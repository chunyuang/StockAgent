#!/bin/bash
# 手动启动回测节点

cd /root/.openclaw/workspace/StockAgent/AgentServer
pkill -f "NODE_TYPE=backtest" > /dev/null 2>&1
sleep 2

NODE_TYPE=backtest nohup python main.py > ../logs/backtest_node.log 2>&1 &
echo "回测节点手动启动，PID: $!"
