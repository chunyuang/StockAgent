#!/bin/bash
# cron_issues.sh - 跨 cron 任务共享的 issue 队列管理工具
# 用法:
#   ./cron_issues.sh add <severity> <discovered_by> "<title>" "<detail>" "<evidence>" "<suggested_fix>"
#   ./cron_issues.sh list [open|resolved|all]
#   ./cron_issues.sh list_open_for_fix    # 夜间 cron 专用,只列 open 状态
#   ./cron_issues.sh resolve <issue_id> <resolved_by> [commit_sha]
#   ./cron_issues.sh wontfix <issue_id> <resolved_by> "<reason>"
#   ./cron_issues.sh stats                # 统计待修/已修/积压

QUEUE_FILE="/root/.openclaw/workspace/StockAgent/cron_issues.jsonl"

# 初始化文件
[ ! -f "$QUEUE_FILE" ] && touch "$QUEUE_FILE"

ACTION="$1"
shift

case "$ACTION" in
  add)
    SEVERITY="$1"
    DISCOVERED_BY="$2"
    TITLE="$3"
    DETAIL="$4"
    EVIDENCE="$5"
    SUGGESTED_FIX="$6"
    ID=$(date +%s%N | md5sum | cut -c1-12)
    NOW=$(date -Iseconds)
    python3 -c "
import json
issue = {
    'id': '$ID',
    'discovered_at': '$NOW',
    'discovered_by': '''$DISCOVERED_BY''',
    'severity': '$SEVERITY',
    'title': '''$TITLE''',
    'detail': '''$DETAIL''',
    'evidence': '''$EVIDENCE''',
    'suggested_fix': '''$SUGGESTED_FIX''',
    'status': 'open',
    'resolved_at': None,
    'resolved_by': None,
    'commit_sha': None
}
with open('$QUEUE_FILE', 'a') as f:
    f.write(json.dumps(issue, ensure_ascii=False) + '\n')
print(f'✅ Issue 已记录: $ID ($SEVERITY) $TITLE')
"
    ;;
  list)
    FILTER="${1:-open}"
    python3 << PYEOF
import json
issues = []
with open('$QUEUE_FILE') as f:
    for line in f:
        line = line.strip()
        if line:
            try: issues.append(json.loads(line))
            except: pass
if '$FILTER' != 'all':
    issues = [i for i in issues if i.get('status') == '$FILTER']
print(f'=== {len(issues)} 个 issue (filter=$FILTER) ===')
for i in sorted(issues, key=lambda x: x.get('discovered_at', ''), reverse=True):
    print(f"[{i['severity']}] {i['id'][:8]} {i.get('title', '?')[:80]}")
    print(f"  发现: {i.get('discovered_at')} by {i.get('discovered_by')}")
    print(f"  状态: {i.get('status')}", end='')
    if i.get('resolved_by'): print(f" by {i['resolved_by']}", end='')
    if i.get('commit_sha'): print(f" ({i['commit_sha'][:7]})", end='')
    print()
PYEOF
    ;;
  list_open_for_fix)
    # 夜间 cron 专用: 输出待修 issue 的结构化清单(按严重度排序)
    python3 << PYEOF
import json
issues = []
with open('$QUEUE_FILE') as f:
    for line in f:
        line = line.strip()
        if line:
            try: issues.append(json.loads(line))
            except: pass
open_issues = [i for i in issues if i.get('status') == 'open']
if not open_issues:
    print('✅ 待修队列为空')
else:
    severity_order = {'P0': 0, 'P1': 1, 'P2': 2}
    open_issues.sort(key=lambda x: (severity_order.get(x.get('severity', 'P2'), 9), x.get('discovered_at', '')))
    print(f'## 待修 issue 清单 ({len(open_issues)} 个,按严重度排序)')
    print()
    for i in open_issues:
        print(f"### [{i['severity']}] {i['title']}")
        print(f"- **ID**: {i['id']}")
        print(f"- **发现于**: {i['discovered_at']} by {i['discovered_by']}")
        print(f"- **详情**: {i['detail']}")
        if i.get('evidence'):
            print(f"- **证据**: {i['evidence']}")
        if i.get('suggested_fix'):
            print(f"- **建议修复**: {i['suggested_fix']}")
        print(f"- **修完命令**: \`./cron_issues.sh resolve {i['id']} <your_cron_name> <commit_sha>\`")
        print()
