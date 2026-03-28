#!/usr/bin/env python3
"""
AKShare 按日期下载日线数据 (独立回测模块)
模式: 逐个日期获取全部股票数据 → 存入 MongoDB stock_daily

特点:
- 完全免费，不需要 token
- 按日期获取，每天一次请求
- 存入统一 stock_daily 集合，回测引擎直接读取
"""

import asyncio
import sys
import time
from datetime import datetime, timedelta
import pandas as pd
import pymongo

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings


async def download_daily_by_date(start_date: str, end_date: str, request_interval: float = 0.5):
    """按日期范围下载日线数据"""
    print(f"=== AKShare 按日期下载日线 (独立回测模块) ===")
    print(f"区间: {start_date} ~ {end_date}")
    print(f"请求间隔: {request_interval}s/日期")
    print()

    # 连接 MongoDB
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    collection = db['stock_daily']

    # 生成日期范围
    from datetime import datetime as dt
    start_dt = dt.strptime(start_date, "%Y%m%d")
    end_dt = dt.strptime(end_date, "%Y%m%d")
    
    all_dates = []
    current = start_dt
    while current <= end_dt:
        if current.weekday() < 5:  # 周一到周五
            all_dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    
    print(f"生成 {len(all_dates)} 个日期 (剔除周末)")
    print()

    total_records = 0
    total_dates = len(all_dates)
    start_time = time.time()

    import akshare as ak

    for idx, trade_date in enumerate(all_dates):
        print(f"[{idx+1}/{total_dates}] 正在下载 {trade_date}...")

        try:
            # AKShare 获取当日全部A股数据
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                None,
                lambda: ak.stock_zh_a_spot()
            )

            if df is None or df.empty:
                print(f"  ⚠️  {trade_date} 没有数据")
                await asyncio.sleep(request_interval)
                continue

            # 标准化格式，转换为 Tushare 兼容格式
            records = []
            for _, row in df.iterrows():
                code = str(row['代码'])
                if len(code) < 6:
                    code = code.zfill(6)
                
                # 添加后缀
                if code[0] == '6' or code[0] == '5':
                    ts_code = code + '.SH'
                else:
                    ts_code = code + '.SZ'

                record = {
                    'ts_code': ts_code,
                    'trade_date': int(trade_date),  # 统一为 int 类型，避免混合类型
                    'open': float(row['今开']),
                    'high': float(row['最高']),
                    'low': float(row['最低']),
                    'close': float(row['最新价']),
                    'pre_close': float(row['昨收']),
                    'vol': float(row['成交量']) * 100,  # AKShare 单位是手，转换为股
                    'amount': float(row['成交额']),
                }

                # 计算涨跌停价
                pre_close = record['pre_close']
                if ts_code.startswith(('688', '300')):
                    up_limit = round(pre_close * 1.2, 2)
                    down_limit = round(pre_close * 0.8, 2)
                else:
                    up_limit = round(pre_close * 1.1, 2)
                    down_limit = round(pre_close * 0.9, 2)
                record['up_limit'] = up_limit
                record['down_limit'] = down_limit
                record['_id'] = f"{ts_code}_{trade_date}"
                records.append(record)

            # 批量 upsert
            from pymongo import ReplaceOne
            bulk = []
            for r in records:
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
    print(f"总日期: {total_dates}")
    print(f"总记录数: {total_records}")
    print(f"总耗时: {elapsed:.1f} 秒 ≈ {elapsed/60:.1f} 分钟")
    print(f"平均速度: {total_records/elapsed:.2f} 条/秒")

    client.close()


def get_date_range(start_date: str, end_date: str) -> list:
    """生成日期范围，剔除周末"""
    from datetime import datetime as dt, timedelta
    start_dt = dt.strptime(start_date, "%Y%m%d")
    end_dt = dt.strptime(end_date, "%Y%m%d")
    
    all_dates = []
    current = start_dt
    while current <= end_dt:
        if current.weekday() < 5:
            all_dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return all_dates


if __name__ == "__main__":
    start_date = "20251215"
    end_date = datetime.now().strftime("%Y%m%d")

    if len(sys.argv) >= 2:
        start_date = sys.argv[1]
    if len(sys.argv) >= 3:
        end_date = sys.argv[2]

    asyncio.run(download_daily_by_date(start_date, end_date))
