#!/usr/bin/env python3
"""
Tushare 下载财务指标数据 (物理隔离，独立脚本)
模式: 按股票批量下载财务指标 → 存入 MongoDB fina_indicator 集合

物理隔离原则:
- 只依赖 Tushare API，不依赖其他数据源
- 遵守 Tushare 频率限制
- 所有数据存入 MongoDB，LocalMongoManager 统一读取
- 因子分析需要财务指标，必须提前下载

财务指标包含:
- eps: 每股收益
- roe: 净资产收益率
- netprofit_margin: 净利率
- 各种成长能力/营运能力/偿债能力指标
- 完整列表见 Tushare fina_indicator 接口文档
"""

import asyncio
import sys
import time
from datetime import datetime
import pandas as pd
import pymongo

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from core.managers import tushare_manager

async def download_fina_indicator_by_stocks(ts_codes: list, limit_per_stock: int = 8):
    """
    按股票批量下载财务指标
    
    Args:
        ts_codes: 股票代码列表
        limit_per_stock: 每只股票保留最近多少份财报，默认 8 份 = 2 年
    """
    print(f"=== Tushare 下载财务指标 (物理隔离独立下载) ===")
    print(f"股票数量: {len(ts_codes)}")
    print(f"每只股票保留最近: {limit_per_stock} 份财报")
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
    collection = db['fina_indicator']

    total_records = 0
    total_stocks = len(ts_codes)
    start_time = time.time()

    for idx, ts_code in enumerate(ts_codes):
        print(f"[{idx+1}/{total_stocks}] 正在下载 {ts_code}...")

        try:
            # 调用 Tushare API 获取财务指标
            records = await tushare_manager.get_financial_indicator(
                ts_code=ts_code,
                limit=limit_per_stock,
            )

            if not records:
                print(f"  ⚠️  {ts_code} 没有数据")
                continue

            # 批量 upsert
            bulk = []
            for r in records:
                # 确保 end_date 是字符串格式
                if 'end_date' in r:
                    r['end_date'] = str(r['end_date'])
                # _id = {ts_code}_{end_date} 确保去重
                key = f"{ts_code}_{r.get('end_date', '')}"
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
    print(f"下载完成!")
    print(f"总股票数: {total_stocks}")
    print(f"总记录数: {total_records}")
    print(f"总耗时: {elapsed:.1f} 秒 ≈ {elapsed/60:.1f} 分钟")
    print(f"平均速度: {total_records/elapsed:.2f} 条/秒")

    # 统计
    final_count = collection.count_documents({})
    print(f"数据库中总记录数: {final_count}")

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
    # python download_fina_indicator_tushare.py [stock_list_file] [limit_per_stock]

    limit_per_stock = 8
    stocks = []

    if len(sys.argv) >= 2:
        stocks = get_stock_list_from_file(sys.argv[1])
        if len(sys.argv) >= 3:
            limit_per_stock = int(sys.argv[2])
    else:
        # 从 stock_basic 读取全部股票
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

    asyncio.run(download_fina_indicator_by_stocks(stocks, limit_per_stock))
