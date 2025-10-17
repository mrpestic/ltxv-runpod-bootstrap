#!/bin/bash
set -euo pipefail

# Скрипт для быстрого обновления только rp_handler.py
# Использует Docker кеш для всех тяжелых слоёв

DOCKER_IMAGE="${DOCKER_IMAGE:-koder007/ltxv-runpod}"
TAG="${TAG:-v0.9.7}"

echo "🚀 Быстрый билд с кешированием для AMD64..."
echo "   Образ: $DOCKER_IMAGE:$TAG"
echo ""

# Создаем buildx builder если нужно
if ! docker buildx ls | grep -q multiarch; then
  echo "📦 Создаем multi-platform builder..."
  docker buildx create --name multiarch --driver docker-container --use
fi

# Используем multiarch builder
docker buildx use multiarch

# Билд для AMD64 с кешем и сразу push
# Используем tty для интерактивного прогресса (показывает детали каждого слоя)
docker buildx build \
  --platform linux/amd64 \
  --progress=tty \
  -t "$DOCKER_IMAGE:$TAG" \
  --push \
  .

echo ""
echo "✅ Билд и пуш завершены!"
echo "🎉 Образ $DOCKER_IMAGE:$TAG готов на Docker Hub (AMD64)"
echo ""
echo "🚀 Для использования на RunPod:"
echo "   Образ: $DOCKER_IMAGE:$TAG"
echo "   Платформа: linux/amd64"

