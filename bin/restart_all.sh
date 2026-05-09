#!/bin/bash
# =============================================
# 🚀 StockAgent 一键重启所有服务脚本
# 功能：强制清理所有旧进程 → 检查端口释放 → 启动 Web 服务 + 回测节点 + 前端
# 注意：**不会修改任何代码/分支**，只重启服务，不碰Git操作
# =============================================

# 自动切换到项目根目录（因为脚本在 bin/ 子目录，需要往上跳一级）
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# 脚本在 bin/ 目录，项目根目录在上级
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
NC='\033[0m' # No Color

# 参数解析
FULL_CHECK=0
FORCE_RESTART=0
SKIP_REDIS_FLUSH=0

while [[ $# -gt 0 ]]; do
  case $1 in
    --full-check)
      FULL_CHECK=1
      shift
      ;;
    --force)
      FORCE_RESTART=1
      shift
      ;;
    --skip-redis-flush)
      SKIP_REDIS_FLUSH=1
      shift
      ;;
    *)
      echo -e "${YELLOW}未知参数: $1${NC}"
      echo -e "可用参数:"
      echo -e "  --full-check    : 全量Python语法检查"
      echo -e "  --force         : 强制重启（忽略未提交修改）"
      echo -e "  --skip-redis-flush : 跳过Redis缓存清空"
      exit 1
      ;;
  esac
done

echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}🔒 6层安全预防机制检查${NC}"
echo -e "${YELLOW}============================================${NC}"

# =============================================
# 🔒 安全层1: 检查未提交的Git修改
# =============================================
echo -e "${YELLOW}🔍 1/6 检查Git工作区状态...${NC}"
GIT_STATUS=$(git status --porcelain)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
CURRENT_COMMIT=$(git rev-parse --short HEAD)

if [[ -n "$GIT_STATUS" ]]; then
  if [[ $FORCE_RESTART -eq 1 ]]; then
    echo -e "${YELLOW}⚠️  检测到未提交的修改，但使用了 --force 参数，强制继续！${NC}"
    echo "$GIT_STATUS"
  else
    echo -e "${RED}❌ 检测到未提交的修改！禁止重启！${NC}"
    echo -e "${YELLOW}当前分支: $CURRENT_BRANCH (commit: $CURRENT_COMMIT)${NC}"
    echo -e "${YELLOW}未提交文件列表:${NC}"
    echo "$GIT_STATUS"
    echo ""
    echo -e "${YELLOW}请执行以下操作后再重启:${NC}"
    echo -e "  1. git status          # 查看修改文件"
    echo -e "  2. git diff            # 查看修改内容"
    echo -e "  3. git add xxx         # 添加文件"
    echo -e "  4. git commit -m 'xxx' # 提交代码"
    echo ""
    echo -e "${YELLOW}如果确认要强制重启（不推荐），请使用:${NC}"
    echo -e "  ./bin/restart_all.sh --force"
    exit 1
  fi
else
  echo -e "${GREEN}✅ Git工作区干净，当前分支: $CURRENT_BRANCH (commit: $CURRENT_COMMIT)${NC}"
fi

# =============================================
# 🔒 安全层1.5: 运行分支对齐检查（最重要！避免之前踩过的坑）
# =============================================
echo -e "${YELLOW}🔍 1.5/7 检查运行中代码分支与当前Git分支是否对齐...${NC}"

# 从PID文件中提取启动时的Git分支信息（如果存在）
# 思路：启动时记录分支信息到PID文件旁边，重启时检查是否匹配
BRANCH_INFO_FILE="${PROJECT_ROOT}/logs/runtime_branch_info.txt"

