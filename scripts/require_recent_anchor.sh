#!/usr/bin/env bash
# Require a fresh recovery anchor before risky automation.
# Read-only: checks backup files only; does not modify code, cron, MongoDB, or services.
set -euo pipefail

BACKUP_ROOT=${BACKUP_ROOT:-/root/.openclaw/backups/recovery-anchors}
MAX_AGE_MIN=${MAX_AGE_MIN:-120}
MODE=${1:-standard}   # standard | trading | nightly
LATEST="$BACKUP_ROOT/latest"

if [ ! -L "$LATEST" ] && [ ! -d "$LATEST" ]; then
  echo "❌ recovery anchor missing: $LATEST" >&2
  exit 20
fi

ANCHOR=$(readlink -f "$LATEST" 2>/dev/null || true)
if [ -z "$ANCHOR" ] || [ ! -d "$ANCHOR" ]; then
  echo "❌ recovery anchor latest target invalid: $LATEST" >&2
  exit 21
fi

# Freshness check by directory mtime; create_recovery_anchor.sh writes files under the dir.
now=$(date +%s)
mtime=$(stat -c %Y "$ANCHOR")
age_min=$(( (now - mtime) / 60 ))
if [ "$age_min" -gt "$MAX_AGE_MIN" ]; then
  echo "❌ recovery anchor too old: ${age_min}min > ${MAX_AGE_MIN}min ($ANCHOR)" >&2
  exit 22
fi

require_file() {
  local path="$1"
  if [ ! -s "$path" ]; then
    echo "❌ required anchor file missing/empty: $path" >&2
    exit 23
  fi
}

require_file "$ANCHOR/README.md"
require_file "$ANCHOR/git/git-state.txt"
require_file "$ANCHOR/cron/jobs.json"
require_file "$ANCHOR/cron/enabled-jobs.txt"
require_file "$ANCHOR/mongo/mongo-snapshot.txt"
require_file "$ANCHOR/service/service-state.txt"

if [ "$MODE" = "trading" ] || [ "$MODE" = "nightly" ]; then
  for coll in broker_orders broker_positions scanner_timeline broker_accounts sim_accounts; do
    if ! find "$ANCHOR/mongo/dump" -type f -name "${coll}.bson" -size +0c 2>/dev/null | grep -q .; then
      echo "❌ trading anchor missing collection dump: $coll" >&2
      exit 24
    fi
  done
fi

if [ "$MODE" = "nightly" ]; then
  # Large table incremental anchors are required before nightly audit/review work.
  for name in stock_daily_ak_full daily_basic limit_list sentiment_scores scan_traces; do
    if ! find "$ANCHOR/mongo/incremental" -type f -name "${name}_*.jsonl.gz" -size +0c 2>/dev/null | grep -q .; then
      echo "❌ nightly anchor missing incremental data backup for: $name" >&2
      exit 25
    fi
  done
fi

echo "✅ recovery anchor ok: mode=$MODE age=${age_min}min path=$ANCHOR"
