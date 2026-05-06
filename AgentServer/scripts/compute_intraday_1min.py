"""
从量脉1分钟K线计算盘中因子，写入stock_daily_ak_full

只处理涨停/跌停候选股票(is_limit_up=1 或 is_limit_down=1)，每只股票间隔1秒避免限流。
"""
import asyncio, sys, time
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.data_fetchers.liangmai_client import LiangMaiClient
from core.managers.mongo_manager import mongo_manager
from core.constants import C
from pymongo import UpdateOne

API_INTERVAL = 1.0  # 秒/请求，留余量避免120/min限制

def get_limit_thresholds(ts_code):
    prefix = ts_code[:3] if len(ts_code) >= 3 else ''
    if prefix.startswith(('300', '301')) or prefix == '688': return 0.20, -0.20
    elif prefix.startswith(('8', '4')): return 0.30, -0.30
    else: return 0.10, -0.10

def compute_intraday_factors(bars, pre_close, ts_code):
    if not bars or pre_close <= 0:
        return {}
    
    up_thresh, down_thresh = get_limit_thresholds(ts_code)
    limit_up_price = round(pre_close * (1 + up_thresh), 2)
    limit_down_price = round(pre_close * (1 + down_thresh), 2)
    
    opening_pct_chg = 0
    limit_up_time = 0
    limit_up_open_count = 0
    limit_up_open_amount = 0
    limit_up_open_duration = 0
    limit_down_open_amount = 0
    rise_after_limit_down = 0
    
    was_at_limit_up = False
    was_at_limit_down = False
    last_open_start = None
    
    for i, bar in enumerate(bars):
        t_str = bar.get('t', '')
        o = bar.get('o', 0)
        h = bar.get('h', 0)
        l = bar.get('l', 0)
        c = bar.get('c', 0)
        v = bar.get('v', 0)
        amount = bar.get('a', 0)
        
        # Parse time
        try:
            if ' ' in t_str:
                time_part = t_str.split(' ')[1]
            else:
                time_part = ''
            parts = time_part.split(':')
            minute_num = int(parts[0]) * 100 + int(parts[1])
        except:
            minute_num = 0
        
        # Opening pct chg (first bar ≈ 9:30)
        if i == 0:
            opening_pct_chg = round((o - pre_close) / pre_close * 100, 2)
        
        # 涨停检测 (0.3% tolerance)
        near = 0.003
        at_limit_up = h >= limit_up_price * (1 - near)
        sealed_up = c >= limit_up_price * (1 - near)
        
        if at_limit_up and limit_up_time == 0:
            limit_up_time = minute_num
        
        if at_limit_up and not was_at_limit_up:
            was_at_limit_up = True
            if last_open_start is not None:
                open_dur = minute_num - last_open_start
                limit_up_open_duration = max(limit_up_open_duration, open_dur)
                last_open_start = None
        
        if was_at_limit_up and not sealed_up and c < limit_up_price * (1 - near):
            limit_up_open_count += 1
            was_at_limit_up = False
            last_open_start = minute_num
            limit_up_open_amount += amount / 10000  # 元→万元... wait, amount单位?
            # amount from liangmai is in 元
            # But stock_daily_ak_full amount is 千元
            # Let's store in 千元 to match DB convention
            limit_up_open_amount += amount / 1000  # 元→千元
        
        # 跌停检测
        at_limit_down = l <= limit_down_price * (1 + near)
        sealed_down = c <= limit_down_price * (1 + near)
        
        if was_at_limit_down and not at_limit_down:
            # 翘板成功
            limit_down_open_amount += amount / 1000  # 元→千元
            rise_after_limit_down = round((c - limit_down_price) / limit_down_price * 100, 2)
            was_at_limit_down = False
        
        if at_limit_down:
            was_at_limit_down = True
    
    # 如果最终封涨停，封单金额用最后几根bar的成交额
    if was_at_limit_up and limit_up_open_amount == 0:
        # 封单金额≈最后5根bar的成交额
        last_bars = bars[-5:] if len(bars) >= 5 else bars[-1:]
        limit_up_open_amount = sum(b.get('a', 0) for b in last_bars) / 1000
    
    return {
        'opening_pct_chg': opening_pct_chg,
        'limit_up_time': limit_up_time,
        'limit_up_open_count': limit_up_open_count,
        'limit_up_open_amount': round(limit_up_open_amount, 2),
        'limit_up_open_duration': limit_up_open_duration,
        'limit_down_open_amount': round(limit_down_open_amount, 2),
        'rise_after_limit_down': rise_after_limit_down,
    }


