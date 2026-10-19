#!/bin/bash
# Top3 데이터 수집 진입점. cron / launchd / 수동 실행 공용.
# 로그는 logs/collector.log 에 append 됩니다.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"   # 스크립트 위치 기준. 어디에 클론해도 동작
LOG="$ROOT/logs/collector.log"
# launchd 의 PATH 는 /usr/bin/python3(3.9)을 잡는다. 엔진은 pandas 가 있는 3.14 를 쓰므로 경로를 고정한다.
PY=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3
[ -x "$PY" ] || PY="$(command -v python3 || echo /usr/bin/python3)"
ENGINE="$ROOT/../04_엔진/run_cycle.py"

mkdir -p "$ROOT/logs"

{
  echo ""
  echo "########## $(date '+%Y-%m-%d %H:%M:%S %Z') ##########"
  "$PY" "$ROOT/src/collect.py"
  echo "exit_code=$?"
  # 4시간 분석 사이클. 04_엔진/conf/engine.json 의 cycle_enabled 가 true 일 때만 실제로 계산한다(run_cycle.py 가 확인).
  if [ -f "$ENGINE" ]; then
    "$PY" "$ENGINE"
    echo "engine_exit_code=$?"
  fi
} >> "$LOG" 2>&1

# 로그가 5MB 넘으면 뒤 2000줄만 남기고 잘라냄
if [ -f "$LOG" ]; then
  SIZE=$(wc -c < "$LOG")
  if [ "$SIZE" -gt 5242880 ]; then
    tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
  fi
fi
