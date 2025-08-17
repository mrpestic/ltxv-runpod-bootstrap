#!/bin/bash

set -euo pipefail

# >>> ДОБАВЬ ЭТО СРАЗУ ПОСЛЕ set -euo pipefail <<<
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# ^ путь к папке, где лежит сам startup.sh, фиксируется до любых cd


# Обработка сигналов для корректного завершения
trap 'echo "🛑 Получен сигнал остановки, завершаем..."; exit 0' SIGTERM SIGINT

echo "🔧 Активируем виртуальное окружение..."
cd /workspace

export DEBIAN_FRONTEND=noninteractive
export HF_HOME=/workspace/.cache/huggingface
export HUGGINGFACE_HUB_CACHE=/workspace/.cache/huggingface
export TRANSFORMERS_CACHE=/workspace/.cache/huggingface
export DIFFUSERS_CACHE=/workspace/.cache/huggingface
mkdir -p "$HF_HOME"
apt-get update -y
apt-get install -y --no-install-recommends git

### ── 1) Клонируем чистый LTX-Video ─────────────────────────────────────────
LTX_DIR="/workspace/LTX-Video"
LTX_REPO_URL="${LTX_REPO_URL:-https://github.com/Lightricks/LTX-Video.git}"
LTX_BRANCH="${LTX_BRANCH:-main}"

if [ -d "$LTX_DIR" ]; then
    echo "[LTX] Удаляю старый LTX-Video и клонирую заново"
    rm -rf "$LTX_DIR"
fi

echo "[LTX] Клонируем LTX-Video из $LTX_REPO_URL (branch=$LTX_BRANCH)"
git clone --depth 1 --branch "$LTX_BRANCH" "$LTX_REPO_URL" "$LTX_DIR"
echo "[LTX] Готово: $LTX_DIR"

### ── 2) Накладываем мои файлы поверх ───────────────────────────────────────
MY_OVERLAY="$SCRIPT_DIR/overlay"

echo "[Overlay] SCRIPT_DIR=$SCRIPT_DIR"
echo "[Overlay] Ожидаю появление папки: $MY_OVERLAY"

# Иногда repo ещё докачивается — подождём до 60с
for i in $(seq 1 30); do
  if [ -d "$MY_OVERLAY" ]; then
    echo "[Overlay] Найдена overlay (через $((i*2))с)"
    break
  fi
  echo "[Overlay] overlay ещё нет, пробую снова... ($i/30)"
  sleep 2
done

# Убедимся, что rsync есть
if ! command -v rsync >/dev/null 2>&1; then
  echo "[Overlay] Устанавливаю rsync..."
  apt-get update -y && apt-get install -y rsync
fi

if [ -d "$MY_OVERLAY" ]; then
  echo "[Overlay] Копирую файлы из $MY_OVERLAY -> $LTX_DIR"
  rsync -a --exclude '.git' "$MY_OVERLAY"/ "$LTX_DIR"/
else
  echo "[Overlay] ВНИМАНИЕ: overlay так и не появилась, пропускаю копирование"
fi

# 2. Создаём и активируем виртуальное окружение
if [ ! -d "env" ]; then
    echo "🌱 Создаём виртуальное окружение..."
    python3 -m venv env
fi

source env/bin/activate

# 3. Устанавливаем зависимости проекта (если не установлены)
if ! pip show ltx-video > /dev/null 2>&1; then
    echo "📦 Устанавливаем зависимости LTX-Video..."
    python -m pip install --upgrade pip
    python -m pip install -e .\[inference-script\]
else
    echo "✅ LTX-Video уже установлен, пропускаем установку"
fi

echo "🔧 Устанавливаем системные зависимости..."
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "📦 Устанавливаем ffmpeg..."
    apt-get update -y
    apt-get install -y --no-install-recommends ffmpeg
else
    echo "✅ ffmpeg уже установлен, пропускаем"
fi

echo "🐍 Проверяем Python-библиотеки для видео..."
if ! pip show av > /dev/null 2>&1; then
    pip install -U av
else
    echo "✅ av уже установлен, пропускаем"
fi
if ! pip show imageio > /dev/null 2>&1; then
    pip install -U imageio
else
    echo "✅ imageio уже установлен, пропускаем"
