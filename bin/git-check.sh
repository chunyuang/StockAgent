#!/bin/bash
# =============================================
# 📝 快速检查Git状态 - 防止忘记提交代码
# 用法：./bin/git-check.sh  或者  git-check（加了alias的话）
# =============================================

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

GIT_STATUS=$(git status --porcelain)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
CURRENT_COMMIT=$(git rev-parse --short HEAD)

if [[ -n "$GIT_STATUS" ]]; then
  COUNT=$(echo "$GIT_STATUS" | wc -l | xargs)
  echo -e "${RED}============================================${NC}"
  echo -e "${RED}⚠️  有 $COUNT 个文件未提交！${NC}"
  echo -e "${RED}============================================${NC}"
  echo -e "${YELLOW}当前分支: $CURRENT_BRANCH (commit: $CURRENT_COMMIT)${NC}"
  echo ""
  echo "$GIT_STATUS"
  echo ""
  echo -e "${YELLOW}建议操作:${NC}"
  echo "  git status      # 查看详情"
  echo "  git diff        # 查看修改内容"
  echo "  git add xxx     # 添加文件"
  echo "  git commit -m 'xxx'  # 提交"
  exit 1
else
  echo -e "${GREEN}✅ Git工作区干净，当前分支: $CURRENT_BRANCH (commit: $CURRENT_COMMIT)${NC}"
  exit 0
fi
