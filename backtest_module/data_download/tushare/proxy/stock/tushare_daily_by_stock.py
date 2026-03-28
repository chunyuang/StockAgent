#!/usr/bin/env python3
"""
Tushare 代理 - 按股票下载日线数据 (独立回测模块)
模式: 逐个股票获取指定区间历史数据 → 存入 MongoDB stock_daily

特点:
- 使用自定义代理 API 地址
- 严格频率控制，间隔可配置
- 存入统一 stock_daily 集合，回测引擎直接读取
"""

import asyncio
import sys
import time
from datetime import datetime
from typing import List, Optional
import pandas as pd
import pymongo
from pymongo import ReplaceOne

# 添加项目路径
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from core.managers.tushare_manager import tushare_manager


async def download_by_stock_list(
    ts_codes: List[str],
    start_date: str,
    end_date: str,
    request_interval: float = 1.0
):
    """按股票列表下载日线数据"""
    print(f"=== Tushare 代理 - 按股票下载日线 (独立回测模块) ===")
    print(f"股票数量: {len(ts_codes)}")
    print(f"区间: {start_date} ~ {end_date}")
    print(f"请求间隔: {request_interval}s/股票")
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
    print(f"   频率限制: {settings.tushare.rate_limit}/分钟")
    print()

    # 连接 MongoDB
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    collection = db['stock_daily']

    total_records = 0
    total_stocks = len(ts_codes)
    start_time = time.time()

    for idx, ts_code in enumerate(ts_codes):
        print(f"[{idx+1}/{total_stocks}] 正在下载 {ts_code}...")

        try:
            # 调用 Tushare API 获取这只股票指定区间的全部数据
            df = await tushare_manager.get_daily_by_stock(ts_code, start_date, end_date)

            if df is None or df.empty:
                print(f"  ⚠️  {ts_code} 没有数据")
                await asyncio.sleep(request_interval)
                continue

            # 批量 upsert
            bulk = []
            for _, row in df.iterrows():
                record = row.to_dict()
                # 确保 trade_date 是字符串格式 (YYYYMMDD)
                trade_date = str(record['trade_date'])
                record['trade_date'] = trade_date
                record['_id'] = f"{ts_code}_{trade_date}"
                # 确保 up_limit/down_limit 存在
                if 'up_limit' not in record:
                    record['up_limit'] = None
                if 'down_limit' not in record:
                    record['down_limit'] = None

                bulk.append(ReplaceOne(
                    {'_id': record['_id']},
                    record,
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

        # 严格控制请求间隔
        await asyncio.sleep(request_interval)

    elapsed = time.time() - start_time
    print()
    print("="*60)
    print(f"下载完成!")
    print(f"总股票数: {total_stocks}")
    print(f"总记录数: {total_records}")
    print(f"总耗时: {elapsed:.1f} 秒 ≈ {elapsed/60:.1f} 分钟")
    print(f"平均速度: {total_records/elapsed:.2f} 条/秒")

    # 统计最终数据库中的数据
    final_count = collection.count_documents({
        'trade_date': {'$gte': start_date, '$lte': end_date}
    })
    print(f"数据库中区间最终记录数: {final_count}")

    client.close()


def get_stock_list_from_file(filename: str) -> List[str]:
    """从文件读取股票列表"""
    import os
    if not os.path.exists(filename):
        print(f"❌ 文件不存在: {filename}")
        return []

    stocks: List[str] = []
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                parts = line.split()
                if parts:
                    stocks.append(parts[0])

    print(f"从文件 {filename} 读取了 {len(stocks)} 只股票")
    return stocks


def get_all_stocks_from_mongo() -> List[str]:
    """从 MongoDB stock_basic 读取全部上市股票"""
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    cursor = db['stock_basic'].find({'list_status': 'L'}, {'ts_code': 1})
    stocks = [doc['ts_code'] for doc in cursor]
    client.close()
    print(f"从 MongoDB stock_basic 读取到 {len(stocks)} 只上市股票")
    return stocks


if __name__ == "__main__":
    # 使用方式:
    # python backtest_module/data_download/tushare/proxy/tushare_daily_by_stock.py start_date end_date [stock_list_file] [interval]
    # 间隔默认 1.0s

    start_date = "19900101"
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

    stocks: List[str] = []
    if len(sys.argv) >= 5:
        stocks = get_stock_list_from_file(sys.argv[4])
    else:
        # 默认从 stock_basic 读取全部股票
        print(f"没有提供股票列表文件，从 MongoDB stock_basic 读取全部上市股票...")
        stocks = get_all_stocks_from_mongo()

    if not stocks:
        print("❌ 没有股票列表，退出")
        sys.exit(1)

    asyncio.run(download_by_stock_list(stocks, start_date, end_date, interval))
