#!/bin/bash
# 감시·백업(10-06 호연 P3, 막힌 작업 33). launchd com.topo3.guard 가 매시 10·40분에 부른다.
# 1) 수집이 40분 넘게 멈췄으면 맥 알림(1시간에 한 번만). 밖으로 보내지 않는다(디스코드 아님).
# 2) 마지막 백업이 20시간보다 오래됐으면 DB 백업(sqlite3 .backup → gzip), 최근 3개만 남긴다.
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DB="$REPO/02_데이터수집/data/raw/market.db"
BK="${TOP3_BACKUP_DIR:-$HOME/top3-backups}"   # 공개 저장소: 백업 위치는 환경 변수로
STATE="$REPO/02_데이터수집/logs/guard.state"
now=$(date +%s)
# -readonly 를 뺐으므로 경로가 틀리면 sqlite3 가 빈 DB 를 만든다 → DB 가 없으면 아무것도 하지 않는다(10-12 검토)
if [ ! -f "$DB" ]; then echo "[$(date '+%Y-%m-%d %H:%M:%S')] DB 없음: $DB"; exit 0; fi
mkdir -p "$BK"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

# 1) 수집 멈춤
# 10-12: -readonly 를 쓰지 않는다. DB 가 WAL 이라 쓰는 프로세스가 모두 닫혀 -wal·-shm 이 없을 때 읽기 전용 연결은
# "unable to open database file" 로 실패한다(매일 첫 백업 실패·xx:40 감시 건너뜀, 막힌작업 11-64). 조회와 .backup 만 하므로 내용은 바뀌지 않는다.
last_ms=$(sqlite3 "$DB" "SELECT MAX(finished_at) FROM run_log" 2>/dev/null || echo "")
if [ -n "$last_ms" ]; then
  age=$(( now - last_ms / 1000 ))
  if [ "$age" -gt 2400 ]; then
    last_alert=$(cat "$STATE" 2>/dev/null || echo 0)
    if [ $(( now - last_alert )) -gt 3600 ]; then
      osascript -e "display notification \"마지막 수집이 $(( age / 60 ))분 전입니다. 02_데이터수집/logs 를 확인하세요.\" with title \"Top 3 Crypto 수집 멈춤\"" >/dev/null 2>&1
      echo "$now" > "$STATE"
      echo "[$(ts)] 알림: 마지막 수집 $(( age / 60 ))분 전"
    fi
  fi
fi

# 2) 하루 한 번 백업
newest=$(ls -t "$BK"/market_*.db.gz 2>/dev/null | head -1)
if [ -z "$newest" ] || [ $(( now - $(stat -f %m "$newest") )) -gt 72000 ]; then
  out="$BK/market_$(date +%Y-%m-%d_%H%M).db"
  if sqlite3 "$DB" ".backup '$out'" && gzip -f "$out"; then
    echo "[$(ts)] 백업 $(basename "$out").gz $(du -h "$out.gz" | cut -f1)"
    ls -t "$BK"/market_*.db.gz | tail -n +4 | while read -r f; do mv "$f" ~/.Trash/ && echo "[$(ts)] 오래된 백업 휴지통: $(basename "$f")"; done
  else
    rm -f "$out"; echo "[$(ts)] 백업 실패"
  fi
fi
