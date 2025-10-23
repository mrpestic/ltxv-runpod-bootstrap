#!/bin/bash

# Устанавливаем переменные окружения для кеширования
export HF_HOME="/runpod-volume/.cache/huggingface"
export HUGGINGFACE_HUB_CACHE="/runpod-volume/.cache/huggingface"
export TRANSFORMERS_CACHE="/runpod-volume/.cache/huggingface"
export DIFFUSERS_CACHE="/runpod-volume/.cache/huggingface"

# Создаем директории если их нет
mkdir -p "$HF_HOME"
mkdir -p "/runpod-volume/models"

# Логинимся в Hugging Face если есть токен
if [ -n "$HF_TOKEN" ]; then
    echo "🔑 Логинимся в Hugging Face Hub..."
    export HUGGINGFACE_HUB_TOKEN="$HF_TOKEN"
    huggingface-cli login --token "$HF_TOKEN"
fi

# Создаем симлинк для моделей если его нет
if [ ! -L "/workspace/LTX-Video/models" ]; then
    echo "🔗 Создаем симлинк для моделей..."
    ln -sf "/runpod-volume/models" "/workspace/LTX-Video/models"
fi

# Запускаем RunPod handler
echo "🚀 Запускаем RunPod serverless handler..."
cd /workspace
/workspace/LTX-Video/env/bin/python rp_handler.py
