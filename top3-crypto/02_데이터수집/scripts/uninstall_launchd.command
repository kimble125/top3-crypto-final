#!/bin/bash
# 더블클릭하면 자동 수집 등록을 해제합니다.
LABEL="com.topo3.market-collector"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "=== 해제 완료 ===" || echo "등록돼 있지 않습니다."
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