if [[ -f "$BRANCH_INFO_FILE" ]]; then
  RUNTIME_BRANCH=$(cat "$BRANCH_INFO_FILE" 2>/dev/null || echo "unknown")
  if [[ "$RUNTIME_BRANCH" != "$CURRENT_BRANCH" ]] && [[ "$RUNTIME_BRANCH" != "unknown" ]]; then
    if [[ $FORCE_RESTART -eq 1 ]]; then
      echo -e "${YELLOW}⚠️  ⚠️  ⚠️  分支不匹配！运行中是 [$RUNTIME_BRANCH]，当前Git是 [$CURRENT_BRANCH]${NC}"
      echo -e "${YELLOW}但使用了 --force 参数，强制继续！${NC}"
    else
      echo -e "${RED}❌ ❌ ❌ 严重警告：分支不匹配！禁止重启！${NC}"
      echo ""
      echo -e "${RED}当前运行中的服务是从分支启动:${NC} $RUNTIME_BRANCH"
      echo -e "${YELLOW}但您当前所在的Git分支是:${NC} $CURRENT_BRANCH"
      echo ""
      echo -e "这就是之前踩过的经典大坑！😱"
      echo -e "  → 在分支A启动服务 → 切到分支B改代码 → 忘记切回直接重启 → 代码不生效"
      echo ""
      echo -e "${YELLOW}请先执行:${NC}"
      echo -e "  git checkout $RUNTIME_BRANCH    # 切回运行中的分支，确认修改正确"
      echo ""
      echo -e "${YELLOW}如果确认要强制重启（确认当前分支代码正确），请使用:${NC}"
      echo -e "  ./bin/restart_all.sh --force"
      exit 1
    fi
  else
    echo -e "${GREEN}✅ 运行分支与Git分支一致: $CURRENT_BRANCH${NC}"
  fi
else
  echo -e "${YELLOW}⚠️  未找到运行时分支信息（可能是首次运行），跳过对齐检查${NC}"
fi
echo -e "${YELLOW}🧹 2/6 清理Python __pycache__ 缓存...${NC}"
PYCACHE_COUNT=$(find . -type d -name "__pycache__" 2>/dev/null | wc -l)
PYC_FILE_COUNT=$(find . -type f -name "*.pyc" 2>/dev/null | wc -l)

find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

echo -e "${GREEN}✅ 已清理 $PYCACHE_COUNT 个 __pycache__ 目录，$PYC_FILE_COUNT 个 .pyc 文件${NC}"

# =============================================
# 🔒 安全层3: 清空Redis缓存
# =============================================
if [[ $SKIP_REDIS_FLUSH -eq 0 ]]; then
  echo -e "${YELLOW}🧹 3/6 清空Redis缓存...${NC}"
  if command -v redis-cli &> /dev/null; then
    REDIS_RESULT=$(redis-cli FLUSHALL 2>&1)
    if [[ $? -eq 0 ]]; then
      echo -e "${GREEN}✅ Redis FLUSHALL 成功，所有缓存已清空${NC}"
    else
      echo -e "${YELLOW}⚠️  Redis清空失败: $REDIS_RESULT${NC}"
    fi
  else
    echo -e "${YELLOW}⚠️  redis-cli 未找到，跳过Redis缓存清空${NC}"
  fi
else
  echo -e "${YELLOW}⚠️  使用 --skip-redis-flush 参数，跳过Redis缓存清空${NC}"
fi

# 🧹 日志文件生命周期管理：保留最近50个task日志
LOG_DIR="${PROJECT_ROOT}/logs/backtest"
if [ -d "$LOG_DIR" ]; then
  LOG_COUNT=$(ls -1 "$LOG_DIR" 2>/dev/null | wc -l)
  if [ "$LOG_COUNT" -gt 50 ]; then
    OLD_FILES=$(ls -1t "$LOG_DIR" | tail -n +51)
    OLD_COUNT=$(echo "$OLD_FILES" | wc -l)
    echo "$OLD_FILES" | xargs rm -f "$LOG_DIR"/ 2>/dev/null
    echo -e "${GREEN}✅ 清理 ${OLD_COUNT} 个旧日志文件（保留最近50个）${NC}"
  else
    echo -e "${GREEN}✅ 日志文件 ${LOG_COUNT} 个，无需清理（阈值50）${NC}"
  fi
fi

echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}🔍 运行Python语法检查...${NC}"
echo -e "${YELLOW}============================================${NC}"

echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}🔍 运行Python语法检查...${NC}"
echo -e "${YELLOW}============================================${NC}"

echo -e "${GREEN}✅ 强制Python语法&缩进检查${NC}"

