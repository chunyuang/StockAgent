#!/bin/bash
# Safe backend restart - kills old process, waits for port release, starts new
set -e
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT/AgentServer"

echo "🔄 安全重启后端..."

# 1. Kill ALL python main.py processes (only from StockAgent)
for pid in $(pgrep -f "python.*main.py" 2>/dev/null || true); do
    cwd=$(readlink /proc/$pid/cwd 2>/dev/null || echo "")
    if [[ "$cwd" == *"StockAgent"* ]] || [[ "$cwd" == *"AgentServer"* ]]; then
        echo "  终止 PID $pid"
        kill -9 $pid 2>/dev/null || true
    fi
done

# 2. Wait for port 8000 to be fully released
echo "  等待端口释放..."
for i in $(seq 1 10); do
    if ! ss -tlnp 2>/dev/null | grep -q ':8000 '; then
        echo "  ✅ 端口8000已释放"
        break
    fi
    sleep 1
done

if ss -tlnp 2>/dev/null | grep -q ':8000 '; then
    echo "❌ 端口8000仍被占用，强制清理"
    fuser -k 8000/tcp 2>/dev/null || true
    sleep 2
fi

# 3. Start fresh
export PYTHONPATH="$PROJECT_ROOT"
export NODE_TYPE=web
nohup "$PROJECT_ROOT/venv/bin/python" main.py > "$PROJECT_ROOT/logs/web_node.log" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PROJECT_ROOT/logs/web_node.pid"
echo "  新进程 PID: $NEW_PID"

# 4. Wait for startup
sleep 8

# 5. Verify
if ss -tlnp 2>/dev/null | grep -q ':8000 '; then
    HEALTH=$(curl -s -m 5 http://localhost:8000/api/v1/scanner/health 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['health']['overall_status'])" 2>/dev/null || echo "fail")
    echo "  ✅ 后端启动成功 (health: $HEALTH)"
else
    echo "  ❌ 后端启动失败，检查日志: tail -f $PROJECT_ROOT/logs/web_node.log"
fi
