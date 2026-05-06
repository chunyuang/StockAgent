#!/usr/bin/env python3
"""
修复 stock_daily_ak_full 中 turnover_rate=100.0 的假数据
方案：用 AKShare stock_zh_a_hist 逐股票下载真实换手率，替换假数据
同时用 amount/turnover_rate*100 反算 circ_mv

AKShare 换手率单位：百分比（如0.2表示0.2%）
stock_daily_ak_full 换手率单位：百分比（如0.2表示0.2%，与AKShare一致）
amount 单位：元
circ_mv = amount / (turnover_rate/100) = amount * 100 / turnover_rate（单位：元 → 万元需/10000）
"""

import asyncio
import sys
import os
import time
import akshare as ak
import pandas as pd
from pymongo import UpdateOne

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers import mongo_manager


async def fix():
    await mongo_manager.initialize()
    db = mongo_manager.db

    # 1. 获取需要修复的交易日和股票
    bad_dates = await db.stock_daily_ak_full.distinct('trade_date', {'turnover_rate': 100.0})
    bad_dates.sort()
    print(f"需要修复的交易日: {len(bad_dates)} ({bad_dates[0]} ~ {bad_dates[-1]})")

    bad_dates_str = set(str(d) for d in bad_dates)

    # 获取所有股票代码
    all_stocks = await db.stock_daily_ak_full.distinct('ts_code', {'turnover_rate': 100.0})
    print(f"涉及股票: {len(all_stocks)} 只")

    # 2. 逐股票从AKShare下载历史数据（包含换手率）
    # 转换日期格式 (trade_date可能是int或str)
    first_date = str(bad_dates[0])
    last_date = str(bad_dates[-1])
    start_date = f"{first_date[:4]}-{first_date[4:6]}-{first_date[6:]}"
    end_date = f"{last_date[:4]}-{last_date[4:6]}-{last_date[6:]}"
    print(f"AKShare 查询区间: {start_date} ~ {end_date}")

    total_fixed = 0
    total_errors = 0
    start_time = time.time()

    # Convert ts_code to AKShare symbol: 600000.SH -> 600000
    for i, ts_code in enumerate(all_stocks):
        symbol = ts_code.split('.')[0]
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period='daily',
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust=''
            )

            if df.empty:
                continue

            # Build trade_date -> turnover_rate mapping
            # AKShare columns: 日期, 换手率, 成交额
            updates = {}
            for _, row in df.iterrows():
                td = str(row['日期']).replace('-', '')
                # 比较时都用字符串
                if td in bad_dates_str:
                    tr = float(row['换手率']) if pd.notna(row['换手率']) else None
                    amt = float(row['成交额']) if pd.notna(row['成交额']) else None
                    
                    calc_circ = None
                    if tr and tr > 0 and amt and amt > 0:
                        # circ_mv(万元) = amount(元) / (turnover_rate/100) / 10000
                        calc_circ = amt / (tr / 100.0) / 10000.0
                    
                    updates[td] = {'turnover_rate': tr, 'circ_mv': calc_circ, 'trade_date_int': int(td)}

            if not updates:
                continue

            # Batch update
            bulk_ops = []
            for td, fields in updates.items():
                if fields['turnover_rate'] is not None:
                    # trade_date在DB中存为int，确保filter匹配
                    td_filter = int(td) if len(td) == 8 else td
                    set_fields = {k: v for k, v in fields.items() if k not in ('trade_date_int',) and v is not None}
                    bulk_ops.append(UpdateOne(
                        {'ts_code': ts_code, 'trade_date': td_filter},
                        {'$set': set_fields}
                    ))

            if bulk_ops:
                result = await db.stock_daily_ak_full.bulk_write(bulk_ops)
                total_fixed += result.modified_count

            if (i + 1) % 100 == 0:
                elapsed = time.time() - start_time
                print(f"  [{i+1}/{len(all_stocks)}] 已修复 {total_fixed} 条, 耗时 {elapsed:.0f}s")

            # Rate limit: AKShare allows ~3 req/s
            await asyncio.sleep(0.35)

        except Exception as e:
            total_errors += 1
            if total_errors <= 5:
                print(f"  {ts_code}: 错误 {e}")
            await asyncio.sleep(0.5)

    elapsed = time.time() - start_time
    print(f"\n修复完成! 修改 {total_fixed} 条, 错误 {total_errors}, 耗时 {elapsed:.0f}s ({elapsed/60:.1f}min)")

    # Verify
    remaining = await db.stock_daily_ak_full.count_documents({'turnover_rate': 100.0})
    total = await db.stock_daily_ak_full.count_documents({})
    print(f"剩余 turnover_rate=100.0: {remaining}/{total}")

    # Sample
    sample = await db.stock_daily_ak_full.find_one({'trade_date': bad_dates[-1], 'turnover_rate': {'$ne': 100.0}})
    if sample:
        print(f"抽样: {sample['ts_code']} {sample['trade_date']}: turnover_rate={sample.get('turnover_rate')}, circ_mv={sample.get('circ_mv')}")


if __name__ == "__main__":
    asyncio.run(fix())
