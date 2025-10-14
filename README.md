# ltxv-runpod-bootstrap
Автозапуск LTXV на RunPod

## Serverless на RunPod

Поддержан серверлес-режим с единоразовой загрузкой демона и обработкой задач через `rp_handler.py`.

### Сборка образа локально (опционально)

```bash
docker build -t ghcr.io/<OWNER>/ltxv-runpod-serverless:latest .
# Если хотите запушить вручную в GHCR:
echo $GITHUB_TOKEN | docker login ghcr.io -u <OWNER> --password-stdin
docker push ghcr.io/<OWNER>/ltxv-runpod-serverless:latest
```

Переменные окружения в контейнере (рекомендуется):

- `HF_TOKEN` — токен Hugging Face (опционально, для приватных моделей/ускоренного скачивания)
- `HF_HOME`, `HUGGINGFACE_HUB_CACHE`, `TRANSFORMERS_CACHE`, `DIFFUSERS_CACHE` — кэш (по умолчанию настроены на `/workspace/.cache/huggingface`)

### Деплой Serverless

1. В RunPod -> Serverless -> Create Endpoint
2. Укажите образ `your-dockerhub/ltxv-runpod-serverless:latest`
3. Entrypoint/Command: по умолчанию контейнер запускает `python /workspace/rp_handler.py`
4. Warm Pool (рекомендуется): `1-2` для снижения холодного старта
5. GPU: выберите GPU с достаточной VRAM (например, A100/H100)

Альтернатива: автосборка образа в GHCR (рекомендуется)

1) Включите GitHub Actions. Workflow `.github/workflows/docker-publish.yml` публикует образ в `ghcr.io/<OWNER>/ltxv-runpod-serverless:latest` с использованием `GITHUB_TOKEN`.

2) Убедитесь, что GitHub Packages (GHCR) настроен на публичную видимость для этого образа, чтобы RunPod мог его притянуть.

3) Создать endpoint можно через UI или API RunPod. Пример JSON — `runpod_endpoint_example.json`.

### Формат запроса

`POST` на endpoint RunPod с телом:

```json
{
  "input": {
    "prompt": "A cat walking in the garden",
    "negative_prompt": "worst quality, blurry",
    "width": 1280,
    "height": 720,
    "num_frames": 120,
    "seed": 42,
    "image_base64": null
  }
}
```

Ответ:

```json
{
  "status": "SUCCESS",
  "result": "outputs/2025-01-01/video_output_xxx.mp4",
  "all_results": ["..."]
}
```

## Примечания

- Демон инициализируется один раз при холодном старте через `init()` в `rp_handler.py`, модели держатся в GPU памяти.
- Поддержаны text-to-video и image-to-video (`image_base64`, JPEG/PNG в base64).
- Папки `outputs/` и кэши находятся в `/workspace` внутри контейнера.

## Pod на RunPod (полноценный сервер)

Контейнер поддерживает Pod-режим c автозапуском демона, Redis/Celery и API/фронта через `startup.sh`.

### Запуск Pod

1. В RunPod -> Pods -> Create Pod
2. Укажите образ `your-dockerhub/ltxv-runpod-serverless:latest`
3. В переменных окружения задайте:
   - `RUN_MODE=pod`
   - (опционально) `HF_TOKEN=<ваш токен>`
4. Порты:
   - 8000 — FastAPI
   - 8002 — Frontend
5. Контейнер команда по умолчанию уже `entrypoint.sh`, менять не нужно.

После старта проверка:

- API docs: `http://<POD_IP>:8000/docs`
- Frontend: `http://<POD_IP>:8002/frontend.html`
