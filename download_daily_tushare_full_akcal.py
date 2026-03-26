#!/usr/bin/env python3
"""
使用 Tushare 自定义节点下载近三个月日线数据
区间: 2026-01-05 ~ 2026-03-20
频率: 按日期获取，间隔 0.5s
交易日历从 AKShare 获取
"""

import asyncio
import sys
import time
import pandas as pd
import pymongo
import akshare as ak

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from core.managers.tushare_manager import tushare_manager

async def download_full_range(start_date: str, end_date: str):
    print(f"=== Tushare 全区间下载 (交易日历来自 AKShare) ===")
    print(f"区间: {start_date} ~ {end_date}")
    print()
    
    # 初始化
    await tushare_manager.initialize()
    
    if not tushare_manager._initialized:
        print("❌ Tushare 初始化失败")
        return
    
    print("✅ Tushare 初始化成功")
    print()
    
    # 从 AKShare 获取交易日历
    print("正在从 AKShare 获取交易日历...")
    trade_cal = ak.tool_trade_date_hist_sina()
    trade_cal['trade_date'] = pd.to_datetime(trade_cal['trade_date'])
    mask = (trade_cal['trade_date'] >= pd.to_datetime(start_date)) & (trade_cal['trade_date'] <= pd.to_datetime(end_date))
    trade_dates = trade_cal[mask]['trade_date'].dt.strftime('%Y%m%d').tolist()
    
    print(f"获取到 {len(trade_dates)} 个交易日")
    print(f"交易日: {trade_dates[:10]}...")
    print()
    
    # 连接 MongoDB
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    collection = db['stock_daily']
    
    total_records = 0
    start_time = time.time()
    
    for i, trade_date in enumerate(trade_dates):
        print(f"[{i+1}/{len(trade_dates)} 正在下载 {trade_date}...")
        
        try:
            records = await tushare_manager.get_daily(trade_date=trade_date)
            
            if not records:
                print(f"  ⚠️  {trade_date} 没有数据")
                continue
            
            # 批量 upsert
            bulk = []
            for r in records:
                r['_id'] = f"{r['ts_code']}_{r['trade_date']}"
                bulk.append({
                    'replaceOne': {
                        'filter': {'_id': r['_id']},
                        'replacement': r,
                        'upsert': True
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
        
        # 已经在 _call_api 中添加了 0.5s 间隔，这里不需要再加
    
    elapsed = time.time() - start_time
    print()
    print("="*60)
    print(f"下载完成!")
    print(f"总记录数: {total_records}")
    print(f"总耗时: {elapsed:.1f} 秒 ≈ {elapsed/60:.1f} 分钟")
    print(f"平均速度: {total_records/elapsed:.2f} 条/秒")
    
    # 统计最终数据库中的数据
    final_count = collection.count_documents({'trade_date': {'$gte': int(start_date), '$lte': int(end_date)}})
    print(f"数据库中区间最终记录数: {final_count}")
    
    client.close()

if __name__ == "__main__":
    start_date = "20260105"
    end_date = "20260320"
    
    if len(sys.argv) >= 2:
        start_date = sys.argv[1]
    if len(sys.argv) >= 3:
        end_date = sys.argv[2]
    
    asyncio.run(download_full_range(start_date, end_date))
