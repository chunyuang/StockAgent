#!/usr/bin/env python3
"""
Tushare 下载每日指标数据 (物理隔离，独立脚本)
模式: 按股票批量下载每日指标 (PE, PB, 换手率, 市值等) → 存入 MongoDB daily_basic 集合

物理隔离原则:
- 只依赖 Tushare API，不依赖其他数据源
- 遵守 Tushare 频率限制
- 所有数据存入 MongoDB，LocalMongoManager 统一读取
- 因子计算需要这些数据，必须提前下载

每日指标包含:
- pe, pe_ttm: 市盈率
- pb: 市净率  
- total_mv, circ_mv: 总市值/流通市值
- turnover_rate: 换手率
- 等所有 Tushare 提供的字段
"""

import asyncio
import sys
import time
from datetime import datetime
import pymongo

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from core.managers import tushare_manager

async def download_daily_basic_by_stocks(ts_codes: list, start_date: str, end_date: str):
    print("=== Tushare 下载每日指标 (物理隔离独立下载) ===")
    print(f"股票数量: {len(ts_codes)}")
    print(f"区间: {start_date} ~ {end_date}")
    print()

    # 初始化
    await tushare_manager.initialize()

    if not tushare_manager._initialized:
        print("❌ Tushare 初始化失败，请检查 Token")
        return

    print("✅ Tushare 初始化成功")
    print()

    # 连接 MongoDB
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    collection = db['daily_basic']

    total_records = 0
    total_stocks = len(ts_codes)
    start_time = time.time()

    for idx, ts_code in enumerate(ts_codes):
        print(f"[{idx+1}/{total_stocks}] 正在下载 {ts_code}...")

        try:
            # 调用 Tushare API 获取每日指标
            records = await tushare_manager.get_daily_basic(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )

            if not records:
                print(f"  ⚠️  {ts_code} 没有数据")
                continue

            # 批量 upsert
            bulk = []
            for r in records:
                # 确保 trade_date 是字符串格式
                if 'trade_date' in r:
                    r['trade_date'] = str(r['trade_date'])
                # _id = {ts_code}_{trade_date} 确保去重
                key = f"{ts_code}_{r.get('trade_date', '')}"
                r['_id'] = key
                bulk.append({
                    'replaceOne': {
                        'filter': {'_id': key},
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

        # Tushare 频率控制，等待 0.2 秒
        await asyncio.sleep(0.2)

    elapsed = time.time() - start_time
    print()
    print("="*60)
    print("下载完成!")
    print(f"总股票数: {total_stocks}")
    print(f"总记录数: {total_records}")
    print(f"总耗时: {elapsed:.1f} 秒 ≈ {elapsed/60:.1f} 分钟")
    print(f"平均速度: {total_records/elapsed:.2f} 条/秒")

    # 统计
    final_count = collection.count_documents({
        'trade_date': {'$gte': start_date, '$lte': end_date}
    })
    print(f"数据库中区间最终记录数: {final_count}")

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
                parts = line.split()
                if parts:
                    stocks.append(parts[0])

    print(f"从文件 {filename} 读取了 {len(stocks)} 只股票")
    return stocks

if __name__ == "__main__":
    # 使用方式:
    # python download_daily_basic_tushare.py start_date end_date [stock_list_file]
    # 如果不提供股票列表文件，从 stock_basic 表读取全部股票

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
        # 从 stock_basic 读取全部股票
        print("没有提供股票列表文件，从 MongoDB stock_basic 读取全部股票...")
        client = pymongo.MongoClient(settings.mongo.url)
        db = client[settings.mongo.database]
        cursor = db['stock_basic'].find({}, {'ts_code': 1})
        stocks = [doc['ts_code'] for doc in cursor]
        client.close()
        print(f"读取到 {len(stocks)} 只股票")

    if not stocks:
        print("❌ 没有股票列表，退出")
        sys.exit(1)

    asyncio.run(download_daily_basic_by_stocks(stocks, start_date, end_date))
