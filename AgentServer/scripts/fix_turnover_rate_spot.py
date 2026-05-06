#!/usr/bin/env python3
"""
用AKShare stock_zh_a_spot_em获取当前换手率+流通市值，
反算历史换手率：turnover_rate = amount(元) / circ_mv(元) * 100
circ_mv用今天的流通市值近似（3个月内误差可接受）
"""
import asyncio, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import akshare as ak
import pandas as pd
from pymongo import UpdateOne
from core.managers import mongo_manager

async def fix():
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    # 1. 获取AKShare全市场实时数据（含换手率+流通市值）
    print("获取AKShare全市场行情...")
    df = ak.stock_zh_a_spot_em()
    print(f"获取到 {len(df)} 只股票")
    
    # 2. 构建ts_code -> {circ_mv(元), turnover_rate} 映射
    circ_mv_map = {}  # ts_code -> 流通市值(元)
    
    for _, row in df.iterrows():
        code = str(row['代码']).zfill(6)
        if code.startswith(('6', '9')):
            ts_code = f"{code}.SH"
        elif code.startswith(('8', '4')):
            ts_code = f"{code}.BJ"
        else:
            ts_code = f"{code}.SZ"
        
        lt = row.get('流通市值')  # 元
        if pd.notna(lt) and float(lt) > 0:
            circ_mv_map[ts_code] = float(lt)
    
    print(f"有流通市值数据: {len(circ_mv_map)}")
    
    # 3. 按交易日批量修复
    bad_dates = await db.stock_daily_ak_full.distinct('trade_date', {'turnover_rate': 100.0})
    bad_dates.sort()
    print(f"需要修复的交易日: {len(bad_dates)}")
    
    total_fixed = 0
    total_zero = 0
    start_time = time.time()
    
    for i, trade_date in enumerate(bad_dates):
        # 获取当日所有坏数据
        bad_docs = await db.stock_daily_ak_full.find(
            {'trade_date': trade_date, 'turnover_rate': 100.0},
            {'ts_code': 1, 'amount': 1}
        ).to_list(10000)
        
        ops = []
        for doc in bad_docs:
            ts_code = doc['ts_code']
            amount = doc.get('amount', 0)  # 元
            
            if ts_code in circ_mv_map and amount and amount > 0:
                circ_mv = circ_mv_map[ts_code]
                tr = amount / circ_mv * 100
                # 合理范围检查 (0.01% ~ 80%)
                if 0.01 < tr < 80:
                    ops.append(UpdateOne(
                        {'ts_code': ts_code, 'trade_date': trade_date},
                        {'$set': {
                            'turnover_rate': round(tr, 4),
                            'circ_mv': round(circ_mv / 1e4, 4),  # 元→万元
                        }}
                    ))
                else:
                    # 异常值标记为0
                    ops.append(UpdateOne(
                        {'ts_code': ts_code, 'trade_date': trade_date},
                        {'$set': {'turnover_rate': 0, 'circ_mv': round(circ_mv / 1e4, 4)}}
                    ))
                    total_zero += 1
            else:
                # 无流通市值数据
                ops.append(UpdateOne(
                    {'ts_code': ts_code, 'trade_date': trade_date},
                    {'$set': {'turnover_rate': 0}}
                ))
                total_zero += 1
        
        if ops:
            # Batch in chunks of 500
            for j in range(0, len(ops), 500):
                chunk = ops[j:j+500]
                result = await db.stock_daily_ak_full.bulk_write(chunk)
                total_fixed += result.matched_count
        
        if (i + 1) % 10 == 0 or i == len(bad_dates) - 1:
            elapsed = time.time() - start_time
            print(f"  [{i+1}/{len(bad_dates)}] fixed={total_fixed} zero={total_zero} {elapsed:.0f}s")
    
    print(f"\nDone! fixed={total_fixed} zero={total_zero} {time.time()-start_time:.0f}s")
    remaining = await db.stock_daily_ak_full.count_documents({'turnover_rate': 100.0})
    zero = await db.stock_daily_ak_full.count_documents({'turnover_rate': 0})
    good = await db.stock_daily_ak_full.count_documents({'turnover_rate': {'$gt': 0, '$lt': 99.9}})
    total = await db.stock_daily_ak_full.count_documents({})
    print(f"\nFinal stats:")
    print(f"  Total: {total}")
    print(f"  Bad(100.0): {remaining} ({remaining/total*100:.1f}%)")
    print(f"  Zero(0): {zero} ({zero/total*100:.1f}%)")
    print(f"  Good: {good} ({good/total*100:.1f}%)")

if __name__ == "__main__":
    asyncio.run(fix())
