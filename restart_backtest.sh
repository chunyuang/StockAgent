#!/bin/bash
# 重启回测节点服务

pkill -f "NODE_TYPE=backtest" > /dev/null 2>&1
sleep 2

cd /root/.openclaw/workspace/StockAgent/AgentServer
NODE_TYPE=backtest python main.py > ../logs/backtest_node.log 2>&1 &

echo "回测节点服务已启动，PID: $!"
