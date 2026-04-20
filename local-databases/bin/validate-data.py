#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据质量检查
检查新增数据库的基本质量：
- 检查有没有空值
- 检查价格是不是在合理范围
- 检查交易日是不是连续
- 检查股票数量是不是对
"""

import argparse
from pymongo import MongoClient


def validate_raw_data(raw_name, db_name='stock_agent'):
    client = MongoClient('mongodb://localhost:27017/')
    db = client[db_name]
    coll = db['stock_daily_ak_full']
    total = coll.count_documents({})
    print(f"Total records: {total}")
    null_open = coll.count_documents({'open': None})
    null_close = coll.count_documents({'close': None})
    null_high = coll.count_documents({'high': None})
    null_low = coll.count_documents({'low': None})
    null_vol = coll.count_documents({'vol': None})
    print("\nNull checks:")
    print(f"  open: {null_open} nulls")
    print(f"  high: {null_high} nulls")
    print(f"  low: {null_low} nulls")
    print(f"  close: {null_close} nulls")
    print(f"  volume: {null_vol} nulls")
    cond1 = {'open': {'$lte': 0}}
    cond2 = {'close': {'$lte': 0}}
    cond3 = {'high': {'$lte': 0}}
    cond4 = {'low': {'$lte': 0}}
    invalid_price = coll.count_documents({'$or': [cond1, cond2, cond3, cond4]})
    print(f"\nInvalid price (<= 0): {invalid_price} records")
    step1 = {'$match': {'$expr': {'$lt': ['$high', '$close']}}}
    step2 = {'$count': 'count'}
    pipeline = [step1, step2]
    result = list(coll.aggregate(pipeline))
    invalid_high = result[0]['count'] if result else 0
    print(f"Invalid high (high < close): {invalid_high} records")
    step1 = {'$match': {'$expr': {'$lt': ['$high', '$open']}}}
    step2 = {'$count': 'count'}
    pipeline = [step1, step2]
    result = list(coll.aggregate(pipeline))
    invalid_high_open = result[0]['count'] if result else 0
    print(f"Invalid high (high < open): {invalid_high_open} records")
    invalid_high += invalid_high_open
    step1 = {'$match': {'$expr': {'$gt': ['$low', '$close']}}}
    step2 = {'$count': 'count'}
    pipeline = [step1, step2]
    result = list(coll.aggregate(pipeline))
    invalid_low = result[0]['count'] if result else 0
    print(f"Invalid low (low > close): {invalid_low} records")
    step1 = {'$match': {'$expr': {'$gt': ['$low', '$open']}}}
    step2 = {'$count': 'count'}
    pipeline = [step1, step2]
    result = list(coll.aggregate(pipeline))
    invalid_low_open = result[0]['count'] if result else 0
    print(f"Invalid low (low > open): {invalid_low_open} records")
    invalid_low += invalid_low_open
    trade_dates = coll.distinct('trade_date')
    # 确保都是 int
    trade_dates = [int(d) for d in trade_dates]
    trade_dates.sort()
    print(f"\nUnique trade dates: {len(trade_dates)}")
    if len(trade_dates) > 1:
        gaps = 0
        for i in range(1, len(trade_dates)):
            prev = trade_dates[i-1]
            curr = trade_dates[i]
            if (curr - prev) > 100:
                gaps += 1
        print(f"Large gaps between trade dates (> 1 month): {gaps}")
    stocks = coll.distinct('ts_code')
    print(f"Unique stocks: {len(stocks)}")
    total_errors = null_open + null_close + null_high + null_low + null_vol + invalid_price + invalid_high + invalid_low
    print("\n=== SUMMARY ===")
    print(f"Total errors: {total_errors}")
    if total_errors == 0:
        print("\n✅ All checks passed!")
        return True
    else:
        print("\n⚠️  Some errors found, please check above")
        return False


def validate_factors(factor_name, db_name='stock_agent'):
    client = MongoClient('mongodb://localhost:27017/')
    db = client[db_name]
    coll = db['strategy_signals']
    total = coll.count_documents({})
    print(f"Total factor records: {total}")
    first = coll.find_one()
    if not first:
        print("❌ No factor records found")
        return False
    factor_names = [k for k in first.keys() if k not in ['_id', 'ts_code', 'trade_date']]
    print(f"\nFactors: {len(factor_names)}")
    total_errors = 0
    for f in factor_names:
        null_count = coll.count_documents({f: None})
        if null_count > 0:
            print(f"  {f}: {null_count} nulls")
            total_errors += null_count
    print("\n=== SUMMARY ===")
    print(f"Total errors: {total_errors}")
    if total_errors == 0:
        print("\n✅ All checks passed!")
        return True
    else:
        print("\n⚠️  Some null values found, please check above")
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Validate data quality')
    parser.add_argument('--type', choices=['raw', 'factors'], required=True, help='Data type')
    parser.add_argument('--name', help='Database name')
    args = parser.parse_args()
    if args.type == 'raw':
        validate_raw_data(args.name)
    else:
        validate_factors(args.name)