fi
if ! pip show imageio-ffmpeg > /dev/null 2>&1; then
    pip install -U imageio-ffmpeg
else
    echo "✅ imageio-ffmpeg уже установлен, пропускаем"
fi


# 4. Устанавливаем diffusers и huggingface_hub (если не установлены)
if ! (pip show diffusers > /dev/null 2>&1 && pip show huggingface_hub > /dev/null 2>&1); then
    echo "📦 Устанавливаем diffusers и huggingface_hub..."
    pip install -U git+https://github.com/huggingface/diffusers
    pip install huggingface_hub
else
    echo "✅ diffusers и huggingface_hub уже установлены, пропускаем"
fi

# 5. Авторизация Hugging Face (однократно сохраняется в /root/.cache/huggingface)
echo "🔐 Логинимся в Hugging Face..."
huggingface-cli login --token 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

if ! (pip show fastapi > /dev/null 2>&1 && pip show celery > /dev/null 2>&1 && pip show redis > /dev/null 2>&1); then
    echo "📦 Устанавливаем зависимости для API, Celery и фронтенда..."
    pip install "fastapi[all]" celery redis
else
    echo "✅ FastAPI, Celery и Redis уже установлены, пропускаем"
fi

# redis-server нужен на системе (apt install), если не стоит
apt-get update -y
apt-get install -y --no-install-recommends redis-server

# 6. Проверяем и загружаем весы модели
if [ ! -f "models/ltxv-13b-0.9.8-distilled/model.safetensors" ]; then
    echo "🎬 Загружаем весы модели..."
    python download_weights.py
else
    echo "✅ Веса модели уже загружены, пропускаем"
fi

# ====== ЗАПУСК СЕРВИСОВ В ФОНОВОМ РЕЖИМЕ ======

echo "🚦 Запускаем Redis..."
redis-server --daemonize yes
sleep 2 # Даем Redis время на запуск, чтобы Celery мог подключиться

# Функция ожидания готовности демона
wait_for_daemon() {
    local max_wait=300  # Уменьшаем до 300 секунд (5 минут)
    local elapsed=0
    local check_interval=10
    
    echo "⏳ Ожидаем готовности inference демона (максимум ${max_wait}с)..."
    
    while [ $elapsed -lt $max_wait ]; do
        if [ -f "/workspace/LTX-Video/daemon_ready.flag" ]; then
            echo "✅ Демон готов! Время загрузки: ${elapsed}с"
            return 0
        fi
        
        # Проверяем что процесс демона еще живой
        if ! pgrep -f "run_inference_daemon_official.py" > /dev/null; then
            echo "❌ Процесс демона завершился! Проверьте логи."
            return 1
        fi
        
        echo "⌛ Демон загружается... ${elapsed}с (осталось: $((max_wait - elapsed))с)"
        sleep $check_interval
        elapsed=$((elapsed + check_interval))
    done
    
    echo "❌ Таймаут ожидания демона (${max_wait}с)!"
    echo "📋 Проверьте логи: tail -f LTX-Video/inference_daemon_official.log"
    return 1
}

# Функция проверки процесса
check_process() {
    local process_name=$1
    local log_file=$2
    local pid=$(pgrep -f "$process_name" | head -1)
    
    if [ -n "$pid" ]; then
        echo "✅ $process_name запущен (PID: $pid)"
        return 0
    else
        echo "❌ $process_name не запущен!"
        echo "📋 Проверьте логи: tail -f $log_file"
        return 1
    fi
}

echo "🚦 Запускаем inference демон (логи в inference_daemon_official.log)..."
cd /workspace/LTX-Video
nohup env/bin/python run_inference_daemon_official.py > inference_daemon_official.log 2>&1 &
DAEMON_PID=$!
echo "📋 Демон запущен с PID: $DAEMON_PID"

# Даем демону время на инициализацию и проверяем что он не падает сразу
sleep 5
if ! kill -0 $DAEMON_PID 2>/dev/null; then
    echo "❌ Демон завершился сразу после запуска! Проверьте логи:"
    tail -n 20 inference_daemon_official.log
    exit 1
fi
echo "✅ Демон успешно запущен, ждем загрузки моделей..."

