#!/bin/bash
cd /root/.openclaw/workspace/StockAgent
export PYTHONPATH=.
echo "🚀 启动后端Web服务..."
python AgentServer/main.py > /tmp/backend.log 2>&1 &
echo "✅ 后端服务已启动，PID: $!"
echo "📝 日志路径: /tmp/backend.log"
sleep 5
echo "🔍 检查服务状态..."
curl -I http://localhost:8000/api/v1/health
echo ""
echo "✅ 服务启动完成！"
