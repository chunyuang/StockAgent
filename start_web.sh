#!/bin/bash
fuser -k 8000/tcp 2>/dev/null || true
sleep 2
cd /root/.openclaw/workspace/StockAgent
python AgentServer/main.py web --host 0.0.0.0 --port 8000 > logs/web_node.log 2>&1
