from pathlib import Path
"""
从量脉1分钟K线计算盘中因子，写入stock_daily_ak_full

计算因子:
- opening_pct_chg: 竞价涨幅(9:25 close vs pre_close)
- limit_up_time: 首次涨停时间(分钟数,如925=09:25)
- limit_up_open_count: 开板次数
- limit_up_open_amount: 封单金额(万元,近似)
- limit_up_open_duration: 最后一次开板时长(分钟)
- limit_down_open_amount: 翘板金额(万元,近似)
- rise_after_limit_down: 翘板后涨幅(%)
- limit_down_yesterday: 昨日跌停
- open_above_limit_down: 开盘高于跌停价
"""
import asyncio, sys, time
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.data_fetchers.liangmai_client import LiangMaiClient
from core.managers.mongo_manager import mongo_manager
from core.constants import C
from pymongo import UpdateOne

# 量脉限流: 120次/分
API_INTERVAL = 0.55  # 秒/请求

def get_limit_thresholds(ts_code):
    """根据股票代码返回涨跌停阈值"""
    prefix = ts_code[:3] if len(ts_code) >= 3 else ''
    suffix = ts_code[-2:] if len(ts_code) >= 2 else ''
    if prefix.startswith(('300', '301')) or (prefix == '688'):
        return 0.20, -0.20  # 创业板/科创板
    elif prefix.startswith(('8', '4')):
        return 0.30, -0.30  # 北交所
    else:
        return 0.10, -0.10  # 主板

def compute_intraday_factors(bars, pre_close, ts_code):
    """从1分钟K线计算盘中因子"""
    if not bars or pre_close <= 0:
        return {}
    
    up_thresh, down_thresh = get_limit_thresholds(ts_code)
    limit_up_price = pre_close * (1 + up_thresh)
    limit_down_price = pre_close * (1 + down_thresh)
    
    # 竞价涨幅: 第1根1分钟K线的open(≈9:30) vs pre_close
    # 更精确: 用9:25的close，但1分钟K线从9:30开始，用第1根open近似
    first_bar = bars[0]
    opening_pct_chg = (first_bar['o'] - pre_close) / pre_close * 100
    
    # 涨停时间: 首次触及涨停价的时间
    limit_up_time = 0  # 分钟数(如930=09:30)
    limit_up_open_count = 0  # 开板次数
    was_at_limit = False
    last_open_start = None
    limit_up_open_duration = 0
    limit_up_open_amount = 0  # 封单金额(万元)
    
    # 跌停相关
    was_at_limit_down = False
    limit_down_open_amount = 0
    rise_after_limit_down = 0
    limit_down_hit_time = None
    
    for bar in bars:
        t_str = bar.get('t', '')
        high = bar.get('h', 0)
        low = bar.get('l', 0)
        close = bar.get('c', 0)
        vol = bar.get('v', 0)
        amount = bar.get('a', 0)
        
        # 解析时间 (格式: '2026-03-20 09:30:00' 或类似)
        try:
            if ' ' in t_str:
                time_part = t_str.split(' ')[1]
            else:
                time_part = t_str[8:] if len(t_str) > 8 else ''
            h, m, _ = time_part.split(':')
            minute_num = int(h) * 100 + int(m)
        except:
            minute_num = 0
        
        # 涨停检测
        at_limit_up = high >= limit_up_price * 0.995  # 允许0.5%误差
        
        if at_limit_up and limit_up_time == 0:
            limit_up_time = minute_num
        
        if at_limit_up and not was_at_limit:
            # 首次封涨停或重新封回
            was_at_limit = True
            if last_open_start is not None:
                # 之前开板了，现在封回
                open_duration = minute_num - last_open_start
                limit_up_open_duration = max(limit_up_open_duration, open_duration)
                last_open_start = None
        
        if was_at_limit and not at_limit_up and close < limit_up_price * 0.995:
            # 开板
            limit_up_open_count += 1
            was_at_limit = False
            last_open_start = minute_num
            limit_up_open_amount += amount / 10000  # 元→万元
        
        # 跌停检测
        at_limit_down = low <= limit_down_price * 1.005
        
        if at_limit_down and limit_down_hit_time is None:
            limit_down_hit_time = minute_num
        
        if was_at_limit_down and not at_limit_down:
            # 翘板
            limit_down_open_amount += amount / 10000
            rise_after_limit_down = (close - limit_down_price) / limit_down_price * 100
            was_at_limit_down = False
        
        if at_limit_down:
            was_at_limit_down = True
    
    # 封单金额: 如果最终仍封涨停，用最后一根bar的成交额
    if was_at_limit and limit_up_open_amount == 0:
        limit_up_open_amount = bars[-1].get('a', 0) / 10000
    
    return {
        'opening_pct_chg': round(opening_pct_chg, 2),
        'limit_up_time': limit_up_time,
        'limit_up_open_count': limit_up_open_count,
        'limit_up_open_amount': round(limit_up_open_amount, 2),
        'limit_up_open_duration': limit_up_open_duration,
        'limit_down_open_amount': round(limit_down_open_amount, 2),
        'rise_after_limit_down': round(rise_after_limit_down, 2),
    }


