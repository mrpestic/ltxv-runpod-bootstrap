#!/bin/bash
set -euo pipefail

RUN_MODE="${RUN_MODE:-serverless}"

echo "[entrypoint] RUN_MODE=$RUN_MODE"

# Настройка персистентного кеша в /runpod-volume
CACHE_DIR="/runpod-volume/.cache/huggingface"
MODELS_DIR="/runpod-volume/models"
MARKER_FILE="$MODELS_DIR/.models_ready"

echo "[entrypoint] Настройка кеша моделей..."
mkdir -p "$CACHE_DIR" "$MODELS_DIR"

# Создаем симлинк для models если нужно
if [ ! -L "/workspace/LTX-Video/models" ]; then
  rm -rf "/workspace/LTX-Video/models"
  ln -sf "$MODELS_DIR" "/workspace/LTX-Video/models"
  echo "[entrypoint] Создан симлинк models -> $MODELS_DIR"
fi

# Качаем веса только если нет маркера
if [ ! -f "$MARKER_FILE" ]; then
  echo "[entrypoint] Первый запуск - загружаем веса модели..."
  cd /workspace/LTX-Video
  /workspace/LTX-Video/env/bin/python download_weights.py
  touch "$MARKER_FILE"
  echo "[entrypoint] Веса загружены и закешированы!"
else
  echo "[entrypoint] Используем закешированные веса из $MODELS_DIR"
fi

# Запускаем соответствующий режим
if [ "$RUN_MODE" = "serverless" ]; then
  exec /workspace/LTX-Video/env/bin/python /workspace/rp_handler.py
elif [ "$RUN_MODE" = "pod" ]; then
  chmod +x /workspace/startup.sh || true
  exec /workspace/startup.sh
else
  echo "Unknown RUN_MODE: $RUN_MODE" >&2
  exit 1
fi


