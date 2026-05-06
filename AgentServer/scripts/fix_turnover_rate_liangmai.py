#!/usr/bin/env python3
"""
用量脉全市场行情修复stock_daily_ak_full的turnover_rate和circ_mv
方案：获取量脉实时行情(含lt流通市值+hs换手率)，用当前流通市值反算历史换手率
反算公式：turnover_rate = amount(元) / circ_mv(元) * 100
         circ_mv用今天的流通市值近似（对于短期回测可接受）

注意：market_realtime_all_network 限制1次/分钟
"""
import asyncio, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pymongo import UpdateOne
from core.managers import mongo_manager
from core.data_fetchers.liangmai_client import LiangMaiClient

TOKEN = os.environ.get("LIANGMAI_TOKEN", "ebacbad6d64444cd037ac5504b63f25d")

async def fix():
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    # 1. 获取量脉全市场实时行情
    print("获取量脉全市场行情...")
    client = LiangMaiClient(token=TOKEN)
    await client.initialize()
    
    # market_realtime_all_network 限1次/分，需要等
    for attempt in range(5):
        try:
            data = await client.request('market_realtime_all_network')
            break
        except ValueError as e:
            if '5429' in str(e):
                wait = 65 * (attempt + 1)
                print(f"  频率限制，等待{wait}秒... (attempt {attempt+1})")
                await asyncio.sleep(wait)
            else:
                raise
    else:
        print("无法获取量脉数据，退出")
        return
    
    await client.close()
    print(f"获取到 {len(data)} 只股票实时行情")
    
    # 2. 构建ts_code -> {circ_mv(元), turnover_rate(当前)} 映射
    circ_mv_map = {}  # ts_code -> circ_mv in 元
    current_tr_map = {}  # ts_code -> current turnover_rate
    
    for r in data:
        dm = r.get('dm', '')
        # 量脉代码格式: 000001.SZ
        ts_code = dm if '.' in dm else None
        if not ts_code:
            code = str(dm).zfill(6)
            if code.startswith(('6', '9')):
                ts_code = f"{code}.SH"
            elif code.startswith(('8', '4')):
                ts_code = f"{code}.BJ"
            else:
                ts_code = f"{code}.SZ"
        
        lt = r.get('lt')  # 流通市值(元)
        hs = r.get('hs')  # 换手率(%)
        
        if lt and lt > 0:
            circ_mv_map[ts_code] = float(lt)
        if hs is not None:
            current_tr_map[ts_code] = float(hs)
    
    print(f"有流通市值: {len(circ_mv_map)}, 有换手率: {len(current_tr_map)}")
    
    # 3. 用流通市值反算历史换手率
    # turnover_rate = amount(元) / circ_mv(元) * 100
    # 注意：circ_mv是今天的，历史换手率是近似值（但比100.0好100倍）
    
    bad_dates = await db.stock_daily_ak_full.distinct('trade_date', {'turnover_rate': 100.0})
    bad_dates.sort()
    print(f"需要修复的交易日: {len(bad_dates)}")
    
    total_fixed = 0
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
                # 合理范围检查
                if 0 < tr < 100:
                    ops.append(UpdateOne(
                        {'ts_code': ts_code, 'trade_date': trade_date},
                        {'$set': {
                            'turnover_rate': round(tr, 4),
                            'circ_mv': round(circ_mv / 1e4, 4),  # 元→万元 (与stock_daily_ak_full一致)
                        }}
                    ))
                else:
                    # 异常值，设为0标记
                    ops.append(UpdateOne(
                        {'ts_code': ts_code, 'trade_date': trade_date},
                        {'$set': {'turnover_rate': 0, 'circ_mv': round(circ_mv / 1e4, 4)}}
                    ))
            else:
                # 无流通市值数据，设为0
                ops.append(UpdateOne(
                    {'ts_code': ts_code, 'trade_date': trade_date},
                    {'$set': {'turnover_rate': 0}}
                ))
        
        if ops:
            result = await db.stock_daily_ak_full.bulk_write(ops)
            total_fixed += result.matched_count
        
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(bad_dates)}] fixed={total_fixed} {time.time()-start_time:.0f}s")
    
    print(f"\nDone! fixed={total_fixed} {time.time()-start_time:.0f}s")
    remaining = await db.stock_daily_ak_full.count_documents({'turnover_rate': 100.0})
    zero = await db.stock_daily_ak_full.count_documents({'turnover_rate': 0})
    good = await db.stock_daily_ak_full.count_documents({'turnover_rate': {'$gt': 0, '$lt': 99.9}})
    print(f"Bad(100.0): {remaining}, Zero(0): {zero}, Good: {good}")

if __name__ == "__main__":
    asyncio.run(fix())
