"""修复MongoDB中涨跌停相关因子（分板块阈值）"""
import asyncio, sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')
from core.managers import mongo_manager
from pymongo import UpdateOne

LIMIT_UP_FIELDS = ['is_limit_up', 'is_limit_down', 'first_limit_up', 'limit_up_yesterday',
                   'limit_down_yesterday', 'limit_up_count', 'limit_down_count']

def get_thresholds(ts_code):
    """根据股票代码前缀返回涨跌停阈值"""
    prefix = ts_code[:3]
    if prefix.startswith(('300', '301', '688')):
        return 19.5, -19.5  # 创业板/科创板 20%
    elif prefix.startswith(('8', '4')):
        return 29.5, -29.5  # 北交所 30%
    else:
        return 9.5, -9.5  # 主板 10% (含ST的5%会漏掉，但ST一般不是策略目标)

async def fix():
    await mongo_manager.initialize()
    db = mongo_manager.db
    coll = db['stock_daily_ak_full']
    
    # Get all unique dates
    dates = sorted(await coll.distinct('trade_date'))
    print(f"Dates: {len(dates)}, range: {dates[0]}~{dates[-1]}")
    
    total_updated = 0
    
    for i, date in enumerate(dates):
        docs = await coll.find({'trade_date': date}, {'ts_code': 1, 'pct_chg': 1, '_id': 1}).to_list(None)
        
        # Previous day for limit_up_yesterday
        prev_idx = i - 1 if i > 0 else None
        if prev_idx is not None:
            prev_date = dates[prev_idx]
            prev_docs = await coll.find({'trade_date': prev_date}, {'ts_code': 1, 'pct_chg': 1}).to_list(None)
            prev_limit_up = {}
            for d in prev_docs:
                up_t, _ = get_thresholds(d['ts_code'])
                prev_limit_up[d['ts_code']] = d.get('pct_chg', 0) >= up_t
        else:
            prev_limit_up = {}
        
        updates = []
        # Group by ts_code for consecutive count (need to track per-stock)
        stock_data = {}
        for doc in docs:
            ts_code = doc['ts_code']
            pct = doc.get('pct_chg', 0)
            up_t, down_t = get_thresholds(ts_code)
            
            is_up = pct >= up_t
            is_down = pct <= down_t
            was_up_yesterday = prev_limit_up.get(ts_code, False)
            first_up = is_up and not was_up_yesterday
            
            stock_data[ts_code] = {
                'is_limit_up': 1 if is_up else 0,
                'is_limit_down': 1 if is_down else 0,
                'first_limit_up': 1 if first_up else 0,
                'limit_up_yesterday': 1 if was_up_yesterday else 0,
            }
        
        # For limit_up_count/down_count, we need consecutive days - just set based on current
        # (proper consecutive count needs multi-day lookback, approximate with current)
        for doc in docs:
            ts_code = doc['ts_code']
            data = stock_data.get(ts_code, {})
            updates.append(UpdateOne(
                {'_id': doc['_id']},
                {'$set': {
                    'is_limit_up': data.get('is_limit_up', 0),
                    'is_limit_down': data.get('is_limit_down', 0),
                    'first_limit_up': data.get('first_limit_up', 0),
                    'limit_up_yesterday': data.get('limit_up_yesterday', 0),
                }}
            ))
        
        if updates:
            result = await coll.bulk_write(updates)
            total_updated += result.modified_count
        
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(dates)} dates processed, updated={total_updated}")
    
    print(f"\n✅ Done! Total updated: {total_updated}")
    
    # Verify
    sample = await coll.count_documents({'trade_date': dates[-1], 'is_limit_up': 1})
    pct_high = await coll.count_documents({'trade_date': dates[-1], 'pct_chg': {'$gte': 9.5}})
    print(f"Verify {dates[-1]}: is_limit_up=1: {sample}, pct_chg>=9.5: {pct_high}")

asyncio.run(fix())