async def main():
    await mongo_manager.initialize()
    db = mongo_manager.db
    coll = db[C.STOCK_DAILY]
    
    token = 'ebacbad6d64444cd037ac5504b63f25d'
    client = LiangMaiClient(token=token)
    
    # Get all trade dates
    dates = sorted(await coll.distinct('trade_date', {'trade_date': {'$gte': 20260105, '$lte': 20260320}}))
    print(f"Trade dates: {len(dates)}")
    
    total_updated = 0
    total_errors = 0
    t_start = time.time()
    
    for date_idx, trade_date in enumerate(dates):
        date_str = str(trade_date)
        
        # Only process limit-up/down candidates
        candidates = await coll.find({
            'trade_date': trade_date,
            '$or': [
                {'is_limit_up': {'$gt': 0}},
                {'is_limit_down': {'$gt': 0}},
                {'pct_chg': {'$gte': 9.0}},
                {'pct_chg': {'$lte': -9.0}},
            ]
        }, {'ts_code': 1, 'pre_close': 1, 'pct_chg': 1, '_id': 1}).to_list(None)
        
        if not candidates:
            continue
        
        updates = []
        for doc in candidates:
            ts_code = doc['ts_code']
            lm_code = ts_code.split('.')[0]
            pre_close = doc.get('pre_close', 0)
            
            if pre_close <= 0:
                # Get from previous day
                prev = await coll.find_one({
                    'ts_code': ts_code, 'trade_date': {'$lt': trade_date}
                }, {'close': 1}, sort=[('trade_date', -1)])
                if prev:
                    pre_close = prev.get('close', 0)
            
            if pre_close <= 0:
                continue
            
            try:
                bars = await client.get_kline(lm_code, klt='1', beg=date_str, end=date_str, lt=240)
                await asyncio.sleep(API_INTERVAL)
                
                if not bars:
                    continue
                
                factors = compute_intraday_factors(bars, pre_close, ts_code)
                if factors:
                    updates.append(UpdateOne(
                        {'_id': doc['_id']},
                        {'$set': factors}
                    ))
                    
            except Exception as e:
                total_errors += 1
                err_str = str(e)
                if '4291' in err_str or 'IP' in err_str:
                    print(f"\n  ⚠️ IP limited at {ts_code}, waiting 60s...")
                    await asyncio.sleep(60)
                    # Retry once
                    try:
                        bars = await client.get_kline(lm_code, klt='1', beg=date_str, end=date_str, lt=240)
                        await asyncio.sleep(API_INTERVAL)
                        if bars:
                            factors = compute_intraday_factors(bars, pre_close, ts_code)
                            if factors:
                                updates.append(UpdateOne({'_id': doc['_id']}, {'$set': factors}))
                    except:
                        pass
                elif total_errors <= 3:
                    print(f"\n  Error {ts_code}: {err_str[:80]}")
                await asyncio.sleep(2)
        
        if updates:
            result = await coll.bulk_write(updates, ordered=False)
            total_updated += result.modified_count
        
        elapsed = time.time() - t_start
        print(f"  {date_str}: {len(candidates)} cand, {len(updates)} updated | total={total_updated}, errors={total_errors}, {elapsed:.0f}s")
    
    await client.close()
    
    elapsed = time.time() - t_start
    print(f"\n✅ Done! Updated: {total_updated}, Errors: {total_errors}, Time: {elapsed:.0f}s")

asyncio.run(main())
