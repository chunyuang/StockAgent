#!/usr/bin/env python3
"""
Tushare 下载龙虎榜数据
模式: 按日期获取，获取每日龙虎榜个股
适用: 情绪周期策略 - 分析游资介入

特点:
- 物理隔离: 纯 Tushare 实现，不依赖其他数据源
- 存入 `lhb` (龙虎榜) 集合
- _id = "{trade_date}_{ts_code}" 确保去重
"""

import asyncio
import sys
import time
from datetime import datetime
import pandas as pd
import pymongo

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from core.managers.tushare_manager import tushare_manager

async def download_lhb_range(start_date: str, end_date: str):
    print(f"=== Tushare 龙虎榜数据下载 (情绪周期辅助数据) ===")
    print(f"区间: {start_date} ~ {end_date}")
    print()

    # 初始化
    await tushare_manager.initialize()

    if not tushare_manager._initialized:
        print("❌ Tushare 初始化失败")
        return

    print("✅ Tushare 初始化成功")
    print()

    # 获取交易日历
    trade_dates = await tushare_manager.get_trade_cal(start_date, end_date)

    print(f"获取到 {len(trade_dates)} 个交易日")
    if len(trade_dates) > 10:
        print(f"前 10 个交易日: {trade_dates[:10]}...")
    print()

    # 连接 MongoDB
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    collection = db['lhb']

    total_records = 0
    total_dates = len(trade_dates)
    start_time = time.time()

    for idx, trade_date in enumerate(trade_dates):
        print(f"[{idx+1}/{total_dates}] 正在下载 {trade_date}...")

        try:
            # 调用 Tushare API 获取龙虎榜
            df = await tushare_manager._call_api("top_list", trade_date=trade_date)

            if df.empty:
                print(f"  ⚠️  {trade_date} 没有龙虎榜数据")
                continue

            # 批量 upsert
            bulk = []
            for _, row in df.iterrows():
                record = row.to_dict()
                ts_code = record['ts_code']
                record['_id'] = f"{trade_date}_{ts_code}"
                record['trade_date'] = trade_date

                bulk.append({
                    'replaceOne': {
                        'filter': {'_id': record['_id']},
                        'replacement': record,
                        'upsert': True,
                    }
                })

            if bulk:
                result = collection.bulk_write(bulk)
                inserted = result.upserted_count
                modified = result.modified_count
                total_records += len(bulk)
                print(f"  ✅ {len(bulk)} 条记录, 新增 {inserted}, 修改 {modified}")

        except Exception as e:
            print(f"  ❌ 错误: {e}")
            continue

        # Tushare 频率控制，等待 0.5 秒
        await asyncio.sleep(0.5)

    elapsed = time.time() - start_time
    print()
    print("="*60)
    print(f"下载完成!")
    print(f"总交易日: {total_dates}")
    print(f"总记录数: {total_records}")
    print(f"总耗时: {elapsed:.1f} 秒 ≈ {elapsed/60:.1f} 分钟")
    print(f"平均速度: {total_records/elapsed:.2f} 条/秒")

    # 统计
    final_count = collection.count_documents({
        'trade_date': {'$gte': start_date, '$lte': end_date}
    })
    print(f"数据库中区间最终记录数: {final_count}")

    client.close()

if __name__ == "__main__":
    # 使用方式:
    # python download_lhb_tushare.py start_date end_date
    start_date = "20251215"
    end_date = datetime.now().strftime("%Y%m%d")

    if len(sys.argv) >= 2:
        start_date = sys.argv[1]
    if len(sys.argv) >= 3:
        end_date = sys.argv[2]

    asyncio.run(download_lhb_range(start_date, end_date))
