#!/bin/bash
set -euo pipefail

# Скрипт для локальной сборки и пуша образа в Docker Hub
# Использовать если GitHub Actions не хватает места

DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:-}"
IMAGE_NAME="ltxv-runpod"
TAG="${TAG:-latest}"

if [ -z "$DOCKERHUB_USERNAME" ]; then
  echo "Ошибка: установите DOCKERHUB_USERNAME"
  echo "Пример: export DOCKERHUB_USERNAME=myusername"
  exit 1
fi

echo "🔨 Сборка образа $DOCKERHUB_USERNAME/$IMAGE_NAME:$TAG"
echo "⚠️  Это займёт ~20-30 минут и скачает ~30GB весов"
read -p "Продолжить? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  exit 0
fi

# Логин в Docker Hub
echo "🔐 Логин в Docker Hub..."
docker login

# Сборка
echo "🔨 Сборка образа..."
docker build \
  --platform linux/amd64 \
  -t "$DOCKERHUB_USERNAME/$IMAGE_NAME:$TAG" \
  .

# Пуш
echo "📤 Пуш образа в Docker Hub..."
docker push "$DOCKERHUB_USERNAME/$IMAGE_NAME:$TAG"

echo "✅ Готово! Образ: $DOCKERHUB_USERNAME/$IMAGE_NAME:$TAG"
echo "📋 Используйте в RunPod: $DOCKERHUB_USERNAME/$IMAGE_NAME:$TAG"

