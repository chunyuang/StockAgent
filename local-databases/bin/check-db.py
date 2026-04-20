#!/usr/bin/env python3
"""
数据库一致性校验工具
检查本地 MongoDB 中的数据数量是否与 metadata 记录一致
"""

import argparse
import sys
import os
from pymongo import MongoClient

def load_metadata(metadata_path):
    """加载 metadata 文件，提取关键统计信息"""
    if not os.path.exists(metadata_path):
        return None
    
    stats = {}
    with open(metadata_path, 'r') as f:
        content = f.read()
    
    # 提取统计信息
    for line in content.split('\n'):
        if '总日线记录数' in line:
            # find number
            for part in line.split('|'):
                digits = ''.join([c for c in part if c.isdigit()])
                if digits:
                    stats['total_records'] = int(digits)
                    break
        if '总因子记录数' in line:
            # find number
            for part in line.split('|'):
                digits = ''.join([c for c in part if c.isdigit()])
                if digits:
                    stats['total_records'] = int(digits)
                    break
        if '股票数量' in line:
            for part in line.split('|'):
                digits = ''.join([c for c in part if c.isdigit()])
                if digits:
                    stats['n_stocks'] = int(digits)
                    break
        if '交易日数量' in line:
            for part in line.split('|'):
                digits = ''.join([c for c in part if c.isdigit()])
                if digits:
                    stats['n_days'] = int(digits)
                    break
    
    return stats

def check_mongodb(collection_name, expected_count):
    """检查 MongoDB 中集合记录数是否符合预期"""
    client = MongoClient('mongodb://localhost:27017/')
    db = client['stock_agent']
    coll = db[collection_name]
    actual = coll.count_documents({})
    client.close()
    
    return actual, expected_count

def main():
    parser = argparse.ArgumentParser(description='Check local database consistency')
    parser.add_argument('--raw', help='Raw data name (e.g. 20251215-20260318-akshare)')
    parser.add_argument('--factors', help='Factor set name (e.g. 20251215-20260318-akshare--21pricefactors)')
    parser.add_argument('--backtest', help='Backtest name')
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 检查原始数据
    if args.raw:
        metadata_path = os.path.join(base_dir, 'raw', 'metadata', f'{args.raw}.md')
        stats = load_metadata(metadata_path)
        if not stats:
            print(f"❌ Metadata not found: {metadata_path}")
            sys.exit(1)
        
        print(f"=== Checking raw data: {args.raw} ===")
        actual, expected = check_mongodb('stock_daily_ak_full', stats.get('total_records', 0))
        print(f"  Expected: {expected}")
        print(f"  Actual:   {actual}")
        if abs(actual - expected) <= max(int(expected * 0.01), 5):
            print("✅ OK - difference within tolerance")
        else:
            print("⚠️  MISMATCH - number of records doesn't match!")
            print("    Please check if data is correctly imported/recomputed.")
            sys.exit(1)
    
    # 检查因子数据
    if args.factors:
        metadata_path = os.path.join(base_dir, 'factors', 'metadata', f'{args.factors}.md')
        stats = load_metadata(metadata_path)
        if not stats:
            print(f"\n❌ Metadata not found: {metadata_path}")
            sys.exit(1)
        
        print(f"\n=== Checking factor data: {args.factors} ===")
        actual, expected = check_mongodb('strategy_signals', stats.get('total_records', 0))
        print(f"  Expected: {expected}")
        print(f"  Actual:   {actual}")
        if abs(actual - expected) <= max(int(expected * 0.01), 5):
            print("✅ OK - difference within tolerance")
        else:
            print("⚠️  MISMATCH - number of records doesn't match!")
            print("    Did you forget to recompute factors after changing them?")
            sys.exit(1)
    
    print("\n✅ All checks passed!")

if __name__ == '__main__':
    main()