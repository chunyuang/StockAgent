#!/usr/bin/env python3
"""
Tushare 代理 - 按日期下载日线数据 (独立回测模块)
模式: 逐个日期获取全部股票数据 → 存入 MongoDB stock_daily

特点:
- 使用自定义代理 API 地址
- 每天一次请求获取全部股票
- 存入统一 stock_daily 集合
"""

import asyncio
import sys
import time
from datetime import datetime, timedelta
from typing import List, Optional
import pandas as pd
import pymongo
from pymongo import ReplaceOne

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from core.managers.tushare_manager import tushare_manager


async def download_daily_range(
    start_date: str,
    end_date: str,
    request_interval: float = 1.0
):
    """按日期范围下载日线数据"""
    print(f"=== Tushare 代理 - 按日期下载日线 (独立回测模块) ===")
    print(f"区间: {start_date} ~ {end_date}")
    print(f"请求间隔: {request_interval}s/日期")
    print()

    # 初始化
    await tushare_manager.initialize()

    if not tushare_manager._initialized:
        print("❌ Tushare 初始化失败，请检查 Token 和代理 URL")
        return

    print("✅ Tushare 初始化成功")
    token = settings.tushare.token.get_secret_value()
    proxy_url = settings.tushare.http_url
    print(f"   Token: {token[:4]}****")
    print(f"   代理 URL: {proxy_url}")
    print()

    # 获取交易日历
    trade_dates = await tushare_manager.get_trade_cal(start_date, end_date)
    print(f"获取到 {len(trade_dates)} 个交易日")
    print()

    # 连接 MongoDB
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    collection = db['stock_daily']

    total_records = 0
    total_dates = len(trade_dates)
    start_time = time.time()

    for idx, trade_date in enumerate(trade_dates):
        print(f"[{idx+1}/{total_dates}] 正在下载 {trade_date}...")

        try:
            # 调用 Tushare API 获取当日全部股票
            records = await tushare_manager.get_daily(trade_date=str(trade_date))

            if not records:
                print(f"  ⚠️  {trade_date} 没有数据")
                await asyncio.sleep(request_interval)
                continue

            # 批量 upsert
            bulk = []
            for r in records:
                r['_id'] = f"{r['ts_code']}_{r['trade_date']}"
                # 确保涨跌停价存在
                if 'up_limit' not in r:
                    r['up_limit'] = None
                if 'down_limit' not in r:
                    r['down_limit'] = None

                bulk.append(ReplaceOne(
                    {'_id': r['_id']},
                    r,
                    upsert=True
                ))

            if bulk:
                result = collection.bulk_write(bulk)
                inserted = result.upserted_count
                modified = result.modified_count
                total_records += len(bulk)
                print(f"  ✅ {len(bulk)} 条记录, 新增 {inserted}, 修改 {modified}")

        except Exception as e:
            print(f"  ❌ 错误: {e}")

        # 频率控制
        await asyncio.sleep(request_interval)

    elapsed = time.time() - start_time
    print()
    print("="*60)
    print(f"下载完成!")
    print(f"总交易日: {total_dates}")
    print(f"总记录数: {total_records}")
    print(f"总耗时: {elapsed:.1f} 秒 ≈ {elapsed/60:.1f} 分钟")
    print(f"平均速度: {total_records/elapsed:.2f} 条/秒")

    client.close()


if __name__ == "__main__":
    start_date = "20251215"
    end_date = datetime.now().strftime("%Y%m%d")
    interval = 1.0

    if len(sys.argv) >= 2:
        start_date = sys.argv[1]
    if len(sys.argv) >= 3:
        end_date = sys.argv[2]
    if len(sys.argv) >= 4:
        try:
            interval = float(sys.argv[3])
        except:
            interval = 1.0

    asyncio.run(download_daily_range(start_date, end_date, interval))
