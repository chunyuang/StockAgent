#!/usr/bin/env python3
"""
Tushare 按股票下载日线数据
模式: 逐个股票获取全部历史数据 → 逐条存入 MongoDB stock_daily

特点:
- 物理隔离: 纯 Tushare 实现，不依赖其他数据源
- 按股票获取: Tushare 原生 API 模式，支持频率控制
- 存入统一 stock_daily 集合，方便回测读取
- _id = "{ts_code}_{trade_date}" 确保去重
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

async def download_by_stock_list(ts_codes: list, start_date: str, end_date: str):
    print(f"=== Tushare 按股票下载 (纯 Tushare 模式) ===")
    print(f"股票数量: {len(ts_codes)}")
    print(f"区间: {start_date} ~ {end_date}")
    print()

    # 初始化
    await tushare_manager.initialize()

    if not tushare_manager._initialized:
        print("❌ Tushare 初始化失败")
        return

    print("✅ Tushare 初始化成功")
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
                continue

            # 批量 upsert
            bulk = []
            for _, row in df.iterrows():
                record = row.to_dict()
                # 确保 trade_date 是字符串 (YYYYMMDD)
                trade_date = str(record['trade_date'])
                record['trade_date'] = trade_date
                record['_id'] = f"{ts_code}_{trade_date}"
                # 确保 up_limit/down_limit 存在 (后续补全)
                if 'up_limit' not in record:
                    record['up_limit'] = None
                if 'down_limit' not in record:
                    record['down_limit'] = None

                bulk.append({
                    'replaceOne': {
                        'filter': {'_id': record['_id']},
                        'replacement': record,
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

        # Tushare 频率控制，manager 已经有令牌桶，这里等待一下确保不超限
        # 用户要求: 0.12s/请求 ≈ 500次/分钟
        await asyncio.sleep(0.12)

    elapsed = time.time() - start_time
    print()
    print("="*60)
    print(f"下载完成!")
    print(f"总记录数: {total_records}")
    print(f"总耗时: {elapsed:.1f} 秒 ≈ {elapsed/60:.1f} 分钟")
    print(f"平均速度: {total_records/elapsed:.2f} 条/秒")

    # 统计最终数据库中的数据
    if len(ts_codes) > 0:
        sample_date = ts_codes[0][:8] if len(ts_codes[0]) >= 8 else start_date[:8]
        print(f"统计完成，数据已存入 MongoDB stock_daily")

    client.close()

def get_stock_list_from_file(filename: str) -> list:
    """从文件读取股票列表"""
    import os
    if not os.path.exists(filename):
        print(f"❌ 文件不存在: {filename}")
        return []

    stocks = []
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                # 支持 ts_code 或 ts_code name 格式
                parts = line.split()
                if parts:
                    stocks.append(parts[0])

    print(f"从文件 {filename} 读取了 {len(stocks)} 只股票")
    return stocks

if __name__ == "__main__":
    # 使用方式:
    # python download_daily_tushare_by_stock.py start_date end_date [stock_list_file]
    # 如果不提供 stock_list_file，需要从 stock_basic 表读取

    start_date = "19900101"
    end_date = datetime.now().strftime("%Y%m%d")

    if len(sys.argv) >= 2:
        start_date = sys.argv[1]
    if len(sys.argv) >= 3:
        end_date = sys.argv[2]

    stocks = []
    if len(sys.argv) >= 4:
        stocks = get_stock_list_from_file(sys.argv[3])
    else:
        # 从 stock_basic 读取全部股票列表
        print(f"没有提供股票列表文件，从 MongoDB stock_basic 读取全部股票...")
        client = pymongo.MongoClient(settings.mongo.url)
        db = client[settings.mongo.database]
        cursor = db['stock_basic'].find({}, {'ts_code': 1})
        stocks = [doc['ts_code'] for doc in cursor]
        client.close()
        print(f"读取到 {len(stocks)} 只股票")

    if not stocks:
        print("❌ 没有股票列表，退出")
        sys.exit(1)

    asyncio.run(download_by_stock_list(stocks, start_date, end_date))
