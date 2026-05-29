#!/bin/bash
# =============================================
# 🚀 StockAgent 一键重启所有服务
# 功能：强制清理旧进程 → 释放端口 → 构建+部署前端 → 启动所有服务 → 健康检查
# 用法：./bin/restart.sh [--force] [--skip-build] [--skip-redis]
# =============================================
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_ROOT"

# 颜色
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

# 参数
FORCE=0; SKIP_BUILD=0; SKIP_REDIS=0
while [[ $# -gt 0 ]]; do
  case $1 in
    --force) FORCE=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-redis) SKIP_REDIS=1; shift ;;
    *) echo -e "${YELLOW}用法: $0 [--force] [--skip-build] [--skip-redis]${NC}"; exit 1 ;;
  esac
done

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}🚀 StockAgent 一键重启 $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo -e "${CYAN}============================================${NC}"

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo -e "  分支: ${GREEN}$BRANCH${NC}  Commit: ${GREEN}$COMMIT${NC}"

# =============================================
# 1/6 Git安全检查
# =============================================
echo -e "\n${YELLOW}📌 1/6 Git安全检查${NC}"
GIT_DIRTY=$(git status --porcelain 2>/dev/null | head -5)
if [[ -n "$GIT_DIRTY" && $FORCE -eq 0 ]]; then
  echo -e "${RED}❌ 有未提交修改，用 --force 强制继续${NC}"
  echo "$GIT_DIRTY"; exit 1
fi
[[ -n "$GIT_DIRTY" ]] && echo -e "${YELLOW}⚠️  有未提交修改(--force跳过)${NC}" || echo -e "${GREEN}✅ 工作区干净${NC}"

# =============================================
# 2/6 强制清理所有进程和端口
# =============================================
echo -e "\n${YELLOW}📌 2/6 强制清理所有进程和端口${NC}"

# 定义服务: "端口:服务名:进程关键词"
SERVICES=(
  "8000:Web服务(8000):main.py"
  "50051:Web内部API:main.py"
  "50057:回测引擎:main.py"
  "5174:前端Vite:vite"
  "5175:前端Vite(备用):vite"
  "8765:旧Web服务:main.py"
)

# 先杀所有相关进程组
echo -e "  ${CYAN}清理Python进程...${NC}"
PIDS=$(ps aux | grep -E "AgentServer/main\.py" | grep -v grep | awk '{print $2}')
if [[ -n "$PIDS" ]]; then
  echo "  杀Python进程: $(echo $PIDS | tr '\n' ' ')"
  echo "$PIDS" | xargs kill -9 2>/dev/null || true
fi

# 清理所有python main.py但不杀自己
SELF_PID=$$
MAIN_PIDS=$(pgrep -f "python.*main\.py" 2>/dev/null | grep -v "^${SELF_PID}$" || true)
if [[ -n "$MAIN_PIDS" ]]; then
  # 确认是AgentServer下的
  for p in $MAIN_PIDS; do
    cwd=$(readlink /proc/$p/cwd 2>/dev/null || echo "")
    if [[ "$cwd" == *"AgentServer"* || "$cwd" == *"StockAgent"* ]]; then
      echo "  杀main.py PID=$p cwd=$cwd"
      kill -9 $p 2>/dev/null || true
    fi
  done
fi

echo -e "  ${CYAN}清理Vite/Node进程...${NC}"
VITE_PIDS=$(ps aux | grep -E "vite.*517[0-9]|node.*frontend.*517[0-9]" | grep -v grep | awk '{print $2}')
if [[ -n "$VITE_PIDS" ]]; then
  echo "  杀Vite进程: $(echo $VITE_PIDS | tr '\n' ' ')"
  echo "$VITE_PIDS" | xargs kill -9 2>/dev/null || true
fi

# 清理npm子进程
npm_pids=$(pgrep -f "npm.*exec.*vite" 2>/dev/null || true)
if [[ -n "$npm_pids" ]]; then
  echo "  杀npm子进程: $(echo $npm_pids | tr '\n' ' ')"
  echo "$npm_pids" | xargs kill -9 2>/dev/null || true
fi

sleep 2

# 逐端口检查+强制清理
ALL_FREE=1
for entry in "${SERVICES[@]}"; do
  port=$(echo "$entry" | cut -d: -f1)
  name=$(echo "$entry" | cut -d: -f2)
  pid=$(ss -tlnp 2>/dev/null | grep ":${port}[[:space:]]" | grep -oP 'pid=\K[0-9]+' | head -1)
  if [[ -n "$pid" ]]; then
    echo -e "  ${RED}端口 $port ($name) 被PID $pid占用，强制清理${NC}"
    kill -9 "$pid" 2>/dev/null || true
    fuser -k "${port}/tcp" 2>/dev/null || true
    sleep 1
    # 二次检查
    pid2=$(ss -tlnp 2>/dev/null | grep ":${port}[[:space:]]" | grep -oP 'pid=\K[0-9]+' | head -1)
    if [[ -n "$pid2" ]]; then
      echo -e "  ${RED}❌ 端口 $port 仍被占用！PID: $pid2${NC}"
      ALL_FREE=0
    else
      echo -e "  ${GREEN}✅ 端口 $port 已释放${NC}"
    fi
  else
    echo -e "  ${GREEN}✅ 端口 $port 空闲${NC}"
  fi