async def main():
    await mongo_manager.initialize()
    db = mongo_manager.db
    coll = db[C.STOCK_DAILY]
    
    token = 'ebacbad6d64444cd037ac5504b63f25d'
    client = LiangMaiClient(token=token)
    
    # Get all trade dates in the backtest range
    dates = sorted(await coll.distinct('trade_date', {'trade_date': {'$gte': 20260105, '$lte': 20260320}}))
    print(f"Trade dates: {len(dates)}, range: {dates[0]}~{dates[-1]}")
    
    total_updated = 0
    total_errors = 0
    
    for date_idx, trade_date in enumerate(dates):
        date_str = str(trade_date)
        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        
        # Get all stocks for this date that are limit_up or limit_down candidates
        # For efficiency, only process stocks with is_limit_up=1 or is_limit_down=1
        # or first_limit_up=1 (these are the ones strategies care about)
        candidates = await coll.find({
            'trade_date': trade_date,
            '$or': [
                {'is_limit_up': 1},
                {'is_limit_down': 1},
                {'first_limit_up': 1},
                {'pct_chg': {'$gte': 9.0}},  # Also near-limit stocks
                {'pct_chg': {'$lte': -9.0}},
            ]
        }, {'ts_code': 1, 'pre_close': 1, 'pct_chg': 1, '_id': 1}).to_list(None)
        
        if not candidates:
            continue
        
        print(f"  {formatted_date}: {len(candidates)} candidates", end='', flush=True)
        
        updates = []
        for doc in candidates:
            ts_code = doc['ts_code']
            # LiangMai uses 6-digit code
            lm_code = ts_code.split('.')[0]
            pre_close = doc.get('pre_close', 0)
            
            if pre_close <= 0:
                # Try to get pre_close from previous day
                prev_doc = await coll.find_one({
                    'ts_code': ts_code,
                    'trade_date': {'$lt': trade_date}
                }, {'close': 1}, sort=[('trade_date', -1)])
                if prev_doc:
                    pre_close = prev_doc.get('close', 0)
            
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
                if total_errors <= 5:
                    print(f"\n    Error {ts_code}: {e}", end='', flush=True)
                await asyncio.sleep(2)  # Back off on error
        
        if updates:
            result = await coll.bulk_write(updates, ordered=False)
            total_updated += result.modified_count
        
        print(f" → {len(updates)} updated", flush=True)
        
        if (date_idx + 1) % 10 == 0:
            print(f"  Progress: {date_idx+1}/{len(dates)} dates, total_updated={total_updated}, errors={total_errors}")
    
    await client.close()
    
    print(f"\n✅ Done! Total updated: {total_updated}, Errors: {total_errors}")
    
    # Verify
    sample = await coll.count_documents({
        'trade_date': dates[-1],
        'opening_pct_chg': {'$exists': True, '$ne': None}
    })
    print(f"Verify {dates[-1]}: stocks with opening_pct_chg: {sample}")

asyncio.run(main())
