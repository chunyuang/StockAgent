#!/usr/bin/env python3
"""
修复 stock_daily_ak_full 中 turnover_rate=100.0 的假数据
方案：从 Tushare daily_basic 按交易日下载真实换手率/流通市值，覆盖假数据

Tushare daily_basic 按 trade_date 查询可一次获取全市场数据（约5000只/天）
频率限制：约120次/分钟，75个交易日需要1分钟
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers import mongo_manager, tushare_manager


async def fix():
    await mongo_manager.initialize()
    await tushare_manager.initialize()
    db = mongo_manager.db

    # 1. 找出所有 turnover_rate=100.0 的交易日
    bad_dates = await db.stock_daily_ak_full.distinct('trade_date', {'turnover_rate': 100.0})
    bad_dates.sort()
    print(f"需要修复的交易日: {len(bad_dates)} 个 ({bad_dates[0]} ~ {bad_dates[-1]})")

    total_fixed = 0
    start_time = time.time()

    for i, trade_date in enumerate(bad_dates):
        try:
            # 2. 从 Tushare 获取当日全市场 daily_basic
            records = await tushare_manager.get_daily_basic(trade_date=trade_date)
            
            if not records:
                print(f"  [{i+1}/{len(bad_dates)}] {trade_date}: Tushare 无数据，跳过")
                continue

            # 3. 构建 ts_code -> {turnover_rate, circ_mv, total_mv} 映射
            update_map = {}
            for r in records:
                ts_code = r.get('ts_code')
                if ts_code:
                    update_map[ts_code] = {
                        'turnover_rate': r.get('turnover_rate'),  # Tushare 返回百分比如 3.13
                        'circ_mv': r.get('circ_mv'),  # 单位：万元
                        'total_mv': r.get('total_mv'),  # 单位：万元
                    }

            # 4. 批量更新 stock_daily_ak_full
            bulk_ops = []
            for ts_code, fields in update_map.items():
                update_fields = {}
                if fields['turnover_rate'] is not None:
                    update_fields['turnover_rate'] = float(fields['turnover_rate'])
                if fields['circ_mv'] is not None:
                    update_fields['circ_mv'] = float(fields['circ_mv'])
                if fields['total_mv'] is not None:
                    update_fields['total_mv'] = float(fields['total_mv'])
                
                if update_fields:
                    bulk_ops.append({
                        'updateOne': {
                            'filter': {'ts_code': ts_code, 'trade_date': trade_date},
                            'update': {'$set': update_fields}
                        }
                    })

            if bulk_ops:
                result = await db.stock_daily_ak_full.bulk_write(bulk_ops)
                fixed = result.modified_count
                total_fixed += fixed
                print(f"  [{i+1}/{len(bad_dates)}] {trade_date}: {len(update_map)} 只股票, 修改 {fixed} 条")
            else:
                print(f"  [{i+1}/{len(bad_dates)}] {trade_date}: 无有效更新")

            # 同时存入 daily_basic 集合（upsert）
            if records:
                daily_basic_ops = []
                for r in records:
                    r['trade_date'] = str(r.get('trade_date', trade_date))
                    key = f"{r.get('ts_code', '')}_{r['trade_date']}"
                    r['_id'] = key
                    daily_basic_ops.append({
                        'replaceOne': {
                            'filter': {'_id': key},
                            'replacement': r,
                            'upsert': True
                        }
                    })
                if daily_basic_ops:
                    await db.daily_basic.bulk_write(daily_basic_ops)

            # Tushare 频率控制
            await asyncio.sleep(0.3)

        except Exception as e:
            print(f"  [{i+1}/{len(bad_dates)}] {trade_date}: 错误 {e}")
            await asyncio.sleep(1)

    elapsed = time.time() - start_time
    print(f"\n修复完成! 共修改 {total_fixed} 条记录, 耗时 {elapsed:.1f}s")

    # 5. 验证
    remaining_bad = await db.stock_daily_ak_full.count_documents({'turnover_rate': 100.0})
    total = await db.stock_daily_ak_full.count_documents({})
    print(f"剩余 turnover_rate=100.0: {remaining_bad}/{total}")
    
    # 随机抽样验证
    sample = await db.stock_daily_ak_full.find_one({'trade_date': bad_dates[-1]})
    if sample:
        print(f"抽样验证 ({sample['ts_code']} {sample['trade_date']}): turnover_rate={sample.get('turnover_rate')}, circ_mv={sample.get('circ_mv')}")


if __name__ == "__main__":
    asyncio.run(fix())
