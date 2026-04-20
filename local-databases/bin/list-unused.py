#!/usr/bin/env python3
"""
列出超过 N 天没更新的数据库，提示可以归档
不自动删除，只提示，由用户决定是否归档
"""

import os
from datetime import datetime, timedelta

def list_unused(days=30):
    """列出超过 days 没更新的数据库"""
    categories = ['raw', 'factors', 'backtests']
    result = []
    
    for category in categories:
        metadata_dir = f'/root/.openclaw/workspace/local-databases/{category}/metadata'
        if not os.path.exists(metadata_dir):
            continue
        for f in os.listdir(metadata_dir):
            if not f.endswith('.md'):
                continue
            name = f.replace('.md', '')
            path = os.path.join(metadata_dir, f)
            mtime = os.path.getmtime(path)
            last_updated = datetime.fromtimestamp(mtime)
            delta = datetime.now() - last_updated
            
            if delta > timedelta(days=days):
                # 读取 metadata 获取更新时间
                with open(path, 'r') as mf:
                    content = mf.read()
                    update_time = last_updated.strftime('%Y-%m-%d')
                    for line in content.split('\n'):
                        if '| **更新时间**' in line:
                            parts = line.split('|')
                            for p in parts:
                                p = p.strip()
                                if p and not p == '更新时间' and not p == '项目' and not p == '信息':
                                    update_time = p
                                    break
                
                result.append({
                    'category': category,
                    'name': name,
                    'last_updated': update_time,
                    'days_ago': delta.days,
                })
    
    if not result:
        print(f"✅ No unused databases older than {days} days.")
        return
    
    print(f"🔍 发现 {len(result)} 个数据库超过 {days} 天没更新：")
    print()
    print("| 分类 | 名称 | 最后更新 | 天数 |")
    print("|------|------|----------|------|")
    for r in result:
        print(f"| {r['category']} | `{r['name']}` | {r['last_updated']} | {r['days_ago']} |")
    
    print()
    print("💡 建议：可以考虑归档到压缩文件节省空间，但不会删除，保留历史版本方便对比。")
    print("   归档命令例子：")
    print(f"   cd local-databases/{result[0]['category']}/data/")
    print(f"   tar -czf {result[0]['name']}.tar.gz {result[0]['name']}/")
    print("   然后删除原文件夹（如果确认不需要了）")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='List unused databases (not updated for N days)')
    parser.add_argument('--days', type=int, default=30, help='Days threshold (default: 30)')
    args = parser.parse_args()
    list_unused(args.days)
