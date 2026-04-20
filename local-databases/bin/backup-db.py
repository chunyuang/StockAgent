#!/usr/bin/env python3
"""
自动备份 MongoDB 集合到压缩文件
备份原始数据/因子数据到 local-databases/{category}/data/ 目录
"""

import argparse
import os
import subprocess
from datetime import datetime

def backup_collection(category, name, db_name='stock_agent', collection_name=None):
    """
    备份 MongoDB 集合到 json 压缩文件
    category: raw/factors/backtests
    name: 数据库名称
    collection_name: MongoDB 集合名称，如果 None，原始数据 → stock_daily_ak_full，因子 → strategy_signals
    """
    if collection_name is None:
        if category == 'raw':
            collection_name = 'stock_daily_ak_full'
        elif category == 'factors':
            collection_name = 'strategy_signals'
        elif category == 'backtests':
            collection_name = 'backtest_results'
    
    output_dir = f'/root/.openclaw/workspace/local-databases/{category}/data/{name}'
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    output_file = f'{output_dir}/{name}-{timestamp}.json'
    archive_file = f'{output_dir}/{name}-{timestamp}.tar.gz'
    
    # 使用 mongoexport 导出
    cmd = f'mongoexport --db {db_name} --collection {collection_name} --out {output_file}'
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print("❌ mongoexport failed")
        return False
    
    # 压缩
    cmd = f'tar -czf {archive_file} -C {output_dir} {name}-{timestamp}.json'
    print(f"Compressing: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print("❌ compression failed")
        return False
    
    # 删除原始 json
    os.remove(output_file)
    
    print(f"✅ Backup completed: {archive_file}")
    print(f"   File size: {os.path.getsize(archive_file) / (1024*1024):.2f} MB")
    
    # 记录到 CHANGELOG
    now = datetime.now().strftime('%Y-%m-%d %H:%M GMT+8')
    user = '@ou_2344df66cfbc48add043acab9784520'
    changelog_path = '/root/.openclaw/workspace/local-databases/CHANGELOG.md'
    
    with open(changelog_path, 'r') as f:
        content = f.read()
    
    new_line = f"- **{now}** | {user} | 备份 | {category}/{name} | 备份 MongoDB {collection_name} → {archive_file}"
    
    if '## 日志' in content:
        before, after = content.split('## 日志', 1)
        content = before + '## 日志\n\n' + new_line + '\n' + after
    
    with open(changelog_path, 'w') as f:
        f.write(content)
    
    return True

def restore_backup(archive_file, db_name='stock_agent', collection_name=None):
    """从备份恢复
    archive_file: path to .tar.gz
    """
    # 解压
    tmp_dir = '/tmp/local-db-restore'
    os.makedirs(tmp_dir, exist_ok=True)
    cmd = f'tar -xzf {archive_file} -C {tmp_dir}'
    print(f"Extracting: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print("❌ extract failed")
        return False
    
    # 找到 json 文件
    json_file = None
    for f in os.listdir(tmp_dir):
        if f.endswith('.json'):
            json_file = os.path.join(tmp_dir, f)
            break
    
    if json_file is None:
        print("❌ No json file found in archive")
        return False
    
    # 导入
    if collection_name is None:
        # 从文件名猜
        if 'raw' in archive_file:
            collection_name = 'stock_daily_ak_full'
        elif 'factors' in archive_file:
            collection_name = 'strategy_signals'
        else:
            collection_name = 'backtest_results'
    
    cmd = f'mongoimport --db {db_name} --collection {collection_name} --file {json_file}'
    print(f"Importing: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print("❌ import failed")
        return False
    
    print(f"✅ Restore completed to {db_name}.{collection_name}")
    return True

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backup MongoDB collection to compressed file')
    parser.add_argument('action', choices=['backup', 'restore'], help='Action')
    parser.add_argument('--category', choices=['raw', 'factors', 'backtests'], help='Category')
    parser.add_argument('--name', help='Database name')
    parser.add_argument('--collection', help='MongoDB collection name (optional)')
    parser.add_argument('--archive', help='Archive file for restore')
    args = parser.parse_args()
    
    if args.action == 'backup':
        backup_collection(args.category, args.name, collection_name=args.collection)
    else:
        restore_backup(args.archive, collection_name=args.collection)
