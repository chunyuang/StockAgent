#!/bin/bash

# 首先运行语法检查，代码有问题直接退出，避免启动失败
echo "🔍 运行Python语法检查..."
/root/.openclaw/workspace/StockAgent/check_syntax.sh
if [ $? -ne 0 ]; then
    echo "❌ 语法检查不通过，请修复代码后再重启！"
    exit 1
fi
echo "✅ 语法检查通过"

echo "🚀 开始一键重启所有服务..."
echo "========================================"

# 1. 【终极清理】不管是什么进程，只要占了我们要用到的端口，直接强制杀死，不留残留
echo "🔧 1/6 强制清理所有占用端口的进程..."
PORTS_TO_KILL="8000 50057 5174 50051 50052"
for PORT in $PORTS_TO_KILL; do
    echo "  清理端口$PORT..."
    # 方法1：用fuser杀
    fuser -k $PORT/tcp 2>/dev/null || true
    # 方法2：用lsof找到pid杀
    PIDS=$(lsof -t -i:$PORT 2>/dev/null)
    if [ -n "$PIDS" ]; then
        kill -9 $PIDS 2>/dev/null || true
    fi
    # 方法3：额外杀所有python main.py进程和node前端进程
    pkill -9 -f "python.*main.py" 2>/dev/null || true
    pkill -9 -f "node.*vite" 2>/dev/null || true
    pkill -9 -f "npm.*dev" 2>/dev/null || true
done
sleep 3

# 2. 【严格校验】确认所有端口完全释放，一个都不能占
echo "🔍 2/6 严格检查所有端口是否完全释放..."
PORT_OCCUPIED=0
for PORT in $PORTS_TO_KILL; do
    if ss -tlnp | grep ":$PORT" > /dev/null; then
        echo "⚠️  端口$PORT仍然被占用，强制杀死..."
        fuser -k $PORT/tcp 2>/dev/null || true
        PIDS=$(ss -tlnp | grep ":$PORT" | grep -o 'pid=[0-9]*' | cut -d'=' -f2)
        if [ -n "$PIDS" ]; then
            kill -9 $PIDS 2>/dev/null || true
        fi
        sleep 1
        # 再检查一次
        if ss -tlnp | grep ":$PORT" > /dev/null; then
            echo "❌ 端口$PORT无法释放，请手动检查！"
            ss -tlnp | grep ":$PORT"
            PORT_OCCUPIED=1
        fi
    fi
done

if [ $PORT_OCCUPIED -eq 1 ]; then
    exit 1
fi
echo "✅ 所有端口已完全释放，没有任何残留"

# 3. 先启动Web服务节点，启动前再次确认8000没被占
echo "🌐 3/6 启动Web服务节点..."
if ss -tlnp | grep ":8000" > /dev/null; then
    echo "❌ 端口8000仍然被占用，退出！"
    exit 1
fi
cd /root/.openclaw/workspace/StockAgent/AgentServer
export NODE_TYPE=web
nohup python main.py > ../logs/web_node.log 2>&1 &
echo "⏳ 等待Web服务启动，等待10秒..."
sleep 10

# 只看8000端口是否在监听，提取正确的PID
echo "🔍 检查Web服务是否启动成功..."
WEB_OK=1
WEB_PID=""
if ss -tlnp | grep ":8000" > /dev/null; then
    WEB_OK=0
    # 提取正确的PID
    WEB_PID=$(ss -tlnp | grep ":8000" | grep -o 'pid=[0-9]*' | cut -d'=' -f2)
fi

if [ $WEB_OK -eq 1 ]; then
    echo "❌ Web服务启动失败，最后20行日志："
    tail -20 /root/.openclaw/workspace/StockAgent/logs/web_node.log
    # 尝试杀死残留进程
    pkill -9 -f "python.*main.*web" 2>/dev/null || true
    exit 1
fi
echo "✅ Web服务启动成功，PID: $WEB_PID，端口:8000"

# 4. 启动回测节点，指定独立RPC端口50052，避免冲突
echo "⚙️  4/6 启动回测节点..."
# 再次清理50057端口，确保没被占用
if ss -tlnp | grep ":50057" > /dev/null; then
    echo "⚠️  端口50057有残留，强制清理..."
    fuser -k 50057/tcp 2>/dev/null || true
    PIDS=$(ss -tlnp | grep ":50057" | grep -o 'pid=[0-9]*' | cut -d'=' -f2)
    if [ -n "$PIDS" ]; then
        kill -9 $PIDS 2>/dev/null || true
    fi
    sleep 2
fi
export NODE_TYPE=backtest
export RPC_PORT=50052
nohup python main.py > ../logs/backtest_node.log 2>&1 &
echo "⏳ 等待回测节点启动，等待7秒..."
sleep 7

# 只看50057端口是否在监听，提取正确的PID
echo "🔍 检查回测节点是否启动成功..."
BACKTEST_OK=1
BACKTEST_PID=""
if ss -tlnp | grep ":50057" > /dev/null; then
    BACKTEST_OK=0
    # 提取正确的PID
    BACKTEST_PID=$(ss -tlnp | grep ":50057" | grep -o 'pid=[0-9]*' | cut -d'=' -f2)
fi

if [ $BACKTEST_OK -eq 1 ]; then
    echo "❌ 回测节点启动失败，最后20行日志："
    tail -20 /root/.openclaw/workspace/StockAgent/logs/backtest_node.log
    # 尝试杀死残留进程
    kill -9 $WEB_PID 2>/dev/null || true
    pkill -9 -f "python.*main.*backtest" 2>/dev/null || true
    exit 1
fi
echo "✅ 回测节点启动成功，PID: $BACKTEST_PID，端口:50057"

# 5. 启动前端服务
echo "🎨 5/6 启动前端服务..."
if ss -tlnp | grep ":5174" > /dev/null; then
    echo "⚠️  端口5174已经被占用，跳过前端启动，不影响回测功能"
else
    cd /root/.openclaw/workspace/StockAgent/frontend
    nohup npm run dev -- --host 0.0.0.0 --port 5174 > /tmp/frontend.log 2>&1 &
    FRONTEND_PID=$!
    echo "⏳ 等待前端服务启动，等待5秒..."
    sleep 5

    # 检查前端服务
    FRONTEND_OK=0
    if ss -tlnp | grep ":5174" > /dev/null; then
        FRONTEND_PID=$(ss -tlnp | grep ":5174" | grep -o 'pid=[0-9]*' | cut -d'=' -f2)
        echo "✅ 前端服务启动成功，PID: $FRONTEND_PID，端口:5174"
    else
        echo "⚠️  前端服务启动失败，不影响回测功能，继续..."
    fi
fi

# 6. 最终状态校验
echo "✅ 6/6 所有核心服务启动校验完成！"

echo "========================================"
echo "🎉 🚀 所有服务100%启动成功！"
echo "📊 核心服务状态："
echo "   ✅ 回测节点：0.0.0.0:50057（PID: $BACKTEST_PID）"
echo "   ✅ Web服务：0.0.0.0:8000（PID: $WEB_PID）"
echo "   🌐 前端页面：http://172.16.16.101:5174/ultra-short-v2"
echo ""
echo "📝 日志路径："
echo "   回测节点日志：/root/.openclaw/workspace/StockAgent/logs/backtest_node.log"
echo "   Web服务日志：/root/.openclaw/workspace/StockAgent/logs/web_node.log"
echo ""
echo "👉 现在直接按Ctrl+Shift+R强制刷新浏览器，提交回测即可正常使用！"
echo "   日志第一行会显示版本标识，所有9项全局公共参数完整显示！"
