#!/usr/bin/env python3
"""
Tushare 下载涨跌停价格数据 (物理隔离，独立脚本)
模式: 按日期批量下载涨跌停统计 → 存入 MongoDB limit_list 集合

物理隔离原则:
- 只依赖 Tushare API，不依赖其他数据源
- 独立频率控制，遵守 Tushare 每分钟 500 次限制
- 所有数据存入 MongoDB，回测时 LocalMongoManager 从 MongoDB 读取
- 格式与 Tushare API 返回完全一致，不需要转换

数据说明:
- limit_list_d 接口获取每日涨跌停统计
- 包含 up_limit/down_limit (涨跌停价格)，这是选股必需字段
- 策略因子计算需要这个数据，必须提前下载存入数据库
"""

import asyncio
import sys
import time
from datetime import datetime
import pymongo

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from core.managers import tushare_manager

async def download_limit_list_range(start_date: str, end_date: str):
    print("=== Tushare 下载涨跌停价格数据 (物理隔离独立下载) ===")
    print(f"区间: {start_date} ~ {end_date}")
    print()

    # 初始化
    await tushare_manager.initialize()

    if not tushare_manager._initialized:
        print("❌ Tushare 初始化失败，请检查 Token")
        return

    print("✅ Tushare 初始化成功")
    print()

    # 获取交易日历
    trade_dates = await tushare_manager.get_trade_cal(start_date, end_date)

    print(f"获取到 {len(trade_dates)} 个交易日")
    if len(trade_dates) > 10:
        print(f"前 10 个交易日: {trade_dates[:10]}...")
    print()

    if not trade_dates:
        print("❌ 没有交易日，退出")
        return

    # 连接 MongoDB
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    collection = db['limit_list']

    total_records = 0
    total_dates = len(trade_dates)
    start_time = time.time()

    for idx, trade_date in enumerate(trade_dates):
        print(f"[{idx+1}/{total_dates}] 正在下载 {trade_date}...")

        try:
            records = await tushare_manager.get_limit_list_d(trade_date=trade_date)

            if not records:
                print(f"  ⚠️  {trade_date} 没有数据")
                continue

            # 批量 upsert
            bulk = []
            for r in records:
                # Tushare 的 limit_list_d 返回已经包含完整字段
                # 按 Tushare 格式存储，不需要转换
                key = f"{trade_date}_{r['ts_code']}"
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

        # Tushare 频率控制，每分钟 500 次 = 约 8 次每秒 → 等待 0.2 秒
        await asyncio.sleep(0.2)

    elapsed = time.time() - start_time
    print()
    print("="*60)
    print("下载完成!")
    print(f"总交易日: {total_dates}")
    print(f"总记录数: {total_records}")
    print(f"总耗时: {elapsed:.1f} 秒 ≈ {elapsed/60:.1f} 分钟")
    print(f"平均速度: {total_records/elapsed:.2f} 条/秒")

    # 最终统计
    final_count = collection.count_documents({
        'trade_date': {'$gte': start_date, '$lte': end_date}
    })
    print(f"数据库中区间最终记录数: {final_count}")

    client.close()

if __name__ == "__main__":
    # 默认下载近一年
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = "20250101"

    if len(sys.argv) >= 2:
        start_date = sys.argv[1]
    if len(sys.argv) >= 3:
        end_date = sys.argv[2]

    asyncio.run(download_limit_list_range(start_date, end_date))
