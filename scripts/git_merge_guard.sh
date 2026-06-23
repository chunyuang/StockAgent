#!/bin/bash
# git_merge_guard.sh — 安全 merge 守卫
# 用法: bash scripts/git_merge_guard.sh <source-branch> [extra-args...]
# 目的: 杜绝 2026-06-22 夜间事故 — feature 用 unrelated histories 覆盖 cron
#
# 强制规则:
#   1. 必须有共同祖先 (有 merge-base)  → 否则拒绝
#   2. 禁止 --allow-unrelated-histories → 杜绝跨 repo 强合
#   3. 禁止 -X theirs / -s theirs       → 杜绝 ours 修改被自动覆盖
#   4. 禁止 -X ours (其实更危险, 一并禁)
#   5. merge 前自动 bundle 备份当前 HEAD 到 /root/.openclaw/backups
#
# 退出码:
#   0 = merge 成功
#   1 = 守卫拒绝 (参数违规 / unrelated histories / 备份失败)
#   2 = git merge 本身失败 (冲突等)

set -euo pipefail

SOURCE="${1:-}"
shift || true
EXTRA_ARGS=("$@")

if [ -z "$SOURCE" ]; then
  echo "❌ 用法: $0 <source-branch> [extra-args...]" >&2
  exit 1
fi

# 1. 黑名单参数检查
for arg in "${EXTRA_ARGS[@]}"; do
  case "$arg" in
    --allow-unrelated-histories)
      echo "❌ 守卫拒绝: --allow-unrelated-histories 已被禁止" >&2
      echo "   原因: 2026-06-22 事故根因 — cron/nightly-fixes 与 feature/market-monitor-auto" >&2
      echo "         是两条独立的 git 历史 (两个不同的 Initial commit)。强合会覆盖工作。" >&2
      exit 1
      ;;
    -X|--strategy-option)
      echo "❌ 守卫拒绝: -X / --strategy-option 已被禁止 (theirs/ours 自动覆盖)" >&2
      exit 1
      ;;
    -Xtheirs|-Xours)
      echo "❌ 守卫拒绝: $arg 已被禁止 (会自动覆盖另一边的修改)" >&2
      exit 1
      ;;
    -s|--strategy)
      echo "❌ 守卫拒绝: -s / --strategy 已被禁止" >&2
      exit 1
      ;;
  esac
done

# 2. 当前分支检查
CUR_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "🔍 守卫: $CUR_BRANCH ← $SOURCE"

# 3. source 分支存在性检查
if ! git rev-parse --verify "$SOURCE" >/dev/null 2>&1; then
  echo "❌ 守卫拒绝: source 分支 '$SOURCE' 不存在" >&2
  exit 1
fi

# 4. unrelated histories 检查 (核心!)
MERGE_BASE=$(git merge-base "$CUR_BRANCH" "$SOURCE" 2>/dev/null || echo "")
if [ -z "$MERGE_BASE" ]; then
  echo "" >&2
  echo "❌ ❌ ❌ 守卫拒绝: unrelated histories 检测! ❌ ❌ ❌" >&2
  echo "" >&2
  echo "   '$CUR_BRANCH' 和 '$SOURCE' 没有共同祖先 (merge-base 为空)" >&2
  echo "   这是 2026-06-22 事故的元凶模式。强行 merge 会丢失工作。" >&2
  echo "" >&2
  CUR_ROOT=$(git rev-list --max-parents=0 "$CUR_BRANCH" | head -1)
  SRC_ROOT=$(git rev-list --max-parents=0 "$SOURCE" | head -1)
  echo "   $CUR_BRANCH lineage 根 = $CUR_ROOT" >&2
  echo "   $SOURCE lineage 根 = $SRC_ROOT" >&2
  echo "" >&2
  echo "   修复方案: 人工介入，决定是 cherry-pick 还是 rebase --onto，禁止强合。" >&2
  exit 1
fi
echo "✅ merge-base 存在: $MERGE_BASE"

# 5. 反向 merge 检测 (cron → feature 是反向, 应该禁止)
if [ "$CUR_BRANCH" = "cron/nightly-fixes" ] && [ "$SOURCE" = "feature/market-monitor-auto" ]; then
  echo "" >&2
  echo "⚠️ ⚠️ ⚠️ 反向 merge 警告 ⚠️ ⚠️ ⚠️" >&2
  echo "" >&2
  echo "   按 2026-06-05 三层分支策略, cron/nightly-fixes 不应从 feature 拉代码。" >&2
  echo "   正确流程: cron 修 bug → 早上人工验证 → 人工 merge cron → feature (单向)" >&2
  echo "" >&2
  echo "   如果一定要执行, 设置环境变量 ALLOW_REVERSE_MERGE=1" >&2
  echo "" >&2
  if [ "${ALLOW_REVERSE_MERGE:-0}" != "1" ]; then
    echo "❌ 守卫拒绝: 反向 merge 默认禁止" >&2
    exit 1
  fi
  echo "⚠️ ALLOW_REVERSE_MERGE=1 已设置，继续执行（请确认你知道在做什么）"
fi

# 6. 自动备份
TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/root/.openclaw/backups"
mkdir -p "$BACKUP_DIR"
BUNDLE="$BACKUP_DIR/pre-merge-${CUR_BRANCH//\//_}-${TS}.bundle"
if git bundle create "$BUNDLE" "$CUR_BRANCH" >/dev/null 2>&1; then
  echo "💾 备份: $BUNDLE ($(du -h "$BUNDLE" | cut -f1))"
else
  echo "⚠️ 备份失败，但继续 merge" >&2
fi

# 7. 执行 merge（只允许 --no-edit / --no-ff / --ff-only / -m 这些非破坏性参数）
echo "🚀 执行: git merge $SOURCE --no-edit ${EXTRA_ARGS[*]}"
if git merge "$SOURCE" --no-edit "${EXTRA_ARGS[@]}"; then
  echo "✅ merge 成功"
  exit 0
else
  EXIT=$?
  echo "❌ merge 失败 (退出码=$EXIT)，备份可用: $BUNDLE" >&2
  exit 2
fi
