#!/bin/bash
# =============================================
# 🚀 StockAgent 一键重启所有服务脚本
# 功能：强制清理所有旧进程 → 检查端口释放 → 启动 Web 服务 + 回测节点
# 注意：**不会修改任何代码/分支**，只重启服务，不碰Git操作
# =============================================

# 自动切换到脚本所在目录（项目根目录），保证相对路径正确
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR" || {
  echo -e "\033[0;31m❌ 无法进入项目根目录: $SCRIPT_DIR\033[0m"
  exit 1
}

# 颜色配置
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}🔍 运行Python语法检查...${NC}"
echo -e "${YELLOW}============================================${NC}"

# 运行语法检查
echo -e "${GREEN}✅ 强制Python语法&缩进检查${NC}"
for file in \
  AgentServer/nodes/web/api/backtest.py \
  AgentServer/nodes/backtest_engine/node.py \
  AgentServer/nodes/backtest_engine/factor_selection/portfolio_backtest.py
do
  if [ -f "$file" ]; then
    python -m py_compile "$file"
    if [ $? -eq 0 ]; then
      echo -e "${GREEN}✅ $file 语法检查通过${NC}"
    else
      echo -e "${RED}❌ $file 语法错误，请修复！${NC}"
      exit 1
    fi
  else
    echo -e "${YELLOW}⚠️  文件不存在，跳过检查: $file${NC}"
  fi
done

echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}🚀 开始一键重启所有服务...${NC}"
echo -e "${YELLOW}============================================${NC}"

# 1. 强制清理所有占用端口的进程
echo -e "${YELLOW}🔧 1/6 强制清理所有占用端口的进程...${NC}"
pkill -9 -f "AgentServer/main.py" 2>/dev/null || true
pkill -9 -f "vite\|node.*frontend" 2>/dev/null || true
sleep 2

# 清理指定端口
ports=(8000 50056 50057 5174 50051 50052)
for port in "${ports[@]}"; do
  pid=$(lsof -t -i:$port 2>/dev/null)
  if [ -n "$pid" ]; then
    echo "  清理端口$port... PID: $pid"
    kill -9 $pid 2>/dev/null || true
  fi
  # 额外使用 fuser 强制清理
  fuser -k ${port}/tcp 2>/dev/null || true
done

sleep 2

# 2. 严格检查所有端口是否完全释放
echo -e "${YELLOW}🔍 2/6 严格检查所有端口是否完全释放...${NC}"
all_free=1
for port in "${ports[@]}"; do
  if lsof -i:$port >/dev/null 2>&1; then
    # 再杀一次
    pid=$(lsof -t -i:$port 2>/dev/null)
    if [ -n "$pid" ]; then
      echo "  二次清理端口$port... PID: $pid"
      kill -9 $pid 2>/dev/null || true
      sleep 1
    fi
    # 再次检查，如果还是被占用，才提示错误
    if lsof -i:$port >/dev/null 2>&1; then
      echo -e "${RED}❌ 端口 $port 仍被占用！${NC}"
      all_free=0
    else
      echo -e "${GREEN}✅ 端口 $port 已释放${NC}"
    fi
  else
    echo -e "${GREEN}✅ 端口 $port 已释放${NC}"
  fi
done

if [ $all_free -eq 0 ]; then
  echo -e "${RED}❌ 端口未完全释放，请手动清理后重试！${NC}"
  exit 1
fi

# 3. 启动Web服务节点
echo -e "${YELLOW}🌐 3/6 启动Web服务节点...${NC}"
cd $SCRIPT_DIR/AgentServer
nohup python main.py --node-type web > ../logs/web_node.log 2>&1 &
web_pid=$!
echo "  Web服务启动，PID: $web_pid"

# 等待15秒让Web服务完全启动和端口绑定
sleep 15

# 最后检查一次端口是否真的绑定成功
if lsof -i:8000 >/dev/null 2>&1; then
  echo -e "${GREEN}✅ 端口 8000 已成功绑定${NC}"
else
  echo -e "${RED}❌ Web服务启动失败，端口8000未绑定！查看日志: tail -f $SCRIPT_DIR/logs/web_node.log${NC}"
  exit 1
fi

# 检查Web服务进程是否还在运行
if ps -p $web_pid > /dev/null; then
  echo -e "${GREEN}✅ Web服务启动成功，PID: $web_pid${NC}"
else
  echo -e "${RED}❌ Web服务启动失败！查看日志: tail -f $SCRIPT_DIR/logs/web_node.log${NC}"
  exit 1
fi

# 4. 启动回测节点
echo -e "${YELLOW}⚙️  4/6 启动回测节点...${NC}"
NODE_TYPE=backtest nohup python main.py > ../logs/backtest_node.log 2>&1 &
backtest_pid=$!
echo "  回测节点启动，PID: $backtest_pid"

# 等待5秒让回测节点完全启动
sleep 5

# 检查回测节点是否启动成功
if ps -p $backtest_pid > /dev/null; then
  echo -e "${GREEN}✅ 回测节点启动成功，PID: $backtest_pid，端口:50057${NC}"
else
  echo -e "${RED}❌ 回测节点启动失败！查看日志: tail -f $SCRIPT_DIR/logs/backtest_node.log${NC}"
  exit 1
fi

# 5. 启动前端Vite开发服务
echo -e "${YELLOW}🎨 5/6 启动前端Vite开发服务...${NC}"
cd ../frontend
nohup npm run dev -- --port 5174 --host 0.0.0.0 > /tmp/frontend.log 2>&1 &
frontend_pid=$!
echo "  前端服务启动，PID: $frontend_pid"

# 等待3秒让前端服务完全启动
sleep 3

# 检查前端服务是否启动成功
if ps -p $frontend_pid > /dev/null; then
  echo -e "${GREEN}✅ 前端服务启动成功，PID: $frontend_pid，端口:5174${NC}"
else
  echo -e "${YELLOW}⚠️  前端服务启动失败，但不影响后端回测使用，查看日志: tail -f /tmp/frontend.log${NC}"
  # 前端不是必须的，不退出
fi

echo -e "${YELLOW}============================================${NC}"
echo -e "${GREEN}✅ 所有服务启动成功！${NC}"
echo -e "${GREEN}👉 Web服务端口: 8000${NC}"
echo -e "${GREEN}👉 回测节点端口: 50057${NC}"
echo -e "${GREEN}👉 前端访问地址: http://172.16.16.101:5174/ultra-short-v2${NC}"
echo -e "${GREEN}👉 当前分支: $(git rev-parse --abbrev-ref HEAD)${NC}"
echo -e "${YELLOW}============================================${NC}"

exit 0