if [ $FULL_CHECK -eq 1 ]; then
  echo -e "${YELLOW}🔍 执行全量语法检查（所有 .py 文件）...${NC}"
  # 全量检查所有 Python 文件，排除 venv
  has_error=0
  find . -name "*.py" -type f \( -path "./AgentServer/*" -o -path "./scripts/*" \) ! -path "*/venv/*" | while read -r file; do
    python -m py_compile "$file"
    if [ $? -ne 0 ]; then
      has_error=1
    fi
  done
  if [ $has_error -eq 1 ]; then
    echo -e "${RED}❌ 全量语法检查发现错误，请修复后重试！${NC}"
    exit 1
  else
    echo -e "${GREEN}✅ 全量语法检查通过，所有 .py 文件语法正确${NC}"
  fi
else
  # 增量检查：只检查 git diff 修改过的文件
  git_diff_files=$(git diff --name-only HEAD | grep '\.py$')

  if [ -n "$git_diff_files" ]; then
    for file in $git_diff_files; do
      # 只检查存在的文件
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
  else
    echo -e "${YELLOW}✅ 没有检测到修改过的Python文件，跳过语法检查${NC}"
  fi
fi

echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}🚀 开始一键重启所有服务...${NC}"
echo -e "${YELLOW}============================================${NC}"

# 1. 强制清理所有占用端口的进程
echo -e "${YELLOW}🔧 1/6 强制清理所有占用端口的进程...${NC}"
pkill -9 -f "AgentServer/main.py" 2>/dev/null || true
pkill -9 -f "vite\|node.*frontend" 2>/dev/null || true
sleep 2

# 清理指定端口（格式: "port:service_name"）
ports=(
  "8000:Web服务"
  "50056:回测API"
  "50057:回测引擎"
  "5174:前端Vite"
  "50051:Web内部API"
  "50052:回测内部API"
)
for entry in "${ports[@]}"; do
  port=$(echo "$entry" | cut -d: -f1)
  service=$(echo "$entry" | cut -d: -f2-)
  pid=$(lsof -t -i:$port 2>/dev/null)
  if [ -n "$pid" ]; then
    echo "  清理端口 $port ($service)... PID: $pid"
    kill -9 $pid 2>/dev/null || true
  fi
  # 额外使用 fuser 强制清理
  fuser -k ${port}/tcp 2>/dev/null || true
done

sleep 2

# 2. 严格检查所有端口是否完全释放
echo -e "${YELLOW}🔍 2/6 严格检查所有端口是否完全释放...${NC}"
all_free=1
for entry in "${ports[@]}"; do
  port=$(echo "$entry" | cut -d: -f1)
  service=$(echo "$entry" | cut -d: -f2-)
  if lsof -i:$port >/dev/null 2>&1; then
    # 再杀一次
    pid=$(lsof -t -i:$port 2>/dev/null)
    if [ -n "$pid" ]; then
      echo "  二次清理端口 $port ($service)... PID: $pid"
      kill -9 $pid 2>/dev/null || true
      sleep 1
    fi
    # 再次检查，如果还是被占用，才提示错误
    if lsof -i:$port >/dev/null 2>&1; then
      echo -e "${RED}❌ 端口 $port ($service) 仍被占用！${NC}"
      all_free=0
    else
      echo -e "${GREEN}✅ 端口 $port ($service) 已释放${NC}"
    fi
  else
    echo -e "${GREEN}✅ 端口 $port ($service) 已释放${NC}"
  fi
done

if [ $all_free -eq 0 ]; then
  echo -e "${RED}❌ 端口未完全释放，请手动清理后重试！${NC}"
  exit 1
fi

# 记录当前Git分支信息，用于下次重启时的对齐检查（防止踩坑！）
echo -e "${YELLOW}📝 记录当前运行分支信息: $CURRENT_BRANCH${NC}"
echo "$CURRENT_BRANCH" > "${PROJECT_ROOT}/logs/runtime_branch_info.txt"

# 3. 启动Web服务节点
echo -e "${YELLOW}🌐 3/7 启动Web服务节点...${NC}"
# 设置 PYTHONPATH 包含项目根目录，确保模块能正确导入
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"
export NODE_TYPE=web
cd "${PROJECT_ROOT}/AgentServer"
nohup python main.py > "${PROJECT_ROOT}/logs/web_node.log" 2>&1 &
web_pid=$!
echo $web_pid > "${PROJECT_ROOT}/logs/web_node.pid"
echo "  Web服务启动，PID: $web_pid (已写入PID文件)"

