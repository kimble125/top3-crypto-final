#!/bin/bash
# 개발용 API 서버 실행. 처음이면 가상환경부터 만든다.
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
if [ ! -x .venv/bin/uvicorn ]; then
  python3 -m venv .venv && ./.venv/bin/pip install -q -r requirements.txt
fi
exec ./.venv/bin/uvicorn app.main:app --reload --no-access-log --port "${PORT:-8765}"   # 접속 기록(IP) 남기지 않음(2026-10-20)
