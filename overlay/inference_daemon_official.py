#!/usr/bin/env python3
"""
Официальный inference демон для LTX-Video
Запускать: python inference_daemon_official.py
"""

import os
import sys
import json
import time
import glob
import subprocess
import torch
import logging
from pathlib import Path

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('inference_daemon_official.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Добавляем текущую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Импортируем функции inference напрямую
from ltx_video.inference import infer, InferenceConfig, load_pipeline_config, create_ltx_video_pipeline, get_device, calculate_padding, get_unique_filename, seed_everething
from ltx_video.pipelines.pipeline_ltx_video import SkipLayerStrategy

def create_ready_flag():
    """Создаем флаг готовности демона"""
    with open("daemon_ready.flag", "w") as f:
        f.write(str(time.time()))

def clear_gpu_cache():
    """Очищаем GPU кеш, но сохраняем модели"""
    if torch.cuda.is_available():
        # Очищаем только промежуточные данные, но не модели
        torch.cuda.empty_cache()
        logger.info("🧹 Промежуточные данные очищены")

# Глобальная переменная для хранения pipeline
global_pipeline = None
global_pipeline_config = None

def load_models_once():
    """Загружаем модели один раз и держим в памяти"""
    global global_pipeline, global_pipeline_config
    
    logger.info("🎬 Загружаем модели в GPU...")
    
    try:
                # Загружаем конфиг
        global_pipeline_config = load_pipeline_config("ltxv-13b-0.9.8-distilled.yaml")
        logger.info("✅ Конфиг загружен")
        

        # Создаем pipeline один раз
        logger.info("🎯 Создаем pipeline...")
        global_pipeline = create_ltx_video_pipeline(
            ckpt_path=global_pipeline_config["checkpoint_path"],
            precision=global_pipeline_config["precision"],
            text_encoder_model_name_or_path=global_pipeline_config["text_encoder_model_name_or_path"],
            enhance_prompt=True,
            prompt_enhancer_image_caption_model_name_or_path=global_pipeline_config.get(
                "prompt_enhancer_image_caption_model_name_or_path"
            ),
            prompt_enhancer_llm_model_name_or_path=global_pipeline_config.get(
                "prompt_enhancer_llm_model_name_or_path"
            ),
        )
        
        # Если это multi-scale pipeline, создаем соответствующий wrapper
        if global_pipeline_config.get("pipeline_type") == "multi-scale":
            from ltx_video.pipelines.pipeline_ltx_video import LTXMultiScalePipeline
            from ltx_video.inference import create_latent_upsampler
            
            spatial_upscaler_model_path = global_pipeline_config.get("spatial_upscaler_model_path")
            if spatial_upscaler_model_path:
                logger.info("🎯 Создаем latent upsampler...")
                latent_upsampler = create_latent_upsampler(spatial_upscaler_model_path, global_pipeline.device)
                global_pipeline = LTXMultiScalePipeline(global_pipeline, latent_upsampler=latent_upsampler)
                logger.info("✅ Multi-scale pipeline создан")
        
        # Перемещаем pipeline на GPU
        device = get_device()
        logger.info(f"🎯 Перемещаем pipeline на {device}...")
        if hasattr(global_pipeline, 'video_pipeline'):
            # Это multi-scale pipeline
            global_pipeline.video_pipeline = global_pipeline.video_pipeline.to(device)
            # Также перемещаем latent_upsampler на GPU
            if hasattr(global_pipeline, 'latent_upsampler'):
                global_pipeline.latent_upsampler = global_pipeline.latent_upsampler.to(device)
                logger.info(f"🎯 Latent upsampler перемещен на {device}")
        else:
            # Обычный pipeline
            global_pipeline = global_pipeline.to(device)
        
        logger.info("✅ Pipeline создан и готов к работе")
        return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки моделей: {e}")
        return False

def test_pipeline():
    """Тестируем pipeline простой генерацией"""
    global global_pipeline
    
    if global_pipeline is None:
        logger.error("❌ Pipeline не загружен")
        return False
    
    try:
        logger.info("🧪 Тестируем pipeline...")
        
        # Простая тестовая генерация
        test_config = InferenceConfig(
            prompt="test",
            negative_prompt="worst quality",
            height=512,
            width=512,
            num_frames=8,
            seed=42,
            pipeline_config="ltxv-13b-0.9.8-distilled.yaml"
        )
        
        result = generate_with_pipeline(test_config, global_pipeline, global_pipeline_config)
        logger.info(f"✅ Тест успешен: {result}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Тест pipeline не прошёл: {e}")
        return False

def generate_with_pipeline(config, pipeline, pipeline_config):
    """Генерируем видео используя готовый pipeline"""
    # Используем subprocess для вызова официального inference.py
    # Но НЕ очищаем GPU кеш между генерациями
    import subprocess
    import glob
    import os
    from datetime import datetime
    
    # Формируем команду для inference.py
    cmd = [
        "/workspace/LTX-Video/env/bin/python", "inference.py",
        "--prompt", config.prompt,
        "--negative_prompt", config.negative_prompt,
        "--height", str(config.height),
        "--width", str(config.width),
        "--num_frames", str(config.num_frames),
        "--seed", str(config.seed),
        "--pipeline_config", "ltxv-13b-0.9.8-distilled.yaml"
    ]
    
    if config.conditioning_media_paths:
        cmd.extend(["--conditioning_media_paths", config.conditioning_media_paths[0]])
        cmd.extend(["--conditioning_start_frames", "0"])
    
    # Запускаем inference.py с выводом в реальном времени
    logger.info(f"🎯 Запускаем: {' '.join(cmd)}")
    
    # Запускаем subprocess с выводом в реальном времени
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT, 
        text=True, 
        cwd="/workspace/LTX-Video",
        bufsize=1,
        universal_newlines=True
    )
    
    # Читаем вывод в реальном времени
    output_lines = []
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            output = output.strip()
            logger.info(f"🔧 inference.py: {output}")
            output_lines.append(output)
    
    # Ждем завершения процесса
    returncode = process.poll()
    
    if returncode != 0:
        logger.error(f"❌ Ошибка inference.py (код: {returncode})")
        return []
    
    # Ищем созданный файл в папке outputs
    output_files = []
    
    # Сначала ищем в stdout
    for line in output_lines:
        if "Output saved to" in line:
            output_path = line.split("Output saved to")[1].strip()
            if os.path.exists(output_path):
                output_files.append(output_path)
                logger.info(f"✅ Найден файл: {output_path}")
    
    # Если не нашли в stdout, ищем в папке outputs
    if not output_files:
        output_dir = f"outputs/{datetime.today().strftime('%Y-%m-%d')}"
        if os.path.exists(output_dir):
            mp4_files = glob.glob(f"{output_dir}/*.mp4")
            if mp4_files:
                # Берём самый новый файл
                latest_file = max(mp4_files, key=os.path.getctime)
                output_files.append(latest_file)
                logger.info(f"✅ Найден файл: {latest_file}")
    
    return output_files

