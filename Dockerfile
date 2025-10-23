# Используем базовый образ с CUDA
FROM nvidia/cuda:11.8-devel-ubuntu20.04

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3-pip \
    git \
    wget \
    curl \
    ffmpeg \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libglib2.0-0 \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# Создаем символическую ссылку для python
RUN ln -s /usr/bin/python3.11 /usr/bin/python

# Устанавливаем рабочую директорию
WORKDIR /workspace

# Клонируем LTX-Video репозиторий
RUN git clone https://github.com/Lightricks/LTX-Video.git

# Переходим в директорию LTX-Video
WORKDIR /workspace/LTX-Video

# Устанавливаем Python зависимости
RUN python -m pip install --upgrade pip
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
RUN pip install -r requirements.txt

# Устанавливаем дополнительные зависимости для RunPod
RUN pip install runpod fastapi uvicorn

# Создаем директории для кеша и моделей
RUN mkdir -p /runpod-volume/.cache/huggingface
RUN mkdir -p /runpod-volume/models

# Настраиваем переменные окружения для кеширования
ENV HF_HOME=/runpod-volume/.cache/huggingface \
    HUGGINGFACE_HUB_CACHE=/runpod-volume/.cache/huggingface \
    TRANSFORMERS_CACHE=/runpod-volume/.cache/huggingface \
    DIFFUSERS_CACHE=/runpod-volume/.cache/huggingface

# Копируем необходимые файлы для скачивания весов
COPY overlay/download_weights.py /workspace/LTX-Video/download_weights.py
COPY overlay/ltxv-13b-0.9.8-distilled.yaml /workspace/LTX-Video/ltxv-13b-0.9.8-distilled.yaml

# Копируем overlay файлы
COPY overlay/ /workspace/LTX-Video/

# Копируем startup.sh и entrypoint.sh
COPY startup.sh /workspace/startup.sh
COPY entrypoint.sh /workspace/entrypoint.sh

# Копируем rp_handler.py
COPY rp_handler.py /workspace/rp_handler.py

# Настраиваем переменные окружения для PyTorch
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Устанавливаем права на выполнение
RUN chmod +x /workspace/startup.sh
RUN chmod +x /workspace/entrypoint.sh

# Устанавливаем точку входа
ENTRYPOINT ["/workspace/entrypoint.sh"]
