#!/bin/bash
# 보드 서버 상시 실행을 해제합니다(조원 공유 링크도 응답하지 않게 됨).
LABEL="com.topo3.board-api"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "해제 완료" || echo "등록돼 있지 않습니다"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
