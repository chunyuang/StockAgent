#!/usr/bin/env bash
# Create a fast recovery anchor before risky automation/nightly audits.
# Safe by design: writes only backup files under ~/.openclaw/backups; does not modify app code, cron, MongoDB, or services.
set -euo pipefail

REPO=${REPO:-/root/.openclaw/workspace/StockAgent}
BACKUP_ROOT=${BACKUP_ROOT:-/root/.openclaw/backups/recovery-anchors}
DB_NAME=${DB_NAME:-stock_agent}
LABEL=${1:-nightly-precheck}
TS=${ANCHOR_TS:-$(date +%Y%m%d-%H%M%S)}
ANCHOR="$BACKUP_ROOT/${TS}-${LABEL}"

mkdir -p "$ANCHOR"/{git,cron,mongo,service,docs}

if [ ! -d "$REPO/.git" ]; then
  echo "ERROR: repo not found: $REPO" >&2
  exit 2
fi

cd "$REPO"

# 1) Git/code anchor
{
  echo "repo=$REPO"
  echo "branch=$(git branch --show-current)"
  echo "head=$(git rev-parse HEAD)"
  echo "head_short=$(git rev-parse --short HEAD)"
  echo "upstream=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)"
  echo "created_at=$(date -Is)"
  echo "label=$LABEL"
  echo
  echo "## git status --short"
  git status --short
  echo
  echo "## recent commits"
  git log --oneline -30
} > "$ANCHOR/git/git-state.txt"

git status --porcelain=v1 > "$ANCHOR/git/worktree-status.txt"
git diff > "$ANCHOR/git/worktree.diff" || true
git diff --staged > "$ANCHOR/git/staged.diff" || true
if ! git bundle create "$ANCHOR/git/StockAgent-$(git rev-parse --short HEAD).bundle" --all >/dev/null 2>&1; then
  echo "git bundle failed" > "$ANCHOR/git/BUNDLE_FAILED.txt"
fi

# 2) Cron anchor
if [ -f /root/.openclaw/cron/jobs.json ]; then
  cp /root/.openclaw/cron/jobs.json "$ANCHOR/cron/jobs.json"
  python3 - <<'PY' > "$ANCHOR/cron/enabled-jobs.txt"
import json
p='/root/.openclaw/cron/jobs.json'
with open(p) as f:
    data=json.load(f)
jobs=data.get('jobs', data)
for j in sorted([x for x in jobs if x.get('enabled')], key=lambda x:(x.get('schedule',{}).get('expr',''), x.get('name',''))):
    print((j.get('id') or '')[:8], j.get('schedule',{}).get('expr',''), j.get('name'), '|', j.get('description','')[:160].replace('\n',' '))
PY
else
  echo "cron jobs.json not found" > "$ANCHOR/cron/CRON_NOT_FOUND.txt"
fi

# 3) Mongo read-only snapshot and selected critical dumps
python3 - <<'PY' > "$ANCHOR/mongo/mongo-snapshot.txt" || true
from pymongo import MongoClient
c=MongoClient('localhost',27017,serverSelectionTimeoutMS=3000)
db=c['stock_agent']
cols=['broker_orders','broker_positions','broker_accounts','broker_account','scanner_timeline','audit_log','strategy_config','performance_snapshots','sim_accounts','stock_daily_ak_full','daily_basic','limit_list','sentiment_scores','scan_traces']
for name in cols:
    coll=db[name]
    try:
        total=coll.estimated_document_count()
        latest=None; latest_count=0
        doc=coll.find_one({'trade_date': {'$exists': True}}, sort=[('trade_date',-1)])
        if doc:
            latest=doc.get('trade_date')
            latest_count=coll.count_documents({'trade_date': latest})
        print(f'{name}: total={total}, latest_trade_date={latest}, latest_count={latest_count}')
    except Exception as e:
        print(f'{name}: ERROR {e}')
PY

if command -v mongodump >/dev/null 2>&1; then
  for coll in broker_orders broker_positions broker_accounts broker_account scanner_timeline audit_log strategy_config performance_snapshots sim_accounts; do
    mongodump --db "$DB_NAME" --collection "$coll" --out "$ANCHOR/mongo/dump" >/dev/null 2>&1 || true
  done
else
  echo "mongodump not found; snapshot counts only" > "$ANCHOR/mongo/MONGODUMP_NOT_FOUND.txt"
fi

# 4) Service state anchor (read-only)
{
  echo "created_at=$(date -Is)"
  echo "label=$LABEL"
  echo
  echo "## processes"
  pgrep -af 'python.*main.py|redis|mongod|vite|node' || true
  echo
  echo "## ports"
  ss -ltnp 2>/dev/null | grep -E ':8000|:5174|:50051|:27017|:6379' || true
  echo
  echo "## scanner status"
  curl -sS -m 5 http://localhost:8000/api/v1/scanner/status || true
  echo
  echo "## premarket status"
  curl -sS -m 5 http://localhost:8000/api/v1/scanner/premarket-status || true
} > "$ANCHOR/service/service-state.txt"

# 5) Restore guide
cat > "$ANCHOR/README.md" <<EOF
# StockAgent Recovery Anchor

Created: $(date -Is)
Label: $LABEL
Anchor: $ANCHOR
Repo: $REPO

## Captured
- Code: branch/head/status/diff + full git bundle
- Cron: exact jobs.json + enabled job list
- Mongo: key collection counts/latest dates + selected trading-critical mongodump when available
- Service: process/port/API snapshots

## Fast recovery order
1. Stop risky automation first; restore or disable cron before further changes.
2. Restore code to recorded branch/head or from git bundle.
3. Restore only confirmed-damaged Mongo collections; do not blanket restore the whole DB.
4. Restart services only after code + cron + data decision is clear.

## Useful commands
- Inspect code anchor: cat git/git-state.txt
- Inspect cron anchor: cat cron/enabled-jobs.txt
- Inspect data anchor: cat mongo/mongo-snapshot.txt
- Restore code from repo: git checkout <branch> && git reset --hard <head>
- Restore from bundle: git clone git/StockAgent-*.bundle StockAgent-restored
EOF

ln -sfn "$ANCHOR" "$BACKUP_ROOT/latest"
printf '%s\n' "$ANCHOR"
