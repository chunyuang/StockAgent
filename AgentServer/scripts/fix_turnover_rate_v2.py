#!/usr/bin/env python3
"""Fix turnover_rate=100.0 in stock_daily_ak_full using AKShare"""
import asyncio, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import akshare as ak
import pandas as pd
from pymongo import UpdateOne
from core.managers import mongo_manager

async def fix():
    await mongo_manager.initialize()
    db = mongo_manager.db

    bad_dates = await db.stock_daily_ak_full.distinct('trade_date', {'turnover_rate': 100.0})
    bad_dates.sort()
    bad_dates_str = set(str(d) for d in bad_dates)
    print(f"Bad dates: {len(bad_dates)}")

    all_stocks = await db.stock_daily_ak_full.distinct('ts_code', {'turnover_rate': 100.0})
    print(f"Stocks: {len(all_stocks)}")

    first_date = str(bad_dates[0])
    last_date = str(bad_dates[-1])
    start_ak = first_date
    end_ak = last_date

    total_fixed = 0
    total_errors = 0
    start_time = time.time()

    for i, ts_code in enumerate(all_stocks):
        symbol = ts_code.split('.')[0]
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period='daily', start_date=start_ak, end_date=end_ak, adjust='')
            if df.empty:
                continue

            updates = {}
            for _, row in df.iterrows():
                td = str(row['日期']).replace('-', '')
                if td in bad_dates_str:
                    tr = float(row['换手率']) if pd.notna(row['换手率']) else None
                    amt = float(row['成交额']) if pd.notna(row['成交额']) else None
                    calc_circ = amt / (tr / 100.0) / 10000.0 if tr and tr > 0 and amt and amt > 0 else None
                    if tr is not None:
                        updates[td] = {'turnover_rate': tr}
                        if calc_circ is not None:
                            updates[td]['circ_mv'] = calc_circ

            if not updates:
                continue

            ops = [UpdateOne(
                {'ts_code': ts_code, 'trade_date': int(td)},
                {'$set': fields}
            ) for td, fields in updates.items() if fields.get('turnover_rate') is not None]

            if ops:
                result = await db.stock_daily_ak_full.bulk_write(ops)
                total_fixed += result.matched_count  # 用matched_count而非modified_count

            if (i + 1) % 100 == 0:
                print(f"  [{i+1}/{len(all_stocks)}] fixed={total_fixed} err={total_errors} {time.time()-start_time:.0f}s")

            await asyncio.sleep(0.35)

        except Exception as e:
            total_errors += 1
            if total_errors <= 10:
                print(f"  {ts_code}: {e}")
            await asyncio.sleep(0.5)

    print(f"\nDone! fixed={total_fixed} errors={total_errors} {time.time()-start_time:.0f}s")
    remaining = await db.stock_daily_ak_full.count_documents({'turnover_rate': 100.0})
    print(f"Remaining bad: {remaining}")

if __name__ == "__main__":
    asyncio.run(fix())
