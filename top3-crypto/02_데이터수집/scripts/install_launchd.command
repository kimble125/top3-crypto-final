#!/bin/bash
# Finder에서 더블클릭하면 터미널이 열리고, 15분봉 마감 1분 뒤(매시 01·16·31·46분)마다 수집이 돌도록 macOS launchd에 등록합니다.
# 맥이 잠들어 있던 시각의 실행은 깨어난 뒤 한 번으로 합쳐서 돌고, 이전 실행이 끝나기 전에는 새로 시작하지 않습니다(launchd 동작).
# 다시 더블클릭하면 재등록(경로 갱신)됩니다. 해제는 uninstall_launchd.command.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
LABEL="com.topo3.market-collector"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$ROOT/scripts/run_collect.sh</string></array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Minute</key><integer>1</integer></dict>
        <dict><key>Minute</key><integer>16</integer></dict>
        <dict><key>Minute</key><integer>31</integer></dict>
        <dict><key>Minute</key><integer>46</integer></dict>
    </array>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>$ROOT/logs/launchd.out.log</string>
    <key>StandardErrorPath</key><string>$ROOT/logs/launchd.err.log</string>
    <key>ProcessType</key><string>Background</string>
    <key>LowPriorityIO</key><true/>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo
launchctl list | grep "$LABEL" >/dev/null && echo "=== 등록 완료: 매시 01·16·31·46분에 실행됩니다 (첫 실행은 지금). 이 창은 닫아도 됩니다 ===" || echo "!!! 등록 확인 실패. 이 창의 메시지를 캡처해 주세요."
echo "로그: $ROOT/logs/collector.log"
