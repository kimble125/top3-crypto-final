#!/bin/bash
# Finder에서 더블클릭하면 보드 서버(포트 8765)를 macOS launchd에 등록합니다.
# 맥이 켜져 있는 동안 항상 실행되고, 꺼지면 자동으로 다시 켜집니다(로그인 시 자동 시작).
# 조원 공유(Tailscale Funnel)는 이 서버를 그대로 바깥 주소에 연결합니다: share_funnel.command
# 해제: uninstall_board_service.command
# 2026-10-20: 접속 기록(access log, 접속 IP 포함)을 남기지 않는다(--no-access-log). 오류 기록만 logs/ 에 남는다(최소 수집).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
LABEL="com.topo3.board-api"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$ROOT/.venv/bin/uvicorn</string><string>app.main:app</string>
        <string>--host</string><string>127.0.0.1</string><string>--port</string><string>8765</string>
        <string>--no-access-log</string>
    </array>
    <key>WorkingDirectory</key><string>$ROOT</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
    <key>StandardOutPath</key><string>$ROOT/logs/board-api.out.log</string>
    <key>StandardErrorPath</key><string>$ROOT/logs/board-api.err.log</string>
    <key>ProcessType</key><string>Background</string>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 2
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/api/engine | grep -q 200; then
  echo "=== 등록 완료: 보드 서버가 http://127.0.0.1:8765 에서 항상 실행됩니다. 이 창은 닫아도 됩니다 ==="
else
  echo "!!! 서버 응답 확인 실패. 로그: $ROOT/logs/board-api.err.log"
fi
