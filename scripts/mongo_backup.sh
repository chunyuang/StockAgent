#!/bin/bash
# MongoDB 每日自动备份（轻量版）
# 关键集合: broker_orders / broker_positions / broker_accounts /
#           scanner_timeline / performance_snapshots / scanner_reset_audit_log
# 保留 7 天，自动清理；磁盘紧张时跳过

set -e

BACKUP_DIR="/root/.openclaw/backups/mongodb"
KEEP_DAYS=7
MIN_FREE_GB=3   # 剩余<3GB跳过备份
MAX_TOTAL_MB=200  # mongodb 备份目录最大 200MB（防止占满）

DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

# ===== 磁盘保护 =====
FREE_KB=$(df / --output=avail | tail -1)
FREE_GB=$((FREE_KB / 1024 / 1024))
if [ "$FREE_GB" -lt "$MIN_FREE_GB" ]; then
  echo "[$(date '+%F %T')] ⚠️ 磁盘剩余 ${FREE_GB}GB < ${MIN_FREE_GB}GB, 跳过备份"
  exit 0
fi

CURRENT_MB=$(du -sm "$BACKUP_DIR" 2>/dev/null | cut -f1)
if [ "${CURRENT_MB:-0}" -gt "$MAX_TOTAL_MB" ]; then
  echo "[$(date '+%F %T')] ⚠️ 备份目录已 ${CURRENT_MB}MB > ${MAX_TOTAL_MB}MB, 强制清理"
  find "$BACKUP_DIR" -name "mongo_*.gz" -mtime +3 -delete
fi

ARCHIVE_FILE="${BACKUP_DIR}/mongo_${DATE}.gz"

# ===== mongodump 直接输出到压缩归档 (--archive --gzip 比 tar.gz 小 30%) =====
mongodump \
  --uri "mongodb://localhost:27017" \
  --db stock_agent \
  --collection broker_orders \
  --archive="${BACKUP_DIR}/.tmp_orders_${DATE}" \
  --gzip --quiet

mongodump \
  --uri "mongodb://localhost:27017" \
  --db stock_agent \
  --collection broker_positions \
  --archive="${BACKUP_DIR}/.tmp_positions_${DATE}" \
  --gzip --quiet

mongodump \
  --uri "mongodb://localhost:27017" \
  --db stock_agent \
  --collection broker_accounts \
  --archive="${BACKUP_DIR}/.tmp_accounts_${DATE}" \
  --gzip --quiet

mongodump \
  --uri "mongodb://localhost:27017" \
  --db stock_agent \
  --collection scanner_timeline \
  --archive="${BACKUP_DIR}/.tmp_timeline_${DATE}" \
  --gzip --quiet

mongodump \
  --uri "mongodb://localhost:27017" \
  --db stock_agent \
  --collection performance_snapshots \
  --archive="${BACKUP_DIR}/.tmp_perf_${DATE}" \
  --gzip --quiet 2>/dev/null || true

mongodump \
  --uri "mongodb://localhost:27017" \
  --db stock_agent \
  --collection scanner_reset_audit_log \
  --archive="${BACKUP_DIR}/.tmp_audit_${DATE}" \
  --gzip --quiet 2>/dev/null || true

# 合并所有归档到一个 tar
tar -cf "$ARCHIVE_FILE" -C "$BACKUP_DIR" \
  ".tmp_orders_${DATE}" \
  ".tmp_positions_${DATE}" \
  ".tmp_accounts_${DATE}" \
  ".tmp_timeline_${DATE}" \
  $([ -f "${BACKUP_DIR}/.tmp_perf_${DATE}" ] && echo ".tmp_perf_${DATE}") \
  $([ -f "${BACKUP_DIR}/.tmp_audit_${DATE}" ] && echo ".tmp_audit_${DATE}") \
  2>/dev/null

# 清理临时归档
rm -f "${BACKUP_DIR}/.tmp_"*"_${DATE}"

SIZE=$(du -h "$ARCHIVE_FILE" | cut -f1)
echo "[$(date '+%F %T')] ✅ 备份完成: $(basename $ARCHIVE_FILE) ($SIZE)"

# ===== 清理过期备份 =====
DELETED=$(find "$BACKUP_DIR" -name "mongo_*.gz" -mtime +${KEEP_DAYS} -print -delete | wc -l)
[ "$DELETED" -gt 0 ] && echo "[$(date '+%F %T')] 清理 $DELETED 个过期备份 (>${KEEP_DAYS}天)"

# ===== 当前状态 =====
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
COUNT=$(ls "$BACKUP_DIR"/mongo_*.gz 2>/dev/null | wc -l)
echo "[$(date '+%F %T')] 备份目录: ${COUNT} 个文件, 共 ${TOTAL_SIZE}, 磁盘剩余 ${FREE_GB}GB"
