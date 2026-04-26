#!/bin/bash
# =============================================
# 📊 StockAgent 一键状态检查脚本
# 功能：检查所有服务状态 + 版本信息 + 依赖状态
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
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}📊 StockAgent 服务状态检查${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# =============================================
# 1. Git 版本信息
# =============================================
echo -e "${YELLOW}📌 1/7 Git 版本信息${NC}"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
CURRENT_COMMIT=$(git rev-parse --short HEAD)
COMMIT_DATE=$(git log -1 --format=%cd --date=format:"%Y-%m-%d %H:%M:%S")
GIT_STATUS=$(git status --porcelain)

echo -e "  分支: ${GREEN}$CURRENT_BRANCH${NC}"
echo -e "  Commit: ${GREEN}$CURRENT_COMMIT${NC}"
echo -e "  提交时间: ${GREEN}$COMMIT_DATE${NC}"
if [[ -n "$GIT_STATUS" ]]; then
  echo -e "  工作区: ${RED}❌ 有未提交的修改${NC}"
  echo "$GIT_STATUS" | head -5
  if [[ $(echo "$GIT_STATUS" | wc -l) -gt 5 ]]; then
    echo -e "  ... 还有更多文件"
  fi
else
  echo -e "  工作区: ${GREEN}✅ 干净${NC}"
fi
echo ""

# =============================================
# 2. 服务端口状态
# =============================================
echo -e "${YELLOW}📌 2/7 服务端口状态${NC}"
ports=(
  "8000:Web服务"
  "50056:回测API"
  "50057:回测引擎"
  "5174:前端Vite"
  "50051:Web内部API"
  "50052:回测内部API"
)

all_running=1
for entry in "${ports[@]}"; do
  port=$(echo "$entry" | cut -d: -f1)
  service=$(echo "$entry" | cut -d: -f2-)
  if lsof -i:$port >/dev/null 2>&1; then
    pid=$(lsof -t -i:$port 2>/dev/null | head -1)
    echo -e "  ✅ $service ($port): ${GREEN}运行中${NC} (PID: $pid)"
  else
    echo -e "  ❌ $service ($port): ${RED}未运行${NC}"
    all_running=0
  fi
done
echo ""

# =============================================
# 3. 进程状态检查
# =============================================
echo -e "${YELLOW}📌 3/7 进程状态检查${NC}"

# Web节点
if [ -f "${PROJECT_ROOT}/logs/web_node.pid" ]; then
  WEB_PID=$(cat "${PROJECT_ROOT}/logs/web_node.pid")
  if ps -p $WEB_PID > /dev/null 2>&1; then
    echo -e "  ✅ Web节点: ${GREEN}运行中${NC} (PID: $WEB_PID)"
  else
    echo -e "  ❌ Web节点: ${RED}PID文件存在但进程已死亡${NC}"
    all_running=0
  fi
else
  WEB_COUNT=$(ps aux | grep "AgentServer/main.py" | grep "NODE_TYPE=web" | wc -l)
  if [[ $WEB_COUNT -gt 0 ]]; then
    echo -e "  ⚠️  Web节点: ${YELLOW}运行中但无PID文件${NC}"
  else
    echo -e "  ❌ Web节点: ${RED}未运行${NC}"
    all_running=0
  fi
fi

# 回测节点
if [ -f "${PROJECT_ROOT}/logs/backtest_node.pid" ]; then
  BACKTEST_PID=$(cat "${PROJECT_ROOT}/logs/backtest_node.pid")
  if ps -p $BACKTEST_PID > /dev/null 2>&1; then
    echo -e "  ✅ 回测节点: ${GREEN}运行中${NC} (PID: $BACKTEST_PID)"
  else
    echo -e "  ❌ 回测节点: ${RED}PID文件存在但进程已死亡${NC}"
    all_running=0
  fi
else
  BACKTEST_COUNT=$(ps aux | grep "AgentServer/main.py" | grep "NODE_TYPE=backtest" | wc -l)
  if [[ $BACKTEST_COUNT -gt 0 ]]; then
    echo -e "  ⚠️  回测节点: ${YELLOW}运行中但无PID文件${NC}"
  else
    echo -e "  ❌ 回测节点: ${RED}未运行${NC}"
    all_running=0
  fi
fi

# 前端
FRONTEND_COUNT=$(ps aux | grep "vite" | grep -v grep | wc -l)
if [[ $FRONTEND_COUNT -gt 0 ]]; then
  echo -e "  ✅ 前端Vite: ${GREEN}运行中${NC}"
else
  echo -e "  ❌ 前端Vite: ${RED}未运行${NC}"
fi
echo ""

# =============================================
# 4. API 健康检查
# =============================================
echo -e "${YELLOW}📌 4/7 API 健康检查${NC}"
if command -v curl &> /dev/null; then
  # Web服务健康检查
  if lsof -i:8000 >/dev/null 2>&1; then
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/healthz 2>/dev/null || echo "000")
    if [[ $HTTP_STATUS == "200" ]]; then
      VERSION=$(curl -s http://localhost:8000/version 2>/dev/null || echo "未知")
      echo -e "  ✅ Web API: ${GREEN}健康${NC} (状态码: $HTTP_STATUS, 版本: $VERSION)"
    else
      echo -e "  ⚠️  Web API: ${YELLOW}端口开放但 /healthz 返回 $HTTP_STATUS${NC}"
    fi
  else
    echo -e "  ❌ Web API: ${RED}未运行${NC}"
  fi
else
  echo -e "  ⚠️  curl 未安装，跳过API健康检查"
fi
echo ""

# =============================================
# 5. Redis 状态检查
# =============================================
echo -e "${YELLOW}📌 5/7 Redis 状态检查${NC}"
if command -v redis-cli &> /dev/null; then
  REDIS_PING=$(redis-cli PING 2>/dev/null)
  if [[ "$REDIS_PING" == "PONG" ]]; then
    REDIS_KEYS=$(redis-cli DBSIZE 2>/dev/null)
    echo -e "  ✅ Redis: ${GREEN}正常${NC} (Key数量: $REDIS_KEYS)"
  else
    echo -e "  ❌ Redis: ${RED}无法连接${NC}"
    all_running=0
  fi
else
  echo -e "  ⚠️  redis-cli 未安装，跳过Redis检查"
fi
echo ""

# =============================================
# 6. MongoDB 状态检查
# =============================================
echo -e "${YELLOW}📌 6/7 MongoDB 状态检查${NC}"
if command -v mongosh &> /dev/null; then
  MONGO_CHECK=$(mongosh --eval "db.stats()" --quiet mongodb://localhost:27017/stock_agent 2>/dev/null)
  if [[ $? -eq 0 ]]; then
    DOC_COUNT=$(mongosh --eval "db.stock_daily_ak_full.countDocuments({})" --quiet mongodb://localhost:27017/stock_agent 2>/dev/null)
    echo -e "  ✅ MongoDB: ${GREEN}正常${NC} (stock_daily_ak_full: ${DOC_COUNT}条)"
  else
    echo -e "  ❌ MongoDB: ${RED}无法连接${NC}"
    all_running=0
  fi
else
  echo -e "  ⚠️  mongosh 未安装，跳过MongoDB检查"
fi
echo ""

# =============================================
# 7. 日志文件大小检查
# =============================================
echo -e "${YELLOW}📌 7/7 日志文件大小检查${NC}"
for log_file in web_node.log backtest_node.log frontend.log; do
  if [ -f "${PROJECT_ROOT}/logs/$log_file" ]; then
    SIZE=$(du -h "${PROJECT_ROOT}/logs/$log_file" | cut -f1)
    echo -e "  $log_file: ${GREEN}$SIZE${NC}"
  fi
done
echo ""

# =============================================
# 总结
# =============================================
echo -e "${BLUE}============================================${NC}"
if [ $all_running -eq 1 ]; then
  echo -e "${GREEN}✅ 所有服务运行正常！${NC}"
else
  echo -e "${YELLOW}⚠️  部分服务未运行，请检查！${NC}"
fi
echo -e "${BLUE}============================================${NC}"

exit $all_running
