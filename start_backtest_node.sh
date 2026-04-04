#!/bin/bash
cd /root/.openclaw/workspace/StockAgent
export PYTHONPATH=.
export NODE_TYPE=backtest
echo "🚀 启动回测引擎节点..."
python AgentServer/main.py > /tmp/backtest_node.log 2>&1 &
echo "✅ 回测节点已启动，PID: $!"
echo "📝 日志路径: /tmp/backtest_node.log"
sleep 2
echo "🔍 检查节点状态..."
ps aux | grep $! | grep -v grep
echo ""
echo "✅ 回测节点启动完成！"