# Ждем готовности демона
if wait_for_daemon; then
    echo "🎉 Демон готов, запускаем остальные сервисы..."
else
    echo "💀 Критическая ошибка: демон не запустился"
    echo "🔍 Последние строки лога:"
    tail -n 10 inference_daemon_official.log
    exit 1
fi

echo "🚦 Запускаем Celery воркер (логи в celery_worker.log)..."
cd /workspace/LTX-Video
source env/bin/activate
nohup celery -A my_celery worker --loglevel=info --concurrency=1 > celery_worker.log 2>&1 &
sleep 3 # Даем воркеру время на инициализацию

echo "🚦 Запускаем API сервер (логи в api_server.log)..."
nohup /workspace/LTX-Video/env/bin/python run_api_server.py > api_server.log 2>&1 &
sleep 2

echo "🚦 Запускаем сервер для фронтенда (логи в frontend_server.log)..."
nohup /workspace/LTX-Video/env/bin/python run_frontend_server.py > frontend_server.log 2>&1 &

echo -e "\\n\\n🔍 Проверяем статус всех сервисов..."
sleep 3

# Детальная проверка сервисов
echo "📊 Статус сервисов:"
check_process "run_inference_daemon_official.py" "inference_daemon_official.log"
check_process "celery.*my_celery" "celery_worker.log"  
check_process "run_api_server.py" "api_server.log"
check_process "run_frontend_server.py" "frontend_server.log"

# Проверяем готовность демона
if [ -f "/workspace/LTX-Video/daemon_ready.flag" ]; then
    READY_TIME=$(cat /workspace/LTX-Video/daemon_ready.flag | cut -d: -f2)
    echo "🏁 Inference демон готов к работе (время: $(date -d @$READY_TIME))"
else
    echo "⚠️ Файл готовности демона не найден!"
fi

# Финальная проверка портов
echo "🌐 Проверяем порты:"
if ss -tlnp | grep -q ":8000"; then
    echo "✅ API сервер (порт 8000)"
else
    echo "❌ API сервер не отвечает на порту 8000"
fi

if ss -tlnp | grep -q ":8002"; then
    echo "✅ Фронтенд сервер (порт 8002)"
else
    echo "❌ Фронтенд сервер не отвечает на порту 8002"
fi

echo "--------------------------------------------------------"
echo "➡️  Фронтенд доступен по адресу: http://<ВАШ_IP>:8002/frontend.html"
echo "➡️  API документация: http://<ВАШ_IP>:8000/docs"
echo "--------------------------------------------------------"
echo "👀 Для просмотра логов используйте команды:"
echo "   tail -f inference_daemon_official.log"
echo "   tail -f celery_worker.log"
echo "   tail -f api_server.log"
echo "   tail -f frontend_server.log"
echo "--------------------------------------------------------"
echo "Для остановки скрипта (и всех фоновых процессов) нажмите Ctrl+C"

# Защита от перезагрузки - держим скрипт активным
echo "🛡️ Защита от перезагрузки: держим startup активным..."
echo "📊 Система готова к работе!"

# Держим скрипт активным, чтобы дочерние процессы не завершились
# Используем бесконечный цикл вместо tail -f /dev/null для стабильности
while true; do
    # Проверяем что все сервисы живы каждые 30 секунд
    sleep 30
    
    # Проверяем критические процессы
    if ! pgrep -f "run_inference_daemon_official.py" > /dev/null; then
        echo "⚠️ Inference демон упал! Перезапускаем..."
        cd /workspace/LTX-Video
        nohup env/bin/python run_inference_daemon_official.py > inference_daemon_restart.log 2>&1 &
    fi
    
    if ! pgrep -f "celery.*my_celery" > /dev/null; then
        echo "⚠️ Celery воркер упал! Перезапускаем..."
        cd /workspace/LTX-Video
        source env/bin/activate
        nohup celery -A my_celery worker --loglevel=info --concurrency=1 > celery_worker_restart.log 2>&1 &
    fi
    
    if ! pgrep -f "run_api_server.py" > /dev/null; then
        echo "⚠️ API сервер упал! Перезапускаем..."
        cd /workspace/LTX-Video
        nohup /workspace/LTX-Video/env/bin/python run_api_server.py > api_server_restart.log 2>&1 &
    fi
done
