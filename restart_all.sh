#!/bin/bash
echo "🚀 开始一键重启所有服务..."
echo "========================================"

# 1. 清理所有旧进程
echo "🔧 1/5 清理旧进程..."
pkill -9 -f "python.*main.py" 2>/dev/null || true
pkill -9 -f "node.*vite" 2>/dev/null || true
fuser -k 8000/tcp 50057/tcp 5174/tcp 2>/dev/null || true
sleep 2

# 2. 检查端口是否释放
echo "🔍 2/5 检查端口状态..."
if ss -tlnp | grep -E ":8000|:50057|:5174" > /dev/null; then
    echo "❌ 端口占用未完全释放，强制清理..."
    fuser -k 8000/tcp 50057/tcp 5174/tcp 2>/dev/null || true
    sleep 2
fi
echo "✅ 所有端口已释放"

# 3. 启动回测节点
echo "⚙️  3/5 启动回测节点..."
cd /root/.openclaw/workspace/StockAgent/AgentServer
nohup python main.py --node-type backtest --port 50057 > ../logs/backtest_node.log 2>&1 &
BACKTEST_PID=$!
echo "✅ 回测节点已启动，PID: $BACKTEST_PID"
sleep 3

# 4. 启动Web服务节点
echo "🌐 4/5 启动Web服务节点..."
nohup python main.py web --host 0.0.0.0 --port 8000 > ../logs/web_node.log 2>&1 &
WEB_PID=$!
echo "✅ Web服务节点已启动，PID: $WEB_PID"
sleep 3

# 5. 启动前端服务（开发模式）
echo "🎨 5/5 启动前端开发服务..."
cd /root/.openclaw/workspace/StockAgent/frontend
nohup npm run dev -- --host 0.0.0.0 --port 5174 > /tmp/frontend.log 2>&1 &
FRONTEND_PID=$!
echo "✅ 前端服务已启动，PID: $FRONTEND_PID"
sleep 3

echo "========================================"
echo "✅ 所有服务启动完成！"
echo "📊 服务状态："
echo "   回测节点: 0.0.0.0:50057 (PID: $BACKTEST_PID)"
echo "   Web服务: 0.0.0.0:8000 (PID: $WEB_PID)"
echo "   前端页面: http://172.16.16.101:5174/ultra-short-v2 (PID: $FRONTEND_PID)"
echo ""
echo "📝 日志路径："
echo "   回测节点日志: /root/.openclaw/workspace/StockAgent/logs/backtest_node.log"
echo "   Web服务日志: /root/.openclaw/workspace/StockAgent/logs/web_node.log"
echo "   前端服务日志: /tmp/frontend.log"
echo ""
echo "🔧 快速检查命令："
echo "   查看进程: ps aux | grep -E \"(main.py|npm.*dev)\" | grep -v grep"
echo "   查看端口: ss -tlnp | grep -E \":8000|:50057|:5174\""
echo "   重启服务: ./restart_all.sh"