done

if [[ $ALL_FREE -eq 0 ]]; then
  echo -e "${RED}❌ 有端口未释放，请手动检查后重试${NC}"
  ss -tlnp | grep -E ":8000|:50051|:50057|:5174|:5175|:8765"
  exit 1
fi

# 最终确认: 列出残留Python进程
REMAINING=$(ps aux | grep -E "AgentServer/main\.py" | grep -v grep | wc -l)
if [[ $REMAINING -gt 0 ]]; then
  echo -e "${YELLOW}⚠️  仍有 $REMAINING 个残留Python进程，再次清理...${NC}"
  ps aux | grep -E "AgentServer/main\.py" | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null || true
  sleep 2
fi

# =============================================
# 3/6 清理缓存
# =============================================
echo -e "\n${YELLOW}📌 3/6 清理缓存${NC}"

# Python __pycache__
PYC=$(find . -type d -name "__pycache__" ! -path "*/venv/*" 2>/dev/null | wc -l)
find . -type d -name "__pycache__" ! -path "*/venv/*" -exec rm -rf {} + 2>/dev/null || true
echo -e "  ${GREEN}✅ 清理 $PYC 个 __pycache__${NC}"

# Redis
if [[ $SKIP_REDIS -eq 0 ]]; then
  if command -v redis-cli &>/dev/null; then
    redis-cli FLUSHALL 2>/dev/null && echo -e "  ${GREEN}✅ Redis缓存已清空${NC}" || echo -e "  ${YELLOW}⚠️  Redis清空失败${NC}"
  else
    echo -e "  ${YELLOW}⚠️  redis-cli未找到，跳过${NC}"
  fi
else
  echo -e "  ${YELLOW}⚠️  跳过Redis清空(--skip-redis)${NC}"
fi

# =============================================
# 4/6 构建和部署前端
# =============================================
echo -e "\n${YELLOW}📌 4/6 构建和部署前端${NC}"

if [[ $SKIP_BUILD -eq 0 ]]; then
  echo -e "  ${CYAN}npm run build...${NC}"
  cd "${PROJECT_ROOT}/frontend"
  npm run build > "${PROJECT_ROOT}/logs/frontend_build.log" 2>&1
  if [[ $? -eq 0 ]]; then
    echo -e "  ${GREEN}✅ 前端build成功${NC}"
    # 同步到AgentServer/static
    echo -e "  ${CYAN}同步dist → AgentServer/static...${NC}"
    node sync-dist.mjs >> "${PROJECT_ROOT}/logs/frontend_build.log" 2>&1 || \
      (echo -e "  ${YELLOW}⚠️  sync-dist.mjs失败，手动rsync...${NC}"; \
       rsync -a --delete "${PROJECT_ROOT}/frontend/dist/" "${PROJECT_ROOT}/AgentServer/static/")
    echo -e "  ${GREEN}✅ 静态文件已同步${NC}"
  else
    echo -e "  ${RED}❌ 前端build失败！查看: tail -20 ${PROJECT_ROOT}/logs/frontend_build.log${NC}"
    echo -e "  ${YELLOW}⚠️  继续启动（Vite dev server可用）${NC}"
  fi
  cd "$PROJECT_ROOT"
else
  echo -e "  ${YELLOW}⚠️  跳过前端构建(--skip-build)${NC}"
fi

# 记录分支信息
mkdir -p "${PROJECT_ROOT}/logs"
echo "$BRANCH" > "${PROJECT_ROOT}/logs/runtime_branch_info.txt"

# =============================================
# 5/6 启动所有服务
# =============================================
echo -e "\n${YELLOW}📌 5/6 启动所有服务${NC}"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

# Web服务 (8000 + 50051)
echo -e "  ${CYAN}启动Web服务 (端口8000)...${NC}"
cd "${PROJECT_ROOT}/AgentServer"
NODE_TYPE=web nohup python main.py > "${PROJECT_ROOT}/logs/web_node.log" 2>&1 &
WEB_PID=$!
echo "$WEB_PID" > "${PROJECT_ROOT}/logs/web_node.pid"
echo "  PID: $WEB_PID"

