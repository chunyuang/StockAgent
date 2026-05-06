#!/usr/bin/env python3
"""Fix remaining turnover_rate=100.0 using AKShare per-stock (round 2)
Only processes stocks that still have bad data"""
import asyncio, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import akshare as ak
import pandas as pd
from pymongo import UpdateOne
from core.managers import mongo_manager

async def fix():
    await mongo_manager.initialize()
    db = mongo_manager.db

    # Get stocks still with bad data
    bad_stocks = await db.stock_daily_ak_full.distinct('ts_code', {'turnover_rate': 100.0})
    print(f"Stocks still with bad data: {len(bad_stocks)}")

    # Check how many are BJ stocks or special codes
    bj = [s for s in bad_stocks if s.endswith('.BJ') or s[0] in ('4', '8')]
    sh = [s for s in bad_stocks if s.endswith('.SH')]
    sz = [s for s in bad_stocks if s.endswith('.SZ')]
    print(f"  BJ/北交所: {len(bj)}, SH: {len(sh)}, SZ: {len(sz)}")

    # For non-BJ stocks, try downloading again with longer timeout
    retry_stocks = [s for s in bad_stocks if not s.endswith('.BJ')]
    print(f"Retrying {len(retry_stocks)} non-BJ stocks...")

    first_date = '20251201'
    last_date = '20260320'

    total_fixed = 0
    total_errors = 0
    start_time = time.time()

    for i, ts_code in enumerate(retry_stocks):
        symbol = ts_code.split('.')[0]
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period='daily', start_date=first_date, end_date=last_date, adjust='')
            if df.empty:
                # Mark as unavailable - set turnover_rate to 0 instead of 100
                ops = [UpdateOne(
                    {'ts_code': ts_code, 'trade_date': int(td)},
                    {'$set': {'turnover_rate': 0}}
                ) for td in range(int(first_date), int(last_date)+1)]
                # Only update bad ones
                result = await db.stock_daily_ak_full.bulk_write([
                    UpdateOne({'ts_code': ts_code, 'turnover_rate': 100.0}, {'$set': {'turnover_rate': 0}})
                ])
                total_fixed += result.matched_count
                await asyncio.sleep(0.1)
                continue

            bad_dates_str = set(str(d) for d in await db.stock_daily_ak_full.distinct('trade_date', {'ts_code': ts_code, 'turnover_rate': 100.0}))
            if not bad_dates_str:
                continue

            ops = []
            for _, row in df.iterrows():
                td = str(row['日期']).replace('-', '')
                if td in bad_dates_str:
                    tr = float(row['换手率']) if pd.notna(row['换手率']) else None
                    amt = float(row['成交额']) if pd.notna(row['成交额']) else None
                    if tr is not None and tr >= 0:
                        set_fields = {'turnover_rate': tr}
                        if tr > 0 and amt and amt > 0:
                            set_fields['circ_mv'] = amt / (tr / 100.0) / 10000.0
                        ops.append(UpdateOne(
                            {'ts_code': ts_code, 'trade_date': int(td)},
                            {'$set': set_fields}
                        ))

            if ops:
                result = await db.stock_daily_ak_full.bulk_write(ops)
                total_fixed += result.matched_count

            await asyncio.sleep(0.35)

        except Exception as e:
            total_errors += 1
            # For stocks that fail, mark turnover_rate as 0 (unavailable)
            try:
                result = await db.stock_daily_ak_full.bulk_write([
                    UpdateOne({'ts_code': ts_code, 'turnover_rate': 100.0}, {'$set': {'turnover_rate': 0}})
                ])
                total_fixed += result.matched_count
            except Exception:
                pass
            await asyncio.sleep(0.3)

        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{len(retry_stocks)}] fixed={total_fixed} err={total_errors} {time.time()-start_time:.0f}s")

    # For BJ stocks, mark as unavailable
    bj_fixed = 0
    if bj:
        for ts_code in bj:
            try:
                result = await db.stock_daily_ak_full.bulk_write([
                    UpdateOne({'ts_code': ts_code, 'turnover_rate': 100.0}, {'$set': {'turnover_rate': 0}})
                ])
                bj_fixed += result.matched_count
            except Exception:
                pass
        print(f"BJ stocks marked unavailable: {bj_fixed}")

    print(f"\nDone! fixed={total_fixed+bj_fixed} errors={total_errors} {time.time()-start_time:.0f}s")
    remaining = await db.stock_daily_ak_full.count_documents({'turnover_rate': 100.0})
    print(f"Remaining bad (100.0): {remaining}")
    zero = await db.stock_daily_ak_full.count_documents({'turnover_rate': 0})
    good = await db.stock_daily_ak_full.count_documents({'turnover_rate': {'$gt': 0, '$lt': 99.9}})
    print(f"Zero (unavailable): {zero}, Good (0-99.9): {good}")

if __name__ == "__main__":
    asyncio.run(fix())