PYEOF
    ;;
  resolve)
    ID="$1"
    RESOLVED_BY="$2"
    COMMIT_SHA="${3:-}"
    python3 << PYEOF
import json
issues = []
with open('$QUEUE_FILE') as f:
    for line in f:
        line = line.strip()
        if line:
            try: issues.append(json.loads(line))
            except: pass
found = False
for i in issues:
    if i.get('id') == '$ID':
        i['status'] = 'resolved'
        i['resolved_at'] = '$(date -Iseconds)'
        i['resolved_by'] = '$RESOLVED_BY'
        i['commit_sha'] = '$COMMIT_SHA' if '$COMMIT_SHA' else None
        found = True
        break
if found:
    with open('$QUEUE_FILE', 'w') as f:
        for i in issues:
            f.write(json.dumps(i, ensure_ascii=False) + '\n')
    print(f'✅ Issue $ID 已标记 resolved')
else:
    print(f'❌ Issue $ID 不存在')
PYEOF
    ;;
  wontfix)
    ID="$1"
    RESOLVED_BY="$2"
    REASON="$3"
    python3 << PYEOF
import json
issues = []
with open('$QUEUE_FILE') as f:
    for line in f:
        line = line.strip()
        if line:
            try: issues.append(json.loads(line))
            except: pass
for i in issues:
    if i.get('id') == '$ID':
        i['status'] = 'wontfix'
        i['resolved_at'] = '$(date -Iseconds)'
        i['resolved_by'] = '$RESOLVED_BY'
        i['wontfix_reason'] = '''$REASON'''
        break
with open('$QUEUE_FILE', 'w') as f:
    for i in issues:
        f.write(json.dumps(i, ensure_ascii=False) + '\n')
print(f'✅ Issue $ID 已标记 wontfix')
PYEOF
    ;;
  stats)
    python3 << PYEOF
import json
from collections import Counter
issues = []
with open('$QUEUE_FILE') as f:
    for line in f:
        line = line.strip()
        if line:
            try: issues.append(json.loads(line))
            except: pass
status_cnt = Counter(i.get('status', 'unknown') for i in issues)
severity_cnt = Counter(i.get('severity', 'unknown') for i in issues if i.get('status') == 'open')
by_source = Counter(i.get('discovered_by', 'unknown') for i in issues if i.get('status') == 'open')
print(f'=== Cron Issue 队列统计 ===')
print(f'总 issue 数: {len(issues)}')
print(f'按状态: {dict(status_cnt)}')
print(f'待修按严重度: {dict(severity_cnt)}')
print(f'待修来源 top: {dict(by_source.most_common(5))}')
# 积压告警
open_cnt = status_cnt.get('open', 0)
p0_cnt = severity_cnt.get('P0', 0)
if p0_cnt > 0:
    print(f'⚠️ P0 积压 {p0_cnt} 个,夜间必须优先修!')
if open_cnt > 20:
    print(f'⚠️ 总积压 {open_cnt} 个,夜间审查压力大')
PYEOF
    ;;
  *)
    echo "用法:"
    echo "  $0 add <severity:P0|P1|P2> <discovered_by> '<title>' '<detail>' '<evidence>' '<suggested_fix>'"
    echo "  $0 list [open|resolved|wontfix|all]"
    echo "  $0 list_open_for_fix     # 夜间 cron 用,输出 markdown 清单"
    echo "  $0 resolve <issue_id> <resolved_by> [commit_sha]"
    echo "  $0 wontfix <issue_id> <resolved_by> '<reason>'"
    echo "  $0 stats"
    exit 1
    ;;
esac