def infer_with_ready_pipeline(config, ready_pipeline, pipeline_config):
    """Модифицированная версия infer() которая использует готовый pipeline"""
    import torch
    import numpy as np
    import imageio
    from datetime import datetime
    
    # Настройки
    device = get_device()
    seed_everething(config.seed)
    
    # Подготавливаем размеры
    height_padded = ((config.height - 1) // 32 + 1) * 32
    width_padded = ((config.width - 1) // 32 + 1) * 32
    num_frames_padded = ((config.num_frames - 2) // 8 + 1) * 8 + 1
    
    padding = calculate_padding(config.height, config.width, height_padded, width_padded)
    
    logger.warning(f"Padded dimensions: {height_padded}x{width_padded}x{num_frames_padded}")
    
    # Подготавливаем входные данные
    sample = {
        "prompt": config.prompt,
        "prompt_attention_mask": None,
        "negative_prompt": config.negative_prompt,
        "negative_prompt_attention_mask": None,
    }
    
    # 🔥 КРИТИЧНО: generator на CPU чтобы не держал память на GPU
    generator = torch.Generator(device="cpu").manual_seed(config.seed)
    
    # Настройки STG
    stg_mode = pipeline_config.get("stg_mode", "attention_values")
    if stg_mode.lower() == "stg_av" or stg_mode.lower() == "attention_values":
        skip_layer_strategy = SkipLayerStrategy.AttentionValues
    elif stg_mode.lower() == "stg_as" or stg_mode.lower() == "attention_skip":
        skip_layer_strategy = SkipLayerStrategy.AttentionSkip
    elif stg_mode.lower() == "stg_r" or stg_mode.lower() == "residual":
        skip_layer_strategy = SkipLayerStrategy.Residual
    elif stg_mode.lower() == "stg_t" or stg_mode.lower() == "transformer_block":
        skip_layer_strategy = SkipLayerStrategy.TransformerBlock
    else:
        raise ValueError(f"Invalid spatiotemporal guidance mode: {stg_mode}")
    
    # Подготавливаем conditioning если есть
    media_item = None
    conditioning_items = None
    
    # Обрабатываем conditioning_media_paths (для image-to-video как в рабочем скрипте)
    if config.conditioning_media_paths:
        from ltx_video.inference import prepare_conditioning
        logger.info(f"🖼️ Загружаем conditioning images: {config.conditioning_media_paths}")
        conditioning_items = prepare_conditioning(
            conditioning_media_paths=config.conditioning_media_paths,
            conditioning_strengths=config.conditioning_strengths or [1.0],
            conditioning_start_frames=config.conditioning_start_frames or [0],
            height=config.height,
            width=config.width,
            num_frames=config.num_frames,
            padding=padding,
            pipeline=ready_pipeline,
        )
        logger.info(f"🖼️ Conditioning items: {type(conditioning_items)} {len(conditioning_items) if conditioning_items else 'None'}")
        
    # input_media_path НЕ используется для image-to-video (только для video-to-video)
    if config.input_media_path:
        from ltx_video.inference import load_media_file
        logger.info(f"🖼️ Загружаем input media: {config.input_media_path}")
        media_item = load_media_file(
            media_path=config.input_media_path,
            height=config.height,
            width=config.width,
            max_frames=num_frames_padded,
            padding=padding,
        )
        logger.info(f"🖼️ Input media item shape: {media_item.shape if hasattr(media_item, 'shape') else type(media_item)}")
    
    # Используем оригинальные timesteps как в inference.py - без фильтрации для image-to-video
    timesteps = pipeline_config.get("first_pass", {}).get("timesteps", [1.0, 0.9937, 0.9875, 0.9812, 0.975, 0.9094, 0.725])
    if conditioning_items is not None:
        logger.info(f"🖼️ Image-to-video: используем полные timesteps как в оригинале: {timesteps}")
    else:
        logger.info(f"📝 Text-to-video: используем полные timesteps: {timesteps}")
    
    # Проверяем, является ли это multi-scale pipeline
    if hasattr(ready_pipeline, 'video_pipeline'):
        # Multi-scale pipeline - используем оба прохода как в оригинале
        first_pass_config = pipeline_config.get("first_pass", {}).copy()
        logger.info(f"🎬 Multi-scale: используем оригинальные timesteps в first_pass: {timesteps}")
        
        # 📊 Мониторинг памяти перед генерацией
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / 1024**3
            cached = torch.cuda.memory_reserved() / 1024**3
            logger.info(f"🔥 Память перед генерацией: {allocated:.1f}GB allocated, {cached:.1f}GB cached")
            torch.cuda.empty_cache()
            logger.info("🧹 Очистка GPU кеша перед генерацией (multi-scale)")
        
        # 🔥 КРИТИЧНО: используем no_grad для отключения autograd (позволяет callback'и)
        with torch.no_grad():
            images = ready_pipeline(
                downscale_factor=pipeline_config.get("downscale_factor", 0.6666666),
                first_pass=first_pass_config,
                second_pass=pipeline_config.get("second_pass", {}),
                skip_layer_strategy=skip_layer_strategy,
                generator=generator,
                output_type="pt",
                callback_on_step_end=None,
                height=height_padded,
                width=width_padded,
                num_frames=num_frames_padded,
                frame_rate=config.frame_rate,
                **sample,
                media_items=media_item,
                conditioning_items=conditioning_items,
                is_video=True,
                vae_per_channel_normalize=True,
                image_cond_noise_scale=config.image_cond_noise_scale,
                mixed_precision=(pipeline_config.get("precision") == "mixed_precision"),
                offload_to_cpu=False,
                device=device,
                enhance_prompt=True,
            ).images
        
        # 🔥 КРИТИЧНО: очистка памяти между этапами multi-scale
        if torch.cuda.is_available():
            allocated_before = torch.cuda.memory_allocated() / 1024**3
            cached_before = torch.cuda.memory_reserved() / 1024**3
            logger.info(f"🧹 Память между этапами multi-scale: {allocated_before:.1f}GB allocated, {cached_before:.1f}GB cached")
            
            # Принудительная очистка между этапами
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            
            allocated_after = torch.cuda.memory_allocated() / 1024**3
            cached_after = torch.cuda.memory_reserved() / 1024**3
            freed_allocated = allocated_before - allocated_after
            freed_cached = cached_before - cached_after
            logger.info(f"🧹 Очистка между этапами multi-scale: {allocated_after:.1f}GB allocated, {cached_after:.1f}GB cached")
            logger.info(f"🧹 Освобождено между этапами: {freed_allocated:.1f}GB allocated, {freed_cached:.1f}GB cached")
        
        # 🔥 Очищаем промежуточные переменные multi-scale
        del first_pass_config
        if 'generator' in locals():
            del generator
        
        # 🔥 КРИТИЧНО: очищаем conditioning тензоры с GPU
        if conditioning_items is not None:
            try:
                # Если там тензоры - выгружаем на CPU
                conditioning_items = [
                    (t.detach().to("cpu", copy=False) if torch.is_tensor(t) else t)
                    for t in conditioning_items
                ]
            except Exception:
                pass
        del conditioning_items, media_item
    else:
        # Обычный pipeline
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.info("🧹 Очистка GPU кеша перед генерацией (single-scale)")
        # 🔥 КРИТИЧНО: используем no_grad для отключения autograd (позволяет callback'и)
        with torch.no_grad():
            images = ready_pipeline(
                skip_layer_strategy=skip_layer_strategy,
                generator=generator,
                output_type="pt",
                callback_on_step_end=None,
                height=height_padded,
                width=width_padded,
                num_frames=num_frames_padded,
                frame_rate=config.frame_rate,
                **sample,
                media_items=media_item,
                conditioning_items=conditioning_items,
                is_video=True,
                vae_per_channel_normalize=True,
                image_cond_noise_scale=config.image_cond_noise_scale,
                mixed_precision=(pipeline_config.get("precision") == "mixed_precision"),
                offload_to_cpu=False,
                device=device,
                enhance_prompt=True,
                timesteps=timesteps,
                guidance_scale=pipeline_config.get("first_pass", {}).get("guidance_scale", 1.0),
                stg_scale=pipeline_config.get("first_pass", {}).get("stg_scale", 0.0),
                rescaling_scale=pipeline_config.get("first_pass", {}).get("rescaling_scale", 1.0),
                skip_block_list=pipeline_config.get("first_pass", {}).get("skip_block_list", [42]),
            ).images
    
    # Обрезаем до нужного размера
    (pad_left, pad_right, pad_top, pad_bottom) = padding
    pad_bottom = -pad_bottom
    pad_right = -pad_right
    if pad_bottom == 0:
        pad_bottom = images.shape[3]
    if pad_right == 0:
        pad_right = images.shape[4]
    images = images[:, :, : config.num_frames, pad_top:pad_bottom, pad_left:pad_right]
    
    # Сохраняем видео
    output_dir = Path(config.output_path) if config.output_path else Path(f"outputs/{datetime.today().strftime('%Y-%m-%d')}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    result_paths = []
    for i in range(images.shape[0]):
        video_np = images[i].permute(1, 2, 3, 0).cpu().float().numpy()
        video_np = (video_np * 255).astype(np.uint8)
        
        output_filename = get_unique_filename(
            f"video_output_{i}",
            ".mp4",
            prompt=config.prompt,
            seed=config.seed,
            resolution=(config.height, config.width, config.num_frames),
            dir=output_dir,
        )
        
        imageio.mimsave(output_filename, video_np, fps=config.frame_rate)
        logger.info(f"Output saved to {output_filename}")
        result_paths.append(str(output_filename))
    
    # 🔥 КРИТИЧНО: Очищаем память после генерации
    if torch.cuda.is_available():
        # 🔥 АГРЕССИВНО: выгружаем результат на CPU и сразу очищаем GPU
        images_cpu = images.detach().to("cpu", copy=True)  # отдельный буфер на CPU
        del images  # удаляем с GPU
        
        # Принудительная очистка CUDA
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        
        # Логируем состояние памяти после очистки
        allocated = torch.cuda.memory_allocated() / 1024**3
        cached = torch.cuda.memory_reserved() / 1024**3
        logger.info(f"🧹 Память очищена после генерации: {allocated:.1f}GB allocated, {cached:.1f}GB cached")
        
        # Используем images_cpu для сохранения видео
        images = images_cpu
    
    # 🔥 ФИНАЛЬНАЯ очистка: удаляем все большие объекты
    del images_cpu
    if 'conditioning_items' in locals():
        del conditioning_items
    if 'media_item' in locals():
        del media_item
    if 'generator' in locals():
        del generator
    import gc
    gc.collect()
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    torch.cuda.ipc_collect()  # помогает добить IPC-хэндлы
    
    return result_paths

def process_command_file(command_file):
    """Обрабатываем команду из файла"""
    global global_pipeline, global_pipeline_config
    
    try:
        # Читаем команду
        with open(command_file, 'r') as f:
            command = json.load(f)
        
        logger.info(f"📥 Обрабатываем: {command_file}")
        logger.info(f"🎬 Генерируем видео: {command['prompt'][:50]}...")
        
        # Проверяем что pipeline готов
        if global_pipeline is None:
            raise Exception("Pipeline не загружен")
        
        # Создаем конфиг для inference
        inference_config = InferenceConfig(
            prompt=command['prompt'],
            negative_prompt=command['negative_prompt'],
            height=command['height'],
            width=command['width'],
            num_frames=command['num_frames'],
            seed=command['seed'],
            pipeline_config="ltxv-13b-0.9.8-distilled.yaml",
            frame_rate=25  # Устанавливаем 25 FPS как стандарт для видео
        )
        
        # Добавляем изображение если есть
        if command.get('image_path') and os.path.exists(command['image_path']):
            # Для image-to-video используем conditioning_media_paths как в рабочем скрипте
            inference_config.conditioning_media_paths = [command['image_path']]
            inference_config.conditioning_start_frames = [0]
            logger.info(f"🖼️ Устанавливаем conditioning_media_paths: {command['image_path']}")
        
        logger.info(f"🎯 Используем готовый pipeline...")
        
        # Используем готовый pipeline напрямую (без subprocess)
        result_paths = infer_with_ready_pipeline(inference_config, global_pipeline, global_pipeline_config)
        
        # Ищем созданный файл в папке outputs
        output_dir = f"outputs/{time.strftime('%Y-%m-%d')}"
        if os.path.exists(output_dir):
            mp4_files = glob.glob(f"{output_dir}/*.mp4")
            if mp4_files:
                # Берем самый новый файл
                video_path = max(mp4_files, key=os.path.getctime)
                
                if os.path.exists(video_path):
                    logger.info(f"✅ Видео создано: {video_path}")
                    
                    # Создаем результат
                    result = {
                        'status': 'success',
                        'result': video_path,
                        'command_id': os.path.basename(command_file).replace('command_', '').replace('.json', '')
                    }
                    
                    return result
                else:
                    raise Exception(f"Файл не найден: {video_path}")
            else:
                raise Exception("Не найдены MP4 файлы в папке outputs")
        else:
            raise Exception("Папка outputs не существует")
            
    except Exception as e:
        import traceback
        logger.error(f"❌ Ошибка обработки команды: {e}")
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        return {
            'status': 'error',
            'error': str(e),
            'command_id': os.path.basename(command_file).replace('command_', '').replace('.json', '')
        }

def main():
    """Основная функция демона"""
    logger.info("🚀 Запускаем официальный inference демон...")
    
    # Создаем папки
    os.makedirs("inference_commands", exist_ok=True)
    os.makedirs("task_results", exist_ok=True)
    
    # Загружаем модели один раз
    if not load_models_once():
        logger.error("💀 Не удалось загрузить модели, завершаем работу")
        return
    
    # Ставим флаг готовности сразу после полной загрузки моделей
    create_ready_flag()
    logger.info("🏁 Демон готов к работе!")
    logger.info("📁 Ожидаем команды в папке inference_commands/")
    
    # Основной цикл
    while True:
        try:
            # Ищем новые команды
            command_files = glob.glob("inference_commands/command_*.json")
            
            for command_file in command_files:
                # Обрабатываем команду
                result = process_command_file(command_file)
                
                # Сохраняем результат
                result_file = command_file.replace('command_', 'result_')
                with open(result_file, 'w') as f:
                    json.dump(result, f)
                
                # Удаляем команду
                os.remove(command_file)
                
                # Очищаем GPU кеш между генерациями
                clear_gpu_cache()
            
            # Пауза между проверками
            time.sleep(1)
            
        except KeyboardInterrupt:
            logger.info("\n🛑 Демон остановлен пользователем")
            break
        except Exception as e:
            logger.error(f"❌ Ошибка в основном цикле: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main() 