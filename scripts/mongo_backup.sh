#!/bin/bash
# MongoDB 每日自动备份脚本
# 备份 stock_agent 数据库的 broker_* 和 scanner_* 关键集合
# 保留最近 14 天

set -e

BACKUP_DIR="/root/.openclaw/backups/mongodb"
DATE=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"

DUMP_DIR="${BACKUP_DIR}/dump_${DATE}"
ARCHIVE_FILE="${BACKUP_DIR}/mongo_stock_agent_${DATE}.tar.gz"

echo "[$(date '+%F %T')] 开始 MongoDB 备份: $DUMP_DIR"

# 备份关键集合
mongodump \
  --uri "mongodb://localhost:27017" \
  --db stock_agent \
  --collection broker_orders \
  --out "$DUMP_DIR" 2>&1 | tail -3

mongodump \
  --uri "mongodb://localhost:27017" \
  --db stock_agent \
  --collection broker_positions \
  --out "$DUMP_DIR" 2>&1 | tail -3

mongodump \
  --uri "mongodb://localhost:27017" \
  --db stock_agent \
  --collection broker_accounts \
  --out "$DUMP_DIR" 2>&1 | tail -3

mongodump \
  --uri "mongodb://localhost:27017" \
  --db stock_agent \
  --collection scanner_timeline \
  --out "$DUMP_DIR" 2>&1 | tail -3

mongodump \
  --uri "mongodb://localhost:27017" \
  --db stock_agent \
  --collection performance_snapshots \
  --out "$DUMP_DIR" 2>&1 | tail -3

mongodump \
  --uri "mongodb://localhost:27017" \
  --db stock_agent \
  --collection scanner_reset_audit_log \
  --out "$DUMP_DIR" 2>&1 | tail -3

# 打包压缩
cd "$BACKUP_DIR"
tar -czf "$ARCHIVE_FILE" "dump_${DATE}"
rm -rf "$DUMP_DIR"

ARCHIVE_SIZE=$(du -h "$ARCHIVE_FILE" | cut -f1)
echo "[$(date '+%F %T')] ✅ 备份完成: $ARCHIVE_FILE ($ARCHIVE_SIZE)"

# 清理 14 天前的旧备份
DELETED=$(find "$BACKUP_DIR" -name "mongo_stock_agent_*.tar.gz" -mtime +${KEEP_DAYS} -print -delete | wc -l)
if [ "$DELETED" -gt 0 ]; then
  echo "[$(date '+%F %T')] 清理 $DELETED 个过期备份 (> ${KEEP_DAYS} 天)"
fi

# 列出当前所有备份
echo "[$(date '+%F %T')] 当前备份列表:"
ls -lah "$BACKUP_DIR"/mongo_stock_agent_*.tar.gz 2>/dev/null | awk '{print "  ", $9, "(" $5 ")"}'
