FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

# Базовые пакеты
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
      git \
      python3 \
      python3-venv \
      python3-pip \
      ffmpeg \
      curl \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Клонируем LTX-Video (ветка настраивается переменными окружения)
ARG LTX_REPO_URL=https://github.com/Lightricks/LTX-Video.git
ARG LTX_BRANCH=main

ENV LTX_REPO_URL=$LTX_REPO_URL \
    LTX_BRANCH=$LTX_BRANCH

RUN git clone --depth 1 --branch "$LTX_BRANCH" "$LTX_REPO_URL" /workspace/LTX-Video

# Создаем venv и ставим зависимости
RUN python3 -m venv /workspace/LTX-Video/env && \
    . /workspace/LTX-Video/env/bin/activate && \
    /workspace/LTX-Video/env/bin/python -m pip install --upgrade pip && \
    /workspace/LTX-Video/env/bin/python -m pip install --extra-index-url https://download.pytorch.org/whl/cu121 torch torchvision torchaudio && \
    /workspace/LTX-Video/env/bin/python -m pip install -e '/workspace/LTX-Video[inference-script]' && \
    /workspace/LTX-Video/env/bin/python -m pip install fastapi[all] celery redis && \
    /workspace/LTX-Video/env/bin/python -m pip install git+https://github.com/huggingface/diffusers && \
    /workspace/LTX-Video/env/bin/python -m pip install huggingface_hub imageio imageio-ffmpeg av runpod

# Кэш HF будет в /runpod-volume (персистентный между воркерами)
ENV HF_HOME=/runpod-volume/.cache/huggingface \
    HUGGINGFACE_HUB_CACHE=/runpod-volume/.cache/huggingface \
    TRANSFORMERS_CACHE=/runpod-volume/.cache/huggingface \
    DIFFUSERS_CACHE=/runpod-volume/.cache/huggingface

# Копируем скрипт загрузки весов (будет запускаться в entrypoint)
COPY overlay/download_weights.py /workspace/LTX-Video/download_weights.py
COPY overlay/ltxv-13b-0.9.8-distilled.yaml /workspace/LTX-Video/ltxv-13b-0.9.8-distilled.yaml

# НЕ качаем веса при сборке! Качаем при запуске в /runpod-volume

# Копируем overlay внутрь LTX-Video (в конце, чтобы не инвалидировать кеш для весов)
COPY overlay/ /workspace/LTX-Video/
COPY startup.sh /workspace/startup.sh
COPY entrypoint.sh /workspace/entrypoint.sh

# Копируем handler для RunPod Serverless (в самом конце)
COPY rp_handler.py /workspace/rp_handler.py

# По умолчанию RunPod Serverless использует python handler
ENV PYTHONPATH=/workspace/LTX-Video

# Фикс фрагментации CUDA памяти (важно для высоких разрешений)
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Порты API/Frontend для Pod режима
EXPOSE 8000 8002

# Контейнер ничего не запускает сам в serverless, стартует через runpod.serverless
RUN chmod +x /workspace/startup.sh /workspace/entrypoint.sh

ENV RUN_MODE=serverless
CMD ["/workspace/entrypoint.sh"]


