#!/bin/bash
cd "$SCRIPT_DIR"
# 定位项目根目录（相对于脚本位置）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH=.
echo "🚀 启动后端Web服务..."
python AgentServer/main.py > /tmp/backend.log 2>&1 &
echo "✅ 后端服务已启动，PID: $!"
echo "📝 日志路径: /tmp/backend.log"
sleep 5
echo "🔍 检查服务状态..."
curl -s http://localhost:8000/health | head -c 200
echo ""
echo "✅ 服务启动完成！"
