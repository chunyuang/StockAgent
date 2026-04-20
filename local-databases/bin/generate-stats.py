#!/usr/bin/env python3
"""
自动从 markdown metadata 提取统计信息，生成 json 方便程序读取
"""

import os
import json

def extract_stats_from_md(metadata_path):
    """从 markdown metadata 提取统计信息"""
    if not os.path.exists(metadata_path):
        return None
    
    with open(metadata_path, 'r') as f:
        content = f.read()
    
    stats = {}
    for line in content.split('\n'):
        if '| **' not in line:
            continue
        # 提取
        parts = line.split('|')
        if len(parts) < 3:
            continue
        key = parts[1].replace('**', '').strip().replace(' ', '_').lower()
        value = parts[2].strip()
        # 尝试转数字
        if any(c.isdigit() for c in value):
            digits = ''
            found_dot = False
            for c in value:
                if c.isdigit():
                    digits += c
                elif c == '.' and not found_dot:
                    digits += c
                    found_dot = True
            if digits:
                if '.' in digits:
                    try:
                        value = float(digits)
                    except:
                        pass
                else:
                    try:
                        value = int(digits)
                    except:
                        pass
        stats[key] = value
    
    return stats

def generate_all_stats():
    """生成所有数据库的 stats json"""
    categories = ['raw', 'factors', 'backtests']
    all_stats = {
        'raw': {},
        'factors': {},
        'backtests': {},
    }
    
    for category in categories:
        metadata_dir = f'/root/.openclaw/workspace/local-databases/{category}/metadata'
        if not os.path.exists(metadata_dir):
            continue
        for f in os.listdir(metadata_dir):
            if not f.endswith('.md'):
                continue
            name = f.replace('.md', '')
            stats = extract_stats_from_md(os.path.join(metadata_dir, f))
            if stats:
                all_stats[category][name] = stats
    
    # 写入 json
    output_path = '/root/.openclaw/workspace/local-databases/stats.json'
    with open(output_path, 'w') as f:
        json.dump(all_stats, f, indent=2)
    
    print(f"✅ Stats generated: {output_path}")
    print(f"  - raw: {len(all_stats['raw'])} databases")
    print(f"  - factors: {len(all_stats['factors'])} databases")
    print(f"  - backtests: {len(all_stats['backtests'])} databases")
    
    return all_stats

if __name__ == '__main__':
    generate_all_stats()
