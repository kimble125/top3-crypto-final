#!/bin/bash
# Finder에서 더블클릭하면 "1시간마다 Vercel 배포"를 macOS launchd에 등록합니다(매시 7분).
# 맥이 잠들어 있던 시각은 깨어날 때 한 번 실행됩니다. 하루 24번으로 Vercel 무료 한도(하루 100번) 안입니다.
# 처음 한 번은 터미널에서 deploy_vercel.sh 를 직접 실행해 Vercel 프로젝트 연결이 되는지 확인한 뒤 등록하세요.
# 해제: uninstall_snapshot_deploy.command
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
LABEL="com.topo3.snapshot-deploy"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$HERE/deploy_vercel.sh</string></array>
    <key>WorkingDirectory</key><string>$ROOT</string>
    <key>StartCalendarInterval</key><dict><key>Minute</key><integer>7</integer></dict>
    <key>StandardOutPath</key><string>$ROOT/logs/snapshot-deploy.out.log</string>
    <key>StandardErrorPath</key><string>$ROOT/logs/snapshot-deploy.err.log</string>
    <key>ProcessType</key><string>Background</string>
    <key>LowPriorityIO</key><true/>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "=== 등록 완료: 매시 7분에 스냅샷을 만들어 Vercel 에 배포합니다. 기록: $ROOT/logs/snapshot-deploy.out.log ==="
