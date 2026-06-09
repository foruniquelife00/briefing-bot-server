#!/bin/bash
# 브리핑봇 안전 재시작 — 기존 프로세스 전부 종료 후 1개만 실행
# 사용법: bash restart_bot.sh

echo "[1] 기존 bot.py 종료..."
pkill -9 -f "bot.py"
sleep 3

REMAIN=$(ps aux | grep "[b]ot.py" | grep -v grep | wc -l)
if [ "$REMAIN" -ne 0 ]; then
    echo "  ⚠️ 아직 $REMAIN 개 남음 — 재시도"
    pkill -9 -f "bot.py"
    sleep 3
fi

echo "[2] bot.py 1개 시작..."
cd /root/briefing-bot-server
setsid nohup python3 bot.py > bot.log 2>&1 < /dev/null &
sleep 3

echo "[3] 실행 상태 (1개여야 정상):"
ps aux | grep "bot.py" | grep -v grep
