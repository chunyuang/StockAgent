#!/bin/bash
# 重启 Web 服务

pkill -f "NODE_TYPE=web" > /dev/null 2>&1
sleep 2

cd /root/.openclaw/workspace/StockAgent/AgentServer
NODE_TYPE=web python main.py > ../logs/web_node.log 2>&1 &

echo "Web 服务已启动，PID: $!"
