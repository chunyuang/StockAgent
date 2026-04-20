#!/usr/bin/env python3
"""
自动记录变更到 CHANGELOG.md
用法:
python bin/log-change.py create raw 20251215-20260318-akshare "初始版本"
python bin/log-change.py update raw 20251215-20260318-akshare "增量更新到 2026-03-20"
python bin/log-change.py delete raw 20251215-20260318-akshare "过期，已归档"
"""

import argparse
from datetime import datetime
import os

def log_change(action, category, name, note):
    """记录变更"""
    changelog_path = '/root/.openclaw/workspace/local-databases/CHANGELOG.md'
    
    # 读取现有
    if os.path.exists(changelog_path):
        with open(changelog_path, 'r') as f:
            content = f.read()
    else:
        content = """# 项目6 操作日志 - 本地数据库管理

记录所有对数据库结构/数据的修改操作，方便追溯变更。

---

## 格式

每条日志格式：
```
- YYYY-MM-DD HH:MM GMT+8 | 操作人 | 操作类型 | 操作对象 | 说明
```

---

## 日志\n"""
    
    # 当前时间
    now = datetime.now().strftime('%Y-%m-%d %H:%M GMT+8')
    user = '@ou_2344df66cfbc48add043acab9784520'
    
    action_cn = {
        'create': '新增',
        'update': '更新',
        'delete': '删除',
        'archive': '归档',
    }
    
    action_name = action_cn.get(action, action)
    full_obj = f'{category}/{name}'
    
    new_line = f"- **{now}** | {user} | {action_name} | {full_obj} | {note}"
    
    # 添加到开头（最新在前面）
    if '## 日志' in content:
        before, after = content.split('## 日志', 1)
        content = before + '## 日志\n\n' + new_line + '\n' + after
    else:
        content += '\n' + new_line + '\n'
    
    with open(changelog_path, 'w') as f:
        f.write(content)
    
    print(f"✅ CHANGELOG updated: {action} {full_obj} - {note}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Log change to CHANGELOG.md')
    parser.add_argument('action', choices=['create', 'update', 'delete', 'archive'], help='Action type')
    parser.add_argument('category', choices=['raw', 'factors', 'backtests'], help='Category (raw/factors/backtests)')
    parser.add_argument('name', help='Database name')
    parser.add_argument('note', help='Description note', nargs='?', default='')
    args = parser.parse_args()
    
    log_change(args.action, args.category, args.name, args.note)
