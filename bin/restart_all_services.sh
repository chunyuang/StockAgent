#!/bin/bash
# 一键重启所有回测相关服务脚本
# 定位项目根目录（相对于脚本位置）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 使用方式：./restart_all_services.sh

echo "========================================"
echo "🚀 开始重启所有回测服务 $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 记录操作日志
LOG_FILE="$SCRIPT_DIR/logs/service_restart.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始执行服务重启操作" >> $LOG_FILE

# 1. 杀掉所有相关进程
echo "🔍 正在清理所有旧进程..."
pkill -9 -f "AgentServer/main.py" 2>/dev/null
pkill -9 -f "python.*AgentServer" 2>/dev/null

# 等待进程退出
sleep 2

# 检查是否还有残留进程
REMAINING=$(ps aux | grep -E "AgentServer/main.py|python.*AgentServer" | grep -v grep | wc -l)
if [ $REMAINING -gt 0 ]; then
    echo "⚠️  发现残留进程，强制清理..."
    ps aux | grep -E "AgentServer/main.py|python.*AgentServer" | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 清理残留进程 $REMAINING 个" >> $LOG_FILE
else
    echo "✅ 所有旧进程已清理完成"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 所有旧进程已清理完成" >> $LOG_FILE
fi

# 2. 启动回测节点
echo ""
echo "🚀 正在启动回测节点..."
cd "$SCRIPT_DIR"
# 明确设置回测节点类型
NODE_TYPE=backtest nohup python AgentServer/main.py > /tmp/backtest_node.log 2>&1 &
BACKTEST_PID=$!
echo "✅ 回测节点已启动，PID: $BACKTEST_PID"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 回测节点启动成功，PID: $BACKTEST_PID" >> $LOG_FILE

# 3. 启动Web节点
echo ""
echo "🚀 正在启动Web节点..."
# 明确设置Web节点类型，隔离环境变量
NODE_TYPE=web nohup python AgentServer/main.py --node-type web > /tmp/web_node.log 2>&1 &
WEB_PID=$!
echo "✅ Web节点已启动，PID: $WEB_PID"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Web节点启动成功，PID: $WEB_PID" >> $LOG_FILE

# 等待服务启动
sleep 3

# 4. 健康检查
echo ""
echo "🔍 正在进行服务健康检查..."
# 检查回测节点端口
if ss -tlnp | grep :50057 >/dev/null; then
    echo "✅ 回测节点端口50057正常监听"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 回测节点端口50057正常监听" >> $LOG_FILE
else
    echo "❌ 回测节点端口监听失败，请检查日志：cat /tmp/backtest_node.log"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 回测节点端口监听失败" >> $LOG_FILE
fi

# 检查Web节点进程
if ps aux | grep $WEB_PID | grep -v grep >/dev/null; then
    echo "✅ Web节点运行正常"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Web节点运行正常" >> $LOG_FILE
else
    echo "❌ Web节点启动失败，请检查日志：cat /tmp/web_node.log"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Web节点启动失败" >> $LOG_FILE
fi

echo ""
echo "========================================"
echo "✅ 所有服务重启完成！"
echo "📝 操作日志已保存到: $LOG_FILE"
echo "📊 回测节点日志: /tmp/backtest_node.log"
echo "🌐 Web节点日志: /tmp/web_node.log"
echo "========================================"
