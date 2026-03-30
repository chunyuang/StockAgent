#!/usr/bin/env python3
"""
AKShare 获取涨跌停列表 (独立回测模块)
获取每日涨跌停股票列表，存入 MongoDB limit_list
"""

import asyncio
import sys
import time
from datetime import datetime, timedelta
import pymongo

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings


async def download_limit_list(start_date: str, end_date: str, request_interval: float = 0.5):
    """下载涨跌停列表"""
    print(f"=== AKShare 获取涨跌停列表 (独立回测模块) ===")
    print(f"区间: {start_date} ~ {end_date}")
    print(f"请求间隔: {request_interval}s/日期")
    print()

    # 连接 MongoDB
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    collection = db['limit_list']

    # 生成日期范围
    from datetime import datetime as dt
    start_dt = dt.strptime(start_date, "%Y%m%d")
    end_dt = dt.strptime(end_date, "%Y%m%d")
    
    all_dates = []
    current = start_dt
    while current <= end_dt:
        if current.weekday() < 5:
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
            loop = asyncio.get_event_loop()
            
            # 涨停
            zt_records = []
            try:
                date_str = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
                zt_df = await loop.run_in_executor(
                    None,
                    lambda: ak.stock_zt_pool_em(date=date_str)
                )
                if zt_df is not None and not zt_df.empty:
                    for _, row in zt_df.iterrows():
                        code = str(row['代码'])
                        if len(code) < 6:
                            code = code.zfill(6)
                        if code[0] == '6' or code[0] == '5':
                            ts_code = code + '.SH'
                        else:
                            ts_code = code + '.SZ'
                        zt_records.append({
                            'trade_date': trade_date,
                            'ts_code': ts_code,
                            'name': str(row['名称']),
                            'pct_chg': float(row['涨跌幅']) if '涨跌幅' in row else None,
                            'close': float(row['最新价']) if '最新价' in row else None,
                            'limit': 'U',  # 涨停
                        })
            except Exception as e:
                print(f"  ⚠️ 涨停获取失败: {e}")

            # 跌停
            dt_records = []
            try:
                date_str = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
                dt_df = await loop.run_in_executor(
                    None,
                    lambda: ak.stock_zt_pool_dtgc_em(date=date_str)
                )
                if dt_df is not None and not dt_df.empty:
                    for _, row in dt_df.iterrows():
                        code = str(row['代码'])
                        if len(code) < 6:
                            code = code.zfill(6)
                        if code[0] == '6' or code[0] == '5':
                            ts_code = code + '.SH'
                        else:
                            ts_code = code + '.SZ'
                        dt_records.append({
                            'trade_date': trade_date,
                            'ts_code': ts_code,
                            'name': str(row['名称']),
                            'pct_chg': float(row['涨跌幅']) if '涨跌幅' in row else None,
                            'close': float(row['最新价']) if '最新价' in row else None,
                            'limit': 'D',  # 跌停
                        })
            except Exception as e:
                print(f"  ⚠️ 跌停获取失败: {e}")

            # 批量写入
            from pymongo import ReplaceOne
            bulk = []
            all_records = zt_records + dt_records
            for r in all_records:
                r['_id'] = f"{r['ts_code']}_{r['trade_date']}_{r['limit']}"
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

        await asyncio.sleep(request_interval)

    elapsed = time.time() - start_time
    print()
    print("="*60)
    print(f"下载完成!")
    print(f"总日期: {total_dates}")
    print(f"总记录数: {total_records}")
    print(f"总耗时: {elapsed:.1f} 秒 ≈ {elapsed/60:.1f} 分钟")

    client.close()


if __name__ == "__main__":
    start_date = "20251215"
    end_date = datetime.now().strftime("%Y%m%d")

    if len(sys.argv) >= 2:
        start_date = sys.argv[1]
    if len(sys.argv) >= 3:
        end_date = sys.argv[2]

    asyncio.run(download_limit_list(start_date, end_date))
