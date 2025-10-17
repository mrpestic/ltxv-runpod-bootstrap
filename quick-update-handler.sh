#!/bin/bash
set -euo pipefail

# Скрипт для быстрого обновления только rp_handler.py
# Использует Docker кеш для всех тяжелых слоёв

DOCKER_IMAGE="${DOCKER_IMAGE:-koder007/ltxv-runpod}"
TAG="${TAG:-latest}"

echo "🚀 Быстрый билд с кешированием..."
echo "   Образ: $DOCKER_IMAGE:$TAG"
echo ""

# BuildKit для лучшего кеширования
export DOCKER_BUILDKIT=1

# Билд с кешем (только последние слои пересоберутся)
docker build \
  --progress=plain \
  -t "$DOCKER_IMAGE:$TAG" \
  .

echo ""
echo "✅ Билд завершен!"
echo ""
read -p "📤 Запушить образ в Docker Hub? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  echo "📤 Пушим образ..."
  docker push "$DOCKER_IMAGE:$TAG"
  echo "✅ Готово! Образ $DOCKER_IMAGE:$TAG обновлен"
else
  echo "ℹ️ Пуш пропущен. Для ручного пуша:"
  echo "   docker push $DOCKER_IMAGE:$TAG"
fi