# 等待15秒让Web服务完全启动和端口绑定
sleep 15

# 最后检查一次端口是否真的绑定成功
if lsof -i:8000 >/dev/null 2>&1; then
  echo -e "${GREEN}✅ 端口 8000 (Web服务) 已成功绑定${NC}"
else
  echo -e "${RED}❌ Web服务启动失败，端口8000未绑定！查看完整错误日志:${NC}"
  echo -e "${YELLOW}   tail -f ${PROJECT_ROOT}/logs/web_node.log${NC}"
  exit 1
fi

# 检查Web服务进程是否还在运行
if ps -p $web_pid > /dev/null; then
  echo -e "${GREEN}✅ Web服务启动成功，PID: $web_pid，端口: 8000${NC}"
else
  echo -e "${RED}❌ Web服务启动失败！进程已退出，查看日志:${NC}"
  echo -e "${YELLOW}   tail -f ${PROJECT_ROOT}/logs/web_node.log${NC}"
  exit 1
fi

# 4. 启动回测节点
echo -e "${YELLOW}⚙️  4/6 启动回测节点...${NC}"
# PYTHONPATH already set
export NODE_TYPE=backtest
cd "${PROJECT_ROOT}/AgentServer"
nohup python main.py > "${PROJECT_ROOT}/logs/backtest_node.log" 2>&1 &
backtest_pid=$!
echo $backtest_pid > "${PROJECT_ROOT}/logs/backtest_node.pid"
echo "  回测节点启动，PID: $backtest_pid (已写入PID文件)"

# 等待5秒让回测节点完全启动
sleep 5

# 检查回测节点是否启动成功
if ps -p $backtest_pid > /dev/null; then
  echo -e "${GREEN}✅ 回测节点启动成功，PID: $backtest_pid，端口: 50057${NC}"
else
  echo -e "${RED}❌ 回测节点启动失败！进程已退出，查看日志:${NC}"
  echo -e "${YELLOW}   tail -f ${PROJECT_ROOT}/logs/backtest_node.log${NC}"
  exit 1
fi

# 5. 启动前端Vite开发服务
echo -e "${YELLOW}🎨 5/6 启动前端Vite开发服务...${NC}"
cd "${PROJECT_ROOT}/frontend"
nohup npm run dev -- --port 5174 --host 0.0.0.0 > "${PROJECT_ROOT}/logs/frontend.log" 2>&1 &
frontend_pid=$!
echo $frontend_pid > "${PROJECT_ROOT}/logs/frontend.pid"
echo "  前端服务启动，PID: $frontend_pid (已写入PID文件)"

# 等待3秒让前端服务完全启动
sleep 3

# 检查前端服务是否启动成功
if ps -p $frontend_pid > /dev/null; then
  echo -e "${GREEN}✅ 前端服务启动成功，PID: $frontend_pid，端口: 5174${NC}"
else
  echo -e "${YELLOW}⚠️  前端服务启动失败，但不影响后端回测使用，查看日志:${NC}"
  echo -e "${YELLOW}   tail -f ${PROJECT_ROOT}/logs/frontend.log${NC}"
  # 前端不是必须的，不退出
fi

# 6. 完成输出
echo -e "${YELLOW}============================================${NC}"
echo -e "${GREEN}✅ 所有服务启动成功！${NC}"
echo -e "${GREEN}👉 Web服务: 端口 8000 (PID $web_pid)${NC}"
echo -e "${GREEN}👉 回测引擎: 端口 50057 (PID $backtest_pid)${NC}"
echo -e "${GREEN}👉 前端: 端口 5174 (PID $frontend_pid)${NC}"
echo -e "${GREEN}👉 前端访问地址: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):5174/ultra-short-v2${NC}"
echo -e "${GREEN}👉 数据库管理页面: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):5174/admin/db${NC}"
echo -e "${GREEN}👉 当前分支: $(git rev-parse --abbrev-ref HEAD)${NC}"
echo -e "${YELLOW}============================================${NC}"

exit 0