# 回测节点 (50057)
echo -e "  ${CYAN}启动回测节点 (端口50057)...${NC}"
NODE_TYPE=backtest nohup python main.py > "${PROJECT_ROOT}/logs/backtest_node.log" 2>&1 &
BT_PID=$!
echo "$BT_PID" > "${PROJECT_ROOT}/logs/backtest_node.pid"
echo "  PID: $BT_PID"

# Vite dev server (5174)
echo -e "  ${CYAN}启动Vite dev server (端口5174)...${NC}"
cd "${PROJECT_ROOT}/frontend"
nohup npx vite --host 0.0.0.0 --port 5174 > "${PROJECT_ROOT}/logs/frontend.log" 2>&1 &
VITE_PID=$!
echo "$VITE_PID" > "${PROJECT_ROOT}/logs/frontend.pid"
echo "  PID: $VITE_PID"

cd "$PROJECT_ROOT"

# =============================================
# 6/6 健康检查
# =============================================
echo -e "\n${YELLOW}📌 6/6 健康检查 (等待服务启动...)${NC}"

# 等待Web服务启动
echo -e "  ${CYAN}等待Web服务(8000)...${NC}"
for i in $(seq 1 15); do
  if ss -tlnp 2>/dev/null | grep -q ":8000 "; then
    echo -e "  ${GREEN}✅ Web服务启动成功 (8000)${NC}"; break
  fi
  [[ $i -eq 15 ]] && echo -e "  ${RED}❌ Web服务启动超时！${NC}"
  sleep 1
done

# 等待回测节点
echo -e "  ${CYAN}等待回测节点(50057)...${NC}"
for i in $(seq 1 10); do
  if ss -tlnp 2>/dev/null | grep -q ":50057 "; then
    echo -e "  ${GREEN}✅ 回测节点启动成功 (50057)${NC}"; break
  fi
  [[ $i -eq 10 ]] && echo -e "  ${RED}❌ 回测节点启动超时！${NC}"
  sleep 1
done

# 等待Vite
echo -e "  ${CYAN}等待Vite dev server(5174)...${NC}"
sleep 3
VITE_PORT=$(ss -tlnp 2>/dev/null | grep -E ":(5174|5175) " | head -1 | grep -oP ':\K[0-9]+' | head -1)
if [[ -n "$VITE_PORT" ]]; then
  echo -e "  ${GREEN}✅ Vite启动成功 (端口$VITE_PORT)${NC}"
  # 如果Vite用了5175, 更新nginx配置
  if [[ "$VITE_PORT" == "5175" ]]; then
    echo -e "  ${YELLOW}⚠️  Vite用了5175而非5174，nginx代理可能需更新${NC}"
  fi
else
  echo -e "  ${YELLOW}⚠️  Vite可能未启动，检查: tail ${PROJECT_ROOT}/logs/frontend.log${NC}"
fi

# 进程存活检查
echo -e "\n${CYAN}进程状态:${NC}"
for label_pid in "Web:$WEB_PID" "回测:$BT_PID" "Vite:$VITE_PID"; do
  label=$(echo "$label_pid" | cut -d: -f1)
  pid=$(echo "$label_pid" | cut -d: -f2)
  if ps -p "$pid" > /dev/null 2>&1; then
    echo -e "  ${GREEN}✅ $label PID=$pid 运行中${NC}"
  else
    echo -e "  ${RED}❌ $label PID=$pid 已退出${NC}"
  fi
done

# 验证前端版本（检查index.html时间戳）
STATIC_HTML="${PROJECT_ROOT}/AgentServer/static/index.html"
if [[ -f "$STATIC_HTML" ]]; then
  HTML_TIME=$(stat -c '%y' "$STATIC_HTML" 2>/dev/null | cut -d. -f1)
  echo -e "\n  ${CYAN}前端静态文件更新时间: ${GREEN}$HTML_TIME${NC}"
fi

# 最终汇总
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
echo -e "\n${CYAN}============================================${NC}"
echo -e "${GREEN}✅ 重启完成！${NC}"
echo -e "  🌐 前端(开发): ${GREEN}http://${IP}:5174/monitor${NC}"
echo -e "  🌐 前端(Nginx): ${GREEN}http://${IP}/monitor${NC}"
echo -e "  🌐 后端API:     ${GREEN}http://${IP}:8000/api/v1/scanner/status${NC}"
echo -e "  📊 回测引擎:    ${GREEN}http://${IP}:50057${NC}"
echo -e "  📝 Web日志:     ${CYAN}tail -f logs/web_node.log${NC}"
echo -e "  📝 回测日志:    ${CYAN}tail -f logs/backtest_node.log${NC}"
echo -e "  📝 前端日志:    ${CYAN}tail -f logs/frontend.log${NC}"
echo -e "  🔀 分支: ${GREEN}$BRANCH${NC} (${COMMIT})"
echo -e "${CYAN}============================================${NC}"
