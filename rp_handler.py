import runpod
import os
import sys
import json
import base64
import io
from PIL import Image
import torch
import gc
import logging

# Настраиваем логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Добавляем путь к LTX-Video
sys.path.append('/workspace/LTX-Video')

# Активируем виртуальное окружение
import subprocess
import os
os.environ['PATH'] = '/workspace/LTX-Video/env/bin:' + os.environ['PATH']

# Глобальные переменные для pipeline
global_pipeline = None
global_pipeline_config = None

def init():
    """Инициализация модели - выполняется один раз при старте worker'а"""
    global global_pipeline, global_pipeline_config
    
    if global_pipeline is not None:
        logger.info("✅ Модель уже загружена")
        return
    
    try:
        logger.info("🔄 Начинаем загрузку модели...")
        
        # Проверяем что веса скачаны
        models_ready_file = "/runpod-volume/models/.models_ready"
        if not os.path.exists(models_ready_file):
            logger.info("📥 Веса не найдены, скачиваем...")
            import subprocess
            result = subprocess.run([
                "/workspace/LTX-Video/env/bin/python", "/workspace/LTX-Video/download_weights.py"
            ], cwd="/workspace/LTX-Video", capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"❌ Ошибка при скачивании весов: {result.stderr}")
                raise Exception(f"Не удалось скачать веса: {result.stderr}")
            
            # Создаем маркер файл
            with open(models_ready_file, 'w') as f:
                f.write("ready")
            logger.info("✅ Веса успешно скачаны")
        
        # Импортируем необходимые модули
        from inference_daemon_official import load_pipeline_config, create_ltx_video_pipeline
        
        # Загружаем pipeline (переходим в директорию LTX-Video для загрузки конфига)
        logger.info("📁 Загружаем конфиг из LTX-Video директории...")
        
        # Сохраняем текущую директорию
        original_cwd = os.getcwd()
        
        try:
            # Переходим в директорию LTX-Video
            os.chdir("/workspace/LTX-Video")
            
            global_pipeline_config = load_pipeline_config("ltxv-13b-0.9.8-distilled.yaml")
            global_pipeline = create_ltx_video_pipeline(global_pipeline_config)
            
        finally:
            # Возвращаемся в исходную директорию
            os.chdir(original_cwd)
        
        logger.info("✅ Модель успешно загружена!")
        
        # Очищаем память
        torch.cuda.empty_cache()
        gc.collect()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке модели: {str(e)}")
        raise e

def handler(event):
    """Основная функция обработки запросов"""
    global global_pipeline, global_pipeline_config
    
    try:
        # Проверяем что модель загружена
        if global_pipeline is None or global_pipeline_config is None:
            logger.info("🔄 Модель не загружена, вызываем init()...")
            init()
        
        # Получаем параметры из event
        input_data = event.get('input', {})
        
        prompt = input_data.get('prompt', '')
        negative_prompt = input_data.get('negative_prompt', 'worst quality, inconsistent motion, blurry, jittery, distorted')
        width = int(input_data.get('width', 1280))
        height = int(input_data.get('height', 720))
        num_frames = int(input_data.get('num_frames', 120))
        seed = int(input_data.get('seed', 0))
        image_base64 = input_data.get('image_base64', None)
        
        logger.info(f"🎬 Генерируем видео: {prompt[:50]}...")
        logger.info(f"📐 Размеры: {width}x{height}, кадров: {num_frames}")
        
        # Логируем память GPU до обработки
        if torch.cuda.is_available():
            memory_before = torch.cuda.memory_allocated() / 1024**3
            logger.info(f"💾 Память GPU до обработки: {memory_before:.2f} GB")
        
        # Импортируем функцию inference
        from inference_daemon_official import infer_with_ready_pipeline, InferenceConfig
        
        # Создаем конфиг для inference
        inference_config = InferenceConfig(
            prompt=prompt,
            negative_prompt=negative_prompt,
            height=height,
            width=width,
            num_frames=num_frames,
            seed=seed,
            pipeline_config="ltxv-13b-0.9.8-distilled.yaml",
            frame_rate=25  # Устанавливаем 25 FPS
        )
        
        # Добавляем изображение если есть
        if image_base64:
            # Сохраняем изображение во временный файл
            image_data = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_data)).convert("RGB")
            temp_image_path = f"/tmp/input_image_{seed}.png"
            image.save(temp_image_path)
            
            inference_config.conditioning_media_paths = [temp_image_path]
            inference_config.conditioning_start_frames = [0]
            logger.info(f"🖼️ Используем изображение: {temp_image_path}")
        
        # Выполняем inference
        logger.info("🎯 Начинаем генерацию видео...")
        result_paths = infer_with_ready_pipeline(inference_config, global_pipeline, global_pipeline_config)
        
        # Логируем память GPU после обработки
        if torch.cuda.is_available():
            memory_after = torch.cuda.memory_allocated() / 1024**3
            logger.info(f"💾 Память GPU после обработки: {memory_after:.2f} GB")
        
        # Очищаем память
        torch.cuda.empty_cache()
        gc.collect()
        
        # Обрабатываем результат
        if result_paths and len(result_paths) > 0:
            output_path = result_paths[0]
            logger.info(f"✅ Видео сгенерировано: {output_path}")
            
            # Читаем видео файл и конвертируем в base64
            with open(output_path, 'rb') as f:
                video_data = f.read()
                video_base64 = base64.b64encode(video_data).decode('utf-8')
            
            # Удаляем временные файлы
            if image_base64 and os.path.exists(temp_image_path):
                os.remove(temp_image_path)
            
            return {
                "success": True,
                "video_base64": video_base64,
                "output_path": output_path,
                "prompt": prompt,
                "width": width,
                "height": height,
                "num_frames": num_frames,
                "fps": 25
            }
        else:
            logger.error("❌ Не удалось сгенерировать видео")
            return {
                "success": False,
                "error": "Не удалось сгенерировать видео"
            }
            
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке запроса: {str(e)}")
        
        # Очищаем память при ошибке
        torch.cuda.empty_cache()
        gc.collect()
        
        return {
            "success": False,
            "error": str(e)
        }

# Инициализируем модель при импорте модуля
logger.info("🚀 Инициализируем RunPod handler...")
init()

# Запускаем RunPod serverless
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
