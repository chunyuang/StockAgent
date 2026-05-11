#!/bin/bash
# 安全重启web节点
# 用法: bash restart_web.sh

set -e
cd "$(dirname "$0")/.."

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

echo "[$(date '+%H:%M:%S')] 正在停止旧web节点..."

OLD_PID=$(lsof -ti :8000 2>/dev/null || true)

if [ -n "$OLD_PID" ]; then
    echo "[$(date '+%H:%M:%S')] 发现旧进程 PID=$OLD_PID，正在停止..."
    kill -9 "$OLD_PID" 2>/dev/null || true
    sleep 3
fi

for PID in $(ps aux | grep "NODE_TYPE=web" | grep python | grep -v grep | awk '{print $2}'); do
    echo "[$(date '+%H:%M:%S')] 清理残留进程 PID=$PID"
    kill -9 "$PID" 2>/dev/null || true
done
sleep 2

if lsof -ti :8000 >/dev/null 2>&1; then
    echo "[$(date '+%H:%M:%S')] ❌ 端口8000仍被占用！"
    exit 1
fi

echo "[$(date '+%H:%M:%S')] 启动新web节点..."
NODE_TYPE=web nohup python main.py >> "$LOG_DIR/web_restart.log" 2>&1 &
NEW_PID=$!

for i in $(seq 1 15); do
    sleep 1
    if lsof -ti :8000 >/dev/null 2>&1; then
        echo "[$(date '+%H:%M:%S')] ✅ Web节点已启动 (端口8000) PID=$NEW_PID"
        exit 0
    fi
done

echo "[$(date '+%H:%M:%S')] ❌ 启动超时"
exit 1
