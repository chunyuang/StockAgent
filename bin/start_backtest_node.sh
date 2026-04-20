#!/bin/bash
cd /root/.openclaw/workspace/StockAgent
export PYTHONPATH=.
export NODE_TYPE=backtest
BACKTEST_PORT=50057

echo "🚀 启动回测引擎节点..."

# 前置检查：清理占用端口的旧进程
echo "🔍 检查端口 ${BACKTEST_PORT} 占用情况..."
OCCUPIED_PID=$(ss -tlnp | grep ":${BACKTEST_PORT}" | awk '{print $6}' | cut -d',' -f2 | cut -d'=' -f2)

if [ -n "${OCCUPIED_PID}" ]; then
  echo "⚠️  发现端口 ${BACKTEST_PORT} 被旧进程(PID: ${OCCUPIED_PID})占用，正在清理..."
  kill -9 ${OCCUPIED_PID} >/dev/null 2>&1
  sleep 1
  echo "✅ 旧进程已清理完成"
fi

# 清理所有残留的AgentServer进程（避免孤儿进程）
echo "🔍 清理残留的回测进程..."
pkill -9 -f "AgentServer/main.py" >/dev/null 2>&1
sleep 1

# 启动新进程
echo "🚀 启动新回测节点..."
python AgentServer/main.py > /tmp/backtest_node.log 2>&1 &
NEW_PID=$!
echo "✅ 回测节点已启动，PID: ${NEW_PID}"
echo "📝 日志路径: /tmp/backtest_node.log"

# 等待启动并校验
sleep 3
echo "🔍 校验节点启动状态..."
if ps aux | grep ${NEW_PID} | grep -v grep >/dev/null; then
  if ss -tlnp | grep ":${BACKTEST_PORT}" | grep ${NEW_PID} >/dev/null; then
    echo ""
    echo "✅ 回测节点启动完成！端口 ${BACKTEST_PORT} 已成功绑定"
    echo "🎯 版本校验：提交回测后日志会显示【NEW CODE 2026-04-08 生效】标识"
  else
    echo "❌ 进程启动成功但端口绑定失败，请检查日志：cat /tmp/backtest_node.log"
    exit 1
  fi
else
  echo "❌ 回测节点启动失败，请检查日志：cat /tmp/backtest_node.log"
  exit 1
fi
