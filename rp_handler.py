#!/usr/bin/env python3
import os
import sys
import base64
import io
import uuid
from typing import Any, Dict

import runpod


# Базовые пути и переменные окружения для кешей и рабочей директории
WORKSPACE_DIR = "/workspace"
LTX_DIR = os.path.join(WORKSPACE_DIR, "LTX-Video")
HF_CACHE = os.path.join(WORKSPACE_DIR, ".cache", "huggingface")


def _ensure_env():
    os.makedirs(HF_CACHE, exist_ok=True)
    os.environ.setdefault("HF_HOME", HF_CACHE)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", HF_CACHE)
    os.environ.setdefault("TRANSFORMERS_CACHE", HF_CACHE)
    os.environ.setdefault("DIFFUSERS_CACHE", HF_CACHE)
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")


def _prepare_imports():
    # Убедимся, что можем импортировать код демона и LTX-Video
    if LTX_DIR not in sys.path:
        sys.path.insert(0, LTX_DIR)


# Глобальные ссылки на pipeline/конфиг демона
global_pipeline = None
global_pipeline_config = None


def init():
    """Инициализация контейнера (cold start): загружаем модели один раз."""
    global global_pipeline, global_pipeline_config

    _ensure_env()
    _prepare_imports()

    # Переходим в директорию проекта LTX-Video
    os.chdir(LTX_DIR)

    # Веса уже запечены в образ на этапе сборки Docker, проверяем их наличие
    ckpt_candidates = [
        os.path.join(LTX_DIR, "models", "ltxv-13b-0.9.8-distilled.safetensors"),
        os.path.join(LTX_DIR, "models", "ltxv-13b-0.9.8-distilled", "model.safetensors"),
    ]
    if not any(os.path.exists(p) for p in ckpt_candidates):
        raise RuntimeError("Веса модели не найдены в образе! Проверьте сборку Docker.")

    # Импортируем модуль демона и загружаем модели
    import importlib
    daemon = importlib.import_module('inference_daemon_official')

    ok = daemon.load_models_once()
    if not ok:
        raise RuntimeError("Не удалось загрузить модели в init()")

    # Ставит флаг готовности (используется и в оригинальном стартапе)
    daemon.create_ready_flag()

    # Прокинем глобальные ссылки
    global_pipeline = daemon.global_pipeline
    global_pipeline_config = daemon.global_pipeline_config


def _decode_image_to_file(image_base64: str) -> str:
    from PIL import Image
    image_bytes = base64.b64decode(image_base64.split(',')[1] if ',' in image_base64 else image_base64)
    image = Image.open(io.BytesIO(image_bytes))
    if image.mode != 'RGB':
        image = image.convert('RGB')
    filename = f"temp_image_{uuid.uuid4().hex}.jpg"
    image.save(filename)
    return filename


def handler(event: Dict[str, Any]) -> Dict[str, Any]:
    """Обработчик задачи RunPod Serverless.

    Ожидаемый payload в event["input"]:
    - prompt (str, required)
    - negative_prompt (str, optional)
    - width (int, optional)
    - height (int, optional)
    - num_frames (int, optional)
    - seed (int, optional)
    - image_base64 (str, optional) — для image-to-video
    """
    from ltx_video.inference import InferenceConfig
    from inference_daemon_official import infer_with_ready_pipeline

    if "input" not in event:
        return {"status": "ERROR", "error": "payload.input is missing"}

    data = event["input"] or {}

    # Если по какой-то причине init не выполнился (или глобали пустые) — инициализируем тут
    global global_pipeline, global_pipeline_config
    if global_pipeline is None or global_pipeline_config is None:
        init()

    prompt = data.get("prompt")
    if not prompt:
        return {"status": "ERROR", "error": "prompt is required"}

    negative_prompt = data.get("negative_prompt", "worst quality, inconsistent motion, blurry, jittery, distorted")
    width = int(data.get("width", 1280))
    height = int(data.get("height", 720))
    num_frames = int(data.get("num_frames", 120))
    seed = int(data.get("seed", 42))
    image_b64 = data.get("image_base64")

    # Подготовка image-to-video, если передано изображение
    conditioning_media_paths = None
    tmp_image_path = None
    if image_b64:
        try:
            tmp_image_path = _decode_image_to_file(image_b64)
            conditioning_media_paths = [tmp_image_path]
        except Exception as e:
            return {"status": "ERROR", "error": f"failed to decode image: {e}"}

    # Сборка конфига инференса
    config = InferenceConfig(
        prompt=prompt,
        negative_prompt=negative_prompt,
        height=height,
        width=width,
        num_frames=num_frames,
        seed=seed,
        pipeline_config="ltxv-13b-0.9.8-distilled.yaml",
        frame_rate=24,
    )

    if conditioning_media_paths:
        config.conditioning_media_paths = conditioning_media_paths
        config.conditioning_start_frames = [0]

    # Генерация через оптимизированную функцию демона с уже загруженным pipeline
    try:
        result_paths = infer_with_ready_pipeline(config, global_pipeline, global_pipeline_config)
    except Exception as e:
        # Уборка временного файла
        if tmp_image_path and os.path.exists(tmp_image_path):
            try:
                os.remove(tmp_image_path)
            except Exception:
                pass
        return {"status": "ERROR", "error": str(e)}

    # Уборка временного файла изображения
    if tmp_image_path and os.path.exists(tmp_image_path):
        try:
            os.remove(tmp_image_path)
        except Exception:
            pass

    if not result_paths:
        return {"status": "ERROR", "error": "no output produced"}

    # Пытаемся загрузить файл в хранилище RunPod и вернуть публичный URL
    result_url = None
    try:
        from runpod.serverless.utils import rp_upload
        upload_result = rp_upload.upload_file_to_bucket(result_paths[0])
        if isinstance(upload_result, str):
            result_url = upload_result
        elif isinstance(upload_result, dict):
            result_url = upload_result.get("url") or upload_result.get("file_url")
    except Exception:
        result_url = None

    # Возвращаем путь и, если получилось, URL
    return {
        "status": "SUCCESS",
        "result_path": result_paths[0],
        "result_url": result_url,
        "all_results": result_paths,
    }


runpod.serverless.start({
    "handler": handler,
    "init": init,
})


