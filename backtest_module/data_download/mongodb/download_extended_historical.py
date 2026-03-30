#!/usr/bin/env python3
"""
MongoDB 扩展历史数据下载 (独立回测模块)
从已有的 price_history 集合迁移数据到 stock_daily 集合

用于:
- 原来按股票存储（一只股票一篇文档）迁移到按交易日存储（一条记录一篇文档）
- 兼容新的回测引擎数据格式
"""

import sys
import time
import pymongo
from pymongo import ReplaceOne
from tqdm import tqdm


def migrate_price_history_to_stock_daily():
    """从 price_history 迁移到 stock_daily"""
    print("=== MongoDB 数据迁移: price_history → stock_daily ===")
    print()

    # 连接 MongoDB
    client = pymongo.MongoClient()
    db = client['stock_agent']
    source_collection = db['price_history']
    target_collection = db['stock_daily']

    # 统计
    total_stocks = source_collection.count_documents({})
    print(f"源集合 price_history 共有 {total_stocks} 只股票")
    print()

    total_records = 0
    migrated_stocks = 0

    cursor = source_collection.find({})
    
    for doc in tqdm(cursor, total=total_stocks):
        ts_code = doc['ts_code']
        daily_data = doc.get('daily_data', [])

        if not daily_data:
            migrated_stocks += 1
            continue

        # 批量转换
        bulk = []
        for record in daily_data:
            # 确保格式一致
            trade_date = str(record.get('trade_date', ''))
            if len(trade_date) != 8:
                continue  # 无效日期
            
            record['ts_code'] = ts_code
            record['_id'] = f"{ts_code}_{trade_date}"
            
            # 确保涨跌停价存在
            if 'up_limit' not in record:
                if 'pre_close' in record and record['pre_close']:
                    pre_close = float(record['pre_close'])
                    if ts_code.startswith(('688', '300')):
                        up_limit = round(pre_close * 1.2, 2)
                        down_limit = round(pre_close * 0.8, 2)
                    else:
                        up_limit = round(pre_close * 1.1, 2)
                        down_limit = round(pre_close * 0.9, 2)
                    record['up_limit'] = up_limit
                    record['down_limit'] = down_limit
                else:
                    record['up_limit'] = None
                    record['down_limit'] = None

            bulk.append(ReplaceOne(
                {'_id': record['_id']},
                record,
                upsert=True
            ))

        if bulk:
            result = target_collection.bulk_write(bulk)
            total_records += len(bulk)

        migrated_stocks += 1

        # 定期进度
        if migrated_stocks % 100 == 0:
            print(f"已迁移 {migrated_stocks}/{total_stocks} 只股票，累计 {total_records} 条记录")

    print()
    print("="*60)
    print(f"迁移完成!")
    print(f"迁移股票: {migrated_stocks} 只")
    print(f"迁移记录: {total_records} 条")

    final_count = target_collection.count_documents({})
    print(f"目标集合 stock_daily 总计: {final_count} 条")

    client.close()


if __name__ == "__main__":
    migrate_price_history_to_stock_daily()
