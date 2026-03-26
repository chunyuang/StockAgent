#!/usr/bin/env python3
"""
逐个交易日下载 stock_daily 数据，使用比盈数据源
"""
import asyncio
import sys
sys.path.insert(0, '.')

from core.settings import settings
from core.managers.biying_manager import biying_manager
from core.managers.mongo_manager import mongo_manager
import akshare as ak
import pandas as pd
from datetime import datetime
import pymongo

async def main():
    await mongo_manager.initialize()
    await biying_manager.initialize()
    
    # 获取交易日历
    trade_cal = ak.tool_trade_date_hist_sina()
    trade_cal['trade_date'] = pd.to_datetime(trade_cal['trade_date'])
    mask = (trade_cal['trade_date'] >= '2026-01-05') & (trade_cal['trade_date'] <= '2026-03-20')
    trade_dates = trade_cal[mask]['trade_date'].dt.strftime('%Y%m%d').astype(int).tolist()
    
    print(f"需要下载 {len(trade_dates)} 个交易日")
    
    success_count = 0
    fail_count = 0
    
    # 获取 mongo db 客户端
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    
    for i, trade_date in enumerate(trade_dates):
        print(f"[{i+1}/{len(trade_dates)}] 正在下载 {trade_date}...")
        try:
            df = await biying_manager.get_daily(trade_date)
            if df is not None and not df.empty:
                records = df.to_dict('records')
                for r in records:
                    r['_id'] = f"{r['ts_code']}_{trade_date}"
                # 批量 upsert
                bulk = []
                for r in records:
                    bulk.append({
                        'replaceOne': {
                            'filter': {'_id': r['_id']},
                            'replacement': r,
                            'upsert': True
                        }
                    })
                if bulk:
                    result = db.stock_daily.bulk_write(bulk)
                    inserted = result.upserted_count
                    modified = result.modified_count
                    print(f"  → {len(records)} 条, 插入/更新: {inserted}/{modified}")
                success_count += 1
            else:
                print(f"  ⚠️  无数据")
                fail_count += 1
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            fail_count += 1
        
        # 睡眠避免限流
        await asyncio.sleep(3)
    
    print(f"\n===== 下载完成 =====")
    print(f"成功: {success_count}, 失败: {fail_count}")
    
    final_count = db.stock_daily.count_documents({'trade_date': {'$gte': 20260105, '$lte': 20260320}})
    print(f"最终 stock_daily 区间记录数: {final_count}")
    
    client.close()
    await biying_manager.shutdown()
    await mongo_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
