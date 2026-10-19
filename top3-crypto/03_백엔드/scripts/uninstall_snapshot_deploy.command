#!/bin/bash
# 1시간마다 Vercel 배포를 해제합니다(이미 배포된 마지막 화면은 Vercel 에 그대로 남음).
LABEL="com.topo3.snapshot-deploy"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "해제 완료" || echo "등록돼 있지 않습니다"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
