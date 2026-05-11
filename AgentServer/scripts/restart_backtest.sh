#!/bin/bash
# 安全重启backtest节点
# 用法: bash restart_backtest.sh

set -e
cd "$(dirname "$0")/.."

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

echo "[$(date '+%H:%M:%S')] 正在停止旧backtest节点..."

# 1. 找到占用50057端口的进程
OLD_PID=$(lsof -ti :50057 2>/dev/null || true)

if [ -n "$OLD_PID" ]; then
    echo "[$(date '+%H:%M:%S')] 发现旧进程 PID=$OLD_PID，正在停止..."
    kill -9 "$OLD_PID" 2>/dev/null || true
    sleep 3
    
    # 验证是否已停止
    STILL_RUNNING=$(lsof -ti :50057 2>/dev/null || true)
    if [ -n "$STILL_RUNNING" ]; then
        echo "[$(date '+%H:%M:%S')] ⚠️ 进程未停止，再次kill..."
        kill -9 "$STILL_RUNNING" 2>/dev/null || true
        sleep 3
    fi
fi

# 2. 清理可能残留的python进程
for PID in $(ps aux | grep "NODE_TYPE=backtest" | grep python | grep -v grep | awk '{print $2}'); do
    echo "[$(date '+%H:%M:%S')] 清理残留进程 PID=$PID"
    kill -9 "$PID" 2>/dev/null || true
done
sleep 2

# 3. 确认端口已释放
if lsof -ti :50057 >/dev/null 2>&1; then
    echo "[$(date '+%H:%M:%S')] ❌ 端口50057仍被占用！"
    lsof -i :50057
    exit 1
fi

echo "[$(date '+%H:%M:%S')] 端口50057已释放，启动新backtest节点..."

# 4. 启动新节点
NODE_TYPE=backtest nohup python main.py >> "$LOG_DIR/backtest_restart.log" 2>&1 &
NEW_PID=$!
echo "[$(date '+%H:%M:%S')] 新进程 PID=$NEW_PID"

# 5. 等待启动
for i in $(seq 1 15); do
    sleep 1
    if lsof -ti :50057 >/dev/null 2>&1; then
        echo "[$(date '+%H:%M:%S')] ✅ Backtest节点已启动 (端口50057)"
        echo "[$(date '+%H:%M:%S')] PID=$NEW_PID"
        exit 0
    fi
done

echo "[$(date '+%H:%M:%S')] ❌ 启动超时，检查日志: $LOG_DIR/backtest_restart.log"
exit 1
