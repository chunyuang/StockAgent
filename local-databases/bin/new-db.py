#!/usr/bin/env python3
"""
自动化创建新数据库完整流程
usage:
python bin/new-db.py --type raw --name 数据库名称 --desc "描述"
python bin/new-db.py --type factors --name 因子名称 --raw 依赖原始 --desc "描述"
python bin/new-db.py --type backtests --name 回测名称 --raw 依赖原始 --factors 依赖因子 --desc "描述"
"""

import argparse
import os
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description='Automatically create new database')
    parser.add_argument('--type', choices=['raw', 'factors', 'backtests'], required=True, help='Database type')
    parser.add_argument('--name', required=True, help='Database name')
    parser.add_argument('--desc', default='', help='Description')
    parser.add_argument('--raw', help='Dependency raw database name (for factors/backtests)')
    parser.add_argument('--factors', help='Dependency factors name (for backtests)')
    args = parser.parse_args()
    
    # Create metadata from template
    template_path = {
        'raw': '/root/.openclaw/workspace/local-databases/raw/metadata/.template.md',
        'factors': '/root/.openclaw/workspace/local-databases/factors/metadata/.template.md',
        'backtests': '/root/.openclaw/workspace/local-databases/backtests/metadata/.template.md',
    }
    
    if not os.path.exists(template_path[args.type]):
        print(f"❌ Template not found: {template_path[args.type]}")
        return False
    
    with open(template_path[args.type], 'r') as f:
        template = f.read()
    
    # Fill template
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    
    result = template
    result = result.replace('{{name}}', args.name)
    result = result.replace('{{version}}', 'v1')
    result = result.replace('{{created}}', today)
    result = result.replace('{{desc}}', args.desc)
    result = result.replace('{{raw_dep}}', args.raw if args.raw else '')
    result = result.replace('{{factors_dep}}', args.factors if args.factors else '')
    
    # Save metadata
    metadata_path = f'/root/.openclaw/workspace/local-databases/{args.type}/metadata/{args.name}.md'
    if os.path.exists(metadata_path):
        print(f"⚠️  Metadata already exists: {metadata_path}")
        overwrite = input("Overwrite? (y/N) ").lower().strip()
        if overwrite != 'y':
            print("Aborted")
            return False
    
    with open(metadata_path, 'w') as f:
        f.write(result)
    
    print(f"✅ Created metadata: {metadata_path}")
    
    # Log change
    import subprocess
    action = 'create'
    desc = args.desc if args.desc else f"New {args.type} database"
    cmd = [
        'python3', '/root/.openclaw/workspace/local-databases/bin/log-change.py',
        action, args.type, args.name, desc
    ]
    subprocess.run(cmd)
    
    # Regenerate stats json
    cmd = [
        'python3', '/root/.openclaw/workspace/local-databases/bin/generate-stats.py',
    ]
    subprocess.run(cmd)
    print("✅ Regenerated stats.json")
    
    # Regenerate README
    cmd = [
        'python3', '/root/.openclaw/workspace/local-databases/bin/regenerate-index.py',
    ]
    subprocess.run(cmd)
    print("✅ Regenerated README dashboard")
    
    print("\n🎉 Done! Next step:")
    if args.type == 'raw':
        print("  1. Import your data into MongoDB stock_daily_ak_full")
        print(f"  2. Run data validation: python local-databases/bin/validate-data.py --type raw --name {args.name}")
        print(f"  3. Backup (optional): python local-databases/bin/backup-db.py backup --category raw --name {args.name}")
    elif args.type == 'factors':
        print("  1. Calculate your factors and import into MongoDB strategy_signals")
        print(f"  2. Run data validation: python local-databases/bin/validate-data.py --type factors --name {args.name}")
        print(f"  3. Backup (optional): python local-databases/bin/backup-db.py backup --category factors --name {args.name}")
    elif args.type == 'backtests':
        print("  1. Run your backtest and save results")
        print(f"  2. Backup (optional): python local-databases/bin/backup-db.py backup --category backtests --name {args.name}")
    
    return True

if __name__ == '__main__':
    main()
