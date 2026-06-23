#!/bin/bash
# nightly_git_backup.sh — 每晚 23:00 自动备份 StockAgent repo
# 目的: 防止 2026-06-22 类工作丢失事故,任何时候都能从 bundle 恢复
#
# 备份产物 (统一存放 /root/.openclaw/backups/):
#   1. StockAgent-full-YYYYMMDD-HHMMSS.bundle      全分支历史 (含所有 ref)
#   2. cron-nightly-fixes-YYYYMMDD-HHMMSS.bundle   单独导出 cron 分支 (用于快速 cherry-pick)
#   3. backups.log                                  执行日志
#
# 保留策略:
#   - 最近 14 天: 全保留
#   - 14~30 天: 每 3 天保留一份
#   - 30 天以上: 删除

set -euo pipefail

REPO="/root/.openclaw/workspace/StockAgent"
BACKUP_DIR="/root/.openclaw/backups"
LOG="$BACKUP_DIR/backups.log"
TS=$(date +%Y%m%d-%H%M%S)
DATE=$(date '+%Y-%m-%d %H:%M:%S')

mkdir -p "$BACKUP_DIR"

log() {
  echo "[$DATE] $*" | tee -a "$LOG"
}

cd "$REPO" || { log "❌ repo 不存在: $REPO"; exit 1; }

log "===== 开始备份 ====="
log "HEAD: $(git rev-parse --abbrev-ref HEAD) @ $(git rev-parse --short HEAD)"

# 1. 全分支 bundle
FULL_BUNDLE="$BACKUP_DIR/StockAgent-full-${TS}.bundle"
if git bundle create "$FULL_BUNDLE" --all >>"$LOG" 2>&1; then
  SIZE=$(du -h "$FULL_BUNDLE" | cut -f1)
  log "✅ 全分支 bundle: $FULL_BUNDLE ($SIZE)"
else
  log "❌ 全分支 bundle 失败"
  exit 2
fi

# 2. cron/nightly-fixes 单独 bundle (快速恢复用)
CRON_BUNDLE="$BACKUP_DIR/cron-nightly-fixes-${TS}.bundle"
if git rev-parse --verify cron/nightly-fixes >/dev/null 2>&1; then
  git bundle create "$CRON_BUNDLE" cron/nightly-fixes >>"$LOG" 2>&1 && log "✅ cron 分支 bundle: $CRON_BUNDLE"
fi

# 3. 验证 bundle 可读
if git bundle verify "$FULL_BUNDLE" >/dev/null 2>&1; then
  log "✅ bundle 完整性验证通过"
else
  log "⚠️ bundle verify 失败"
fi

# 4. 清理过期备份
NOW=$(date +%s)
DAY=86400
DELETED=0
KEPT=0

for f in "$BACKUP_DIR"/StockAgent-full-*.bundle "$BACKUP_DIR"/cron-nightly-fixes-*.bundle; do
  [ -f "$f" ] || continue
  MTIME=$(stat -c %Y "$f")
  AGE=$(( (NOW - MTIME) / DAY ))
  KEEP=1
  if [ $AGE -gt 30 ]; then
    KEEP=0
  elif [ $AGE -gt 14 ]; then
    # 14-30 天: 每 3 天保留一份 (按日期数字判断)
    DAYNUM=$(date -d "@$MTIME" +%j)
    [ $((DAYNUM % 3)) -ne 0 ] && KEEP=0
  fi

  if [ $KEEP -eq 0 ]; then
    rm -f "$f"
    DELETED=$((DELETED + 1))
  else
    KEPT=$((KEPT + 1))
  fi
done

log "🧹 清理: 删除 $DELETED 个, 保留 $KEPT 个"

# 5. 统计当前 backup 大小
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
log "📊 备份目录总大小: $TOTAL_SIZE"

# 6. 输出最近 5 个备份
log "📋 最近备份:"
ls -lh "$BACKUP_DIR"/StockAgent-full-*.bundle 2>/dev/null | tail -5 | awk '{print "    "$NF" "$5}' | tee -a "$LOG"

log "===== 备份完成 ====="
log ""
