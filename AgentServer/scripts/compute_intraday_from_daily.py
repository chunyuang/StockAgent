"""
从日线OHLC推算盘中因子（无需分时数据）

近似方法：
- opening_pct_chg: (open - pre_close) / pre_close * 100
- limit_up_time: 
  - open=涨停价 → 925(竞价封板)
  - close=涨停价且high=涨停价 → 1430(尾盘封板)  
  - high=涨停价且close<涨停价 → 1000(盘中开板,取中间)
  - 其他 → 0(未涨停)
- limit_up_open_count:
  - close=涨停价且high=涨停价 → 0(封死)
  - high=涨停价且close<涨停价 → 1(至少开板1次)
- limit_up_open_amount: amount * (1 - close/limit_up_price) 近似开板时成交
- limit_up_open_duration: close<涨停价时估算60分钟
- limit_down_open_amount: amount * close/limit_down_price 近似翘板时成交
- rise_after_limit_down: (close - limit_down_price) / limit_down_price * 100
"""
import asyncio, sys, time
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers.mongo_manager import mongo_manager
from core.constants import C
from pymongo import UpdateOne


def get_limit_thresholds(ts_code):
    prefix = ts_code[:3] if len(ts_code) >= 3 else ''
    if prefix.startswith(('300', '301')) or prefix == '688':
        return 0.20, -0.20
    elif prefix.startswith(('8', '4')):
        return 0.30, -0.30
    else:
        return 0.10, -0.10


def compute_intraday_from_daily(doc, prev_close):
    """从日线数据推算盘中因子"""
    ts_code = doc.get('ts_code', '')
    open_p = doc.get('open', 0)
    high = doc.get('high', 0)
    low = doc.get('low', 0)
    close = doc.get('close', 0)
    amount = doc.get('amount', 0)  # 千元
    pct_chg = doc.get('pct_chg', 0)
    
    if prev_close <= 0 or close <= 0:
        return {}
    
    up_thresh, down_thresh = get_limit_thresholds(ts_code)
    limit_up_price = round(prev_close * (1 + up_thresh), 2)
    limit_down_price = round(prev_close * (1 + down_thresh), 2)
    
    # 竞价涨幅
    opening_pct_chg = round((open_p - prev_close) / prev_close * 100, 2)
    
    # 涨停相关
    near_limit_up = 0.003  # 0.3%误差
    is_at_limit_up = high >= limit_up_price * (1 - near_limit_up)
    is_sealed = close >= limit_up_price * (1 - near_limit_up)
    
    limit_up_time = 0
    limit_up_open_count = 0
    limit_up_open_amount = 0
    limit_up_open_duration = 0
    
    if is_at_limit_up:
        if is_sealed:
            # 封死涨停
            if abs(open_p - limit_up_price) / limit_up_price < near_limit_up:
                limit_up_time = 925  # 一字板
            else:
                limit_up_time = 1000  # 盘中封板(取中间值)
            limit_up_open_count = 0
            limit_up_open_amount = 0
            limit_up_open_duration = 0
        else:
            # 开板
            # 估算涨停时间：如果open接近涨停→早，否则→盘中
            if abs(open_p - limit_up_price) / limit_up_price < 0.02:
                limit_up_time = 935  # 开盘后很快
            else:
                limit_up_time = 1030  # 盘中
            limit_up_open_count = 1
            # 开板成交额 ≈ 总成交额 × (1 - 收盘价/涨停价)
            if limit_up_price > 0:
                open_ratio = max(0, 1 - close / limit_up_price)
                limit_up_open_amount = round(amount * open_ratio, 2)  # 千元
            limit_up_open_duration = 60  # 近似60分钟
    
    # 跌停相关
    is_at_limit_down = low <= limit_down_price * (1 + near_limit_up)
    is_sealed_down = close <= limit_down_price * (1 + near_limit_up)
    
    limit_down_open_amount = 0
    rise_after_limit_down = 0
    
    if is_at_limit_down and not is_sealed_down:
        # 翘板
        if limit_down_price > 0:
            limit_down_open_amount = round(amount * (close / limit_down_price - 1), 2)  # 千元
            rise_after_limit_down = round((close - limit_down_price) / limit_down_price * 100, 2)
    
    return {
        'opening_pct_chg': opening_pct_chg,
        'limit_up_time': limit_up_time,
        'limit_up_open_count': limit_up_open_count,
        'limit_up_open_amount': limit_up_open_amount,
        'limit_up_open_duration': limit_up_open_duration,
        'limit_down_open_amount': limit_down_open_amount,
        'rise_after_limit_down': rise_after_limit_down,
    }


async def main():
    await mongo_manager.initialize()
    db = mongo_manager.db
    coll = db[C.STOCK_DAILY]
    
    # Get all trade dates
    dates = sorted(await coll.distinct('trade_date', {'trade_date': {'$gte': 20260105, '$lte': 20260320}}))
    print(f"Trade dates: {len(dates)}")
    
    total_updated = 0
    t_start = time.time()
    
    for date_idx, trade_date in enumerate(dates):
        # Get all docs for this date
        docs = await coll.find({'trade_date': trade_date}).to_list(None)
        if not docs:
            continue
        
        # Build prev_close map from previous date
        prev_docs = await coll.find({
            'ts_code': {'$in': [d['ts_code'] for d in docs]},
            'trade_date': {'$lt': trade_date}
        }, {'ts_code': 1, 'close': 1}).sort('trade_date', -1).to_list(None)
        
        prev_close_map = {}
        for pd in prev_docs:
            if pd['ts_code'] not in prev_close_map:
                prev_close_map[pd['ts_code']] = pd.get('close', 0)
        
        updates = []
        for doc in docs:
            prev_close = prev_close_map.get(doc['ts_code'], doc.get('pre_close', 0))
            if prev_close <= 0:
                prev_close = doc.get('pre_close', 0)
            
            factors = compute_intraday_from_daily(doc, prev_close)
            if factors:
                updates.append(UpdateOne(
                    {'_id': doc['_id']},
                    {'$set': factors}
                ))
        
        if updates:
            result = await coll.bulk_write(updates, ordered=False)
            total_updated += result.modified_count
        
        if (date_idx + 1) % 10 == 0:
            elapsed = time.time() - t_start
            print(f"  {date_idx+1}/{len(dates)} dates, updated={total_updated}, {elapsed:.0f}s")
    
    elapsed = time.time() - t_start
    print(f"\n✅ Done! Total updated: {total_updated}, {elapsed:.0f}s")
    
    # Verify
    for check_date in [dates[0], dates[-1]]:
        with_factor = await coll.count_documents({
            'trade_date': check_date,
            'opening_pct_chg': {'$exists': True}
        })
        total = await coll.count_documents({'trade_date': check_date})
        print(f"  {check_date}: {with_factor}/{total} stocks have opening_pct_chg")
        
        # Sample
        sample = await coll.find_one({
            'trade_date': check_date,
            'is_limit_up': 1,
            'opening_pct_chg': {'$exists': True}
        })
        if sample:
            print(f"  Sample limit_up: {sample['ts_code']} opening_pct_chg={sample.get('opening_pct_chg')}, limit_up_time={sample.get('limit_up_time')}, limit_up_open_count={sample.get('limit_up_open_count')}")

asyncio.run(main())
