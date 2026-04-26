#!/bin/bash
# =============================================
# 🛑 StockAgent 一键停止所有服务脚本
# 功能：优雅停止 Web 服务 + 回测节点 + 前端
# =============================================

# 自动切换到项目根目录
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_ROOT" || {
  echo -e "\033[0;31m❌ 无法进入项目根目录: $PROJECT_ROOT\033[0m"
  exit 1
}
PROJECT_ROOT=$(pwd)

# 颜色配置
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}🛑 停止所有服务${NC}"
echo -e "${YELLOW}============================================${NC}"

# 端口列表（和 restart_all.sh 保持一致）
ports=(
  "8000:Web服务"
  "50056:回测API"
  "50057:回测引擎"
  "5174:前端Vite"
  "50051:Web内部API"
  "50052:回测内部API"
)

# 1. 先按进程名pkill
echo -e "${YELLOW}🔧 1/3 按进程名停止服务...${NC}"
pkill -9 -f "AgentServer/main.py" 2>/dev/null && echo "  ✅ 已停止 Python main.py 进程" || echo "  ⚠️  未找到 Python main.py 进程"
pkill -9 -f "vite\|node.*frontend" 2>/dev/null && echo "  ✅ 已停止 Node/Vite 进程" || echo "  ⚠️  未找到 Node/Vite 进程"
sleep 1

# 2. 按端口清理
echo -e "${YELLOW}🔧 2/3 按端口清理残留进程...${NC}"
for entry in "${ports[@]}"; do
  port=$(echo "$entry" | cut -d: -f1)
  service=$(echo "$entry" | cut -d: -f2-)
  pid=$(lsof -t -i:$port 2>/dev/null)
  if [ -n "$pid" ]; then
    echo "  清理端口 $port ($service)... PID: $pid"
    kill -9 $pid 2>/dev/null
    fuser -k ${port}/tcp 2>/dev/null
  fi
done

sleep 2

# 3. 验证所有端口已释放
echo -e "${YELLOW}🔍 3/3 验证所有端口已释放...${NC}"
all_stopped=1
for entry in "${ports[@]}"; do
  port=$(echo "$entry" | cut -d: -f1)
  service=$(echo "$entry" | cut -d: -f2-)
  if lsof -i:$port >/dev/null 2>&1; then
    echo -e "${RED}❌ 端口 $port ($service) 仍被占用！${NC}"
    all_stopped=0
  else
    echo -e "${GREEN}✅ 端口 $port ($service) 已释放${NC}"
  fi
done

# 清理PID文件
echo -e "${YELLOW}🧹 清理PID文件...${NC}"
rm -f "${PROJECT_ROOT}/logs/web_node.pid" 2>/dev/null
rm -f "${PROJECT_ROOT}/logs/backtest_node.pid" 2>/dev/null
rm -f "${PROJECT_ROOT}/logs/frontend.pid" 2>/dev/null
echo -e "${GREEN}✅ PID文件已清理${NC}"

echo -e "${YELLOW}============================================${NC}"
if [ $all_stopped -eq 1 ]; then
  echo -e "${GREEN}✅ 所有服务已成功停止！${NC}"
  exit 0
else
  echo -e "${RED}❌ 部分服务未能完全停止，请手动检查！${NC}"
  exit 1
fi
