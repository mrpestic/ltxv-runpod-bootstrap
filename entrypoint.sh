#!/bin/bash
set -euo pipefail

RUN_MODE="${RUN_MODE:-serverless}"

echo "[entrypoint] RUN_MODE=$RUN_MODE"

if [ "$RUN_MODE" = "serverless" ]; then
  exec /workspace/LTX-Video/env/bin/python /workspace/rp_handler.py
elif [ "$RUN_MODE" = "pod" ]; then
  chmod +x /workspace/startup.sh || true
  exec /workspace/startup.sh
else
  echo "Unknown RUN_MODE: $RUN_MODE" >&2
  exit 1
fi


