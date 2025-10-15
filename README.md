# ltxv-runpod-bootstrap
Автозапуск LTXV на RunPod

## Serverless на RunPod

Поддержан серверлес-режим с единоразовой загрузкой демона и обработкой задач через `rp_handler.py`. Веса модели запечены в образ для мгновенного cold start.

### Автосборка образа в Docker Hub (рекомендуется)

1. Добавьте секреты в GitHub репозиторий (Settings → Secrets → Actions):
   - `DOCKERHUB_USERNAME` — ваш логин Docker Hub
   - `DOCKERHUB_TOKEN` — Access Token (создать в Docker Hub → Account Settings → Security)

2. При пуше в ветку `runpod-serverless` или `main` GitHub Actions автоматически:
   - Соберёт образ с весами (~30GB, займёт ~20 мин)
   - Запушит в `DOCKERHUB_USERNAME/ltxv-runpod:latest`

3. В RunPod используйте готовый образ из Docker Hub

### Деплой Serverless

1. RunPod → Serverless → Create Endpoint
2. Container Image: `DOCKERHUB_USERNAME/ltxv-runpod:latest`
3. Container Disk: 10–20 GB (веса уже в образе)
4. GPU: A100/H100
5. ENV:
   - `RUN_MODE=serverless`
   - `HF_TOKEN=<опционально>`
6. Warm Pool: 1–2
7. Idle Timeout: 300–600

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
  "result_path": "outputs/2025-01-01/video_output_xxx.mp4",
  "result_url": "https://...",
  "all_results": ["..."]
}
```

## Примечания

- Демон инициализируется один раз при холодном старте через `init()` в `rp_handler.py`, модели держатся в GPU памяти.
- Веса модели (~30GB) запечены в Docker-образ — cold start займёт ~30–60 сек вместо 8 минут.
- Поддержаны text-to-video и image-to-video (`image_base64`, JPEG/PNG в base64).
- Папки `outputs/` и кэши находятся в `/workspace` внутри контейнера.

## Pod на RunPod (полноценный сервер)

Контейнер поддерживает Pod-режим c автозапуском демона, Redis/Celery и API/фронта через `startup.sh`.

### Запуск Pod

1. В RunPod -> Pods -> Create Pod
2. Укажите образ `DOCKERHUB_USERNAME/ltxv-runpod:latest`
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
