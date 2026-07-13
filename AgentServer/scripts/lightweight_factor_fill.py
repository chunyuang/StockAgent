#!/usr/bin/env python3
"""
轻量因子补算 - 补全最近缺失的所有因子
避免全量加载导致OOM，分批处理

用法: python3 scripts/lightweight_factor_fill.py
"""
import asyncio
import sys, functools
import os
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pymongo import UpdateOne
from core.managers import mongo_manager


async def fill_simple_factors(trade_dates: list[int]):
    """从daily_basic同步turnover_rate/volume_ratio/circ_mv/pe_ttm/pb到stock_daily_ak_full"""
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    for td in trade_dates:
        t0 = time.time()
        
        # Step 1: 从daily_basic同步基础因子
        basic_cursor = db['daily_basic'].find({'trade_date': td}, {
            'ts_code': 1, 'turnover_rate': 1, 'volume_ratio': 1, 'circ_mv': 1, 'total_mv': 1,
            'pe_ttm': 1, 'pb': 1, '_id': 0
        })
        basic_map = {}
        async for doc in basic_cursor:
            basic_map[doc['ts_code']] = doc
        
        # Step 2: 批量更新stock_daily_ak_full
        # 注意: daily_basic的circ_mv/total_mv单位是亿元, stock_daily_ak_full标准是万元
        # 需要×10000转换
        ops = []
        for ts_code, basic in basic_map.items():
            update = {}
            for k in ['turnover_rate', 'volume_ratio', 'pe_ttm', 'pb']:
                if k in basic and basic[k] is not None:
                    try:
                        v = float(basic[k])
                        if v == v:  # 非NaN
                            update[k] = v
                    except (ValueError, TypeError):
                        pass
            # circ_mv/total_mv: 亿元→万元(×10000)
            for k in ['circ_mv', 'total_mv']:
                if k in basic and basic[k] is not None and basic[k] > 0:
                    update[k] = basic[k] * 10000
            if update:
                ops.append(UpdateOne(
                    {'ts_code': ts_code, 'trade_date': td},
                    {'$set': update}
                ))
        
        if ops:
            result = await db['stock_daily_ak_full'].bulk_write(ops)
            print(f"  {td}: synced {result.modified_count} records from daily_basic ({time.time()-t0:.1f}s)")
        else:
            print(f"  {td}: no daily_basic data to sync")
        
        # Step 3: 计算is_limit_up/is_limit_down (基于pct_chg)
        ops2 = []
        cursor = db['stock_daily_ak_full'].find({'trade_date': td}, {
            'ts_code': 1, 'pct_chg': 1, '_id': 0
        })
        async for doc in cursor:
            ts_code = doc['ts_code']
            pct = doc.get('pct_chg', 0) or 0
            
            # 根据板块确定涨跌停阈值
            if ts_code.startswith(('30', '688')):
                limit_up_threshold = 19.5
                limit_down_threshold = -19.5
            elif ts_code.startswith(('8', '4')):
                limit_up_threshold = 29.5
                limit_down_threshold = -29.5
            else:
                limit_up_threshold = 9.5
                limit_down_threshold = -9.5
            
            is_limit_up = 1 if pct >= limit_up_threshold else 0
            is_limit_down = 1 if pct <= limit_down_threshold else 0
            
            ops2.append(UpdateOne(
                {'ts_code': ts_code, 'trade_date': td},
                {'$set': {'is_limit_up': is_limit_up, 'is_limit_down': is_limit_down}}
            ))
        
        if ops2:
            result2 = await db['stock_daily_ak_full'].bulk_write(ops2)
            print(f"  {td}: is_limit_up/down computed for {result2.modified_count} records ({time.time()-t0:.1f}s)")


async def compute_ma(trade_dates: list[int], periods: list[int] = None):
    """计算MA均线 - MA5/MA10/MA20/MA60"""
    if periods is None:
        periods = [5, 10, 20, 60]
    max_period = max(periods)
    
    await mongo_manager.initialize()
    db = mongo_manager.db
    field_names = {p: f'ma{p}' for p in periods}
    
    for td in trade_dates:
        t0 = time.time()
        
        # 获取该日期及前N个交易日的数据(需要max_period天来回溯)
        pipeline = [
            {'$match': {'trade_date': {'$lte': td}}},
            {'$group': {'_id': '$trade_date'}},
            {'$sort': {'_id': -1}},
            {'$limit': max_period + 5}  # 多取几天以防缺失
        ]
        recent_dates = []
        async for doc in db['stock_daily_ak_full'].aggregate(pipeline):
            recent_dates.append(doc['_id'])
        
        if len(recent_dates) < 2:
            print(f"  {td}: not enough historical data for MA")
            continue
        
        recent_dates.sort()
        
        # 加载这些日期的数据
        cursor = db['stock_daily_ak_full'].find(
            {'trade_date': {'$in': recent_dates}},
            {'ts_code': 1, 'trade_date': 1, 'close': 1, '_id': 0}
        )
        
        # 按股票分组
        stock_data = defaultdict(list)
        async for doc in cursor:
            stock_data[doc['ts_code']].append((doc['trade_date'], doc.get('close', 0)))
        
        # 计算各周期MA
        ops = []
        for ts_code, records in stock_data.items():
            records.sort()
            closes = [r[1] for r in records if r[1] and r[1] > 0]
            
            if not closes:
                continue
            
            update = {}
            for p in periods:
                if len(closes) >= p:
                    update[field_names[p]] = round(sum(closes[-p:]) / p, 4)
                elif len(closes) >= 2:
                    # 数据不足时用已有数据近似
                    update[field_names[p]] = round(sum(closes) / len(closes), 4)
            
            if update:
                ops.append(UpdateOne(
                    {'ts_code': ts_code, 'trade_date': td},
                    {'$set': update}
                ))
        
        if ops:
            result = await db['stock_daily_ak_full'].bulk_write(ops)
            ma_fields = '+'.join(field_names.values())
            print(f"  {td}: {ma_fields} computed for {result.modified_count} records ({time.time()-t0:.1f}s)")


async def compute_limit_flags(trade_dates: list[int]):
    """计算涨停/跌停相关衍生因子"""
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    for td in trade_dates:
        t0 = time.time()
        
        # 获取前一个交易日
        pipeline = [
            {'$match': {'trade_date': {'$lt': td}}},
            {'$group': {'_id': '$trade_date'}},
            {'$sort': {'_id': -1}},
            {'$limit': 1}
        ]
        prev_date = None
        async for doc in db['stock_daily_ak_full'].aggregate(pipeline):
            prev_date = doc['_id']
        
        if not prev_date:
            print(f"  {td}: no previous date found")
            continue
        
        # 获取前一天的is_limit_up/is_limit_down
        prev_cursor = db['stock_daily_ak_full'].find(
            {'trade_date': prev_date, 'is_limit_up': 1},
            {'ts_code': 1, '_id': 0}
        )
        prev_limit_up = set()
        async for doc in prev_cursor:
            prev_limit_up.add(doc['ts_code'])
        
        prev_down_cursor = db['stock_daily_ak_full'].find(
            {'trade_date': prev_date, 'is_limit_down': 1},
            {'ts_code': 1, '_id': 0}
        )
        prev_limit_down = set()
        async for doc in prev_down_cursor:
            prev_limit_down.add(doc['ts_code'])
        
        # 【v2.9.110】获取当天的is_limit_up, 用于计算first_limit_up
        cur_limit_up = set()
        async for doc in db['stock_daily_ak_full'].find(
            {'trade_date': td, 'is_limit_up': 1},
            {'ts_code': 1, '_id': 0}
        ):
            cur_limit_up.add(doc['ts_code'])
        
        # 更新当天数据
        ops = []
        cursor = db['stock_daily_ak_full'].find({'trade_date': td}, {'ts_code': 1, '_id': 0})
        async for doc in cursor:
            ts_code = doc['ts_code']
            update = {
                'limit_up_yesterday': 1 if ts_code in prev_limit_up else 0,
                'limit_down_yesterday': 1 if ts_code in prev_limit_down else 0,
                'first_limit_up': 1 if (ts_code in cur_limit_up and ts_code not in prev_limit_up) else 0,
                'hot_sector': 0,
                'market_leader': None,
                'sentiment_score': 0.5,  # 市场级，回测引擎会覆盖
            }
            ops.append(UpdateOne(
                {'ts_code': ts_code, 'trade_date': td},
                {'$set': update}
            ))
        
        if ops:
            result = await db['stock_daily_ak_full'].bulk_write(ops)
            print(f"  {td}: limit flags computed for {result.modified_count} records ({time.time()-t0:.1f}s)")


async def compute_opening_and_intraday(trade_dates: list[int]):
    """计算开盘涨幅、盘中涨幅等衍生因子

    - opening_pct_chg = (open - pre_close) / pre_close * 100
    - intraday_max_rise_pct = (high - pre_close) / pre_close * 100
    - intraday_open_rise_pct = (open - pre_close) / pre_close * 100 (同opening_pct_chg)
    - open_above_limit / open_below_limit / open_above_limit_down
    """
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    for td in trade_dates:
        t0 = time.time()
        cursor = db['stock_daily_ak_full'].find(
            {'trade_date': td, 'open': {'$ne': None}, 'pre_close': {'$ne': None, '$gt': 0}},
            {'ts_code': 1, 'open': 1, 'pre_close': 1, 'high': 1, 'low': 1, 'close': 1, 'pct_chg': 1, '_id': 0}
        )
        
        ops = []
        async for doc in cursor:
            ts_code = doc['ts_code']
            open_p = doc.get('open', 0) or 0
            pre_close = doc.get('pre_close', 0) or 0
            high = doc.get('high', 0) or 0
            low = doc.get('low', 0) or 0
            close_p = doc.get('close', 0) or 0
            
            if pre_close <= 0:
                continue
            
            update = {}
            
            # 开盘涨幅
            if open_p > 0:
                opening_pct = (open_p - pre_close) / pre_close * 100
                update['opening_pct_chg'] = round(opening_pct, 4)
                update['intraday_open_rise_pct'] = round(opening_pct, 4)
            
            # 盘中最高涨幅
            if high > 0:
                max_rise = (high - pre_close) / pre_close * 100
                update['intraday_max_rise_pct'] = round(max_rise, 4)
            
            # 振幅
            if low > 0 and high > 0:
                amplitude = (high - low) / pre_close * 100
                update['amplitude'] = round(amplitude, 4)
            
            # 涨停/跌停开盘标记
            if open_p > 0:
                if ts_code.startswith(('30', '688')):
                    limit_threshold = 19.5
                elif ts_code.startswith(('8', '4')):
                    limit_threshold = 29.5
                else:
                    limit_threshold = 9.5
                
                limit_up_price = pre_close * (1 + limit_threshold / 100)
                limit_down_price = pre_close * (1 - limit_threshold / 100)
                
                update['open_above_limit'] = 1 if open_p >= limit_up_price * 0.995 else 0
                update['open_below_limit'] = 1 if open_p <= limit_down_price * 1.005 else 0
                update['open_above_limit_down'] = 1 if open_p > limit_down_price else 0
            
            # 【v2.9.110新增】盘中涨停标记(最高价触过涨停板, 含炸板)
            # 与is_limit_up的区别: is_limit_up=收盘涨停, intraday_limit_up=盘中触涨停
            if high > 0:
                if ts_code.startswith(('30', '688')):
                    high_limit_pct = 19.5
                elif ts_code.startswith(('8', '4')):
                    high_limit_pct = 29.5
                else:
                    high_limit_pct = 9.5
                max_rise_val = (high - pre_close) / pre_close * 100
                update['intraday_limit_up'] = 1 if max_rise_val >= high_limit_pct else 0
            
            if update:
                ops.append(UpdateOne(
                    {'ts_code': ts_code, 'trade_date': td},
                    {'$set': update}
                ))
        
        if ops:
            result = await db['stock_daily_ak_full'].bulk_write(ops)
            print(f"  {td}: opening+intraday computed for {result.modified_count} records ({time.time()-t0:.1f}s)")


async def compute_limit_up_count(trade_dates: list[int]):
    """计算连板数 limit_up_count - 需要多日回溯"""
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    for td in trade_dates:
        t0 = time.time()
        
        # 获取前10个交易日(最大连板回溯)
        pipeline = [
            {'$match': {'trade_date': {'$lte': td}}},
            {'$group': {'_id': '$trade_date'}},
            {'$sort': {'_id': -1}},
            {'$limit': 11}
        ]
        recent_dates = []
        async for doc in db['stock_daily_ak_full'].aggregate(pipeline):
            recent_dates.append(doc['_id'])
        
        if len(recent_dates) < 2:
            continue
        
        recent_dates.sort()
        
        # 加载这些日期的is_limit_up数据
        cursor = db['stock_daily_ak_full'].find(
            {'trade_date': {'$in': recent_dates}},
            {'ts_code': 1, 'trade_date': 1, 'is_limit_up': 1, '_id': 0}
        )
        
        # 按股票分组，按日期排序
        stock_data = defaultdict(list)
        async for doc in cursor:
            stock_data[doc['ts_code']].append((doc['trade_date'], doc.get('is_limit_up', 0)))
        
        ops = []
        for ts_code, records in stock_data.items():
            records.sort()
            # 找到target_date在records中的位置
            target_idx = None
            for i, (d, _) in enumerate(records):
                if d == td:
                    target_idx = i
                    break
            
            if target_idx is None:
                continue
            
            # 从target_date往前数连续涨停天数
            count = 0
            for i in range(target_idx, -1, -1):
                if records[i][1] == 1:
                    count += 1
                else:
                    break
            
            ops.append(UpdateOne(
                {'ts_code': ts_code, 'trade_date': td},
                {'$set': {'limit_up_count': count, 'limit_down_count': 0}}  # limit_down_count简化为0
            ))
        
        if ops:
            result = await db['stock_daily_ak_full'].bulk_write(ops)
            print(f"  {td}: limit_up_count computed for {result.modified_count} records ({time.time()-t0:.1f}s)")


async def compute_pullback(trade_dates: list[int]):
    """计算回调因子 pullback_pct - 从高点回调百分比"""
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    for td in trade_dates:
        t0 = time.time()
        
        # 获取前5个交易日
        pipeline = [
            {'$match': {'trade_date': {'$lte': td}}},
            {'$group': {'_id': '$trade_date'}},
            {'$sort': {'_id': -1}},
            {'$limit': 6}
        ]
        recent_dates = []
        async for doc in db['stock_daily_ak_full'].aggregate(pipeline):
            recent_dates.append(doc['_id'])
        
        if len(recent_dates) < 2:
            continue
        
        recent_dates.sort()
        
        cursor = db['stock_daily_ak_full'].find(
            {'trade_date': {'$in': recent_dates}},
            {'ts_code': 1, 'trade_date': 1, 'close': 1, 'high': 1, '_id': 0}
        )
        
        stock_data = defaultdict(list)
        async for doc in cursor:
            stock_data[doc['ts_code']].append((doc['trade_date'], doc.get('close', 0), doc.get('high', 0)))
        
        ops = []
        for ts_code, records in stock_data.items():
            records.sort()
            if len(records) < 2:
                continue
            
            # 最近5日最高价
            recent_highs = [r[2] for r in records[-5:] if r[2] and r[2] > 0]
            if not recent_highs:
                continue
            
            max_high = max(recent_highs)
            current_close = records[-1][1]  # 当天收盘价
            
            if max_high > 0 and current_close is not None and current_close > 0:
                pullback_pct = (current_close - max_high) / max_high * 100
                ops.append(UpdateOne(
                    {'ts_code': ts_code, 'trade_date': td},
                    {'$set': {'pullback_pct': round(pullback_pct, 4)}}
                ))
        
        if ops:
            result = await db['stock_daily_ak_full'].bulk_write(ops)
            print(f"  {td}: pullback_pct computed for {result.modified_count} records ({time.time()-t0:.1f}s)")


async def compute_technical_indicators(trade_dates: list[int]):
    """纯Python计算技术指标: MACD/RSI/BOLL/ATR/恐贪指数 (不需要talib)"""
    import numpy as np
    import pandas as pd
    
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    max_lookback = 45
    
    for td in trade_dates:
        t0 = time.time()
        
        pipeline = [
            {'$match': {'trade_date': {'$lte': td}}},
            {'$group': {'_id': '$trade_date'}},
            {'$sort': {'_id': -1}},
            {'$limit': max_lookback + 5}
        ]
        recent_dates = []
        async for doc in db['stock_daily_ak_full'].aggregate(pipeline):
            recent_dates.append(doc['_id'])
        
        if len(recent_dates) < 20:
            print(f"  {td}: not enough lookback data")
            continue
        
        recent_dates.sort()
        
        target_codes = []
        async for doc in db['stock_daily_ak_full'].find({'trade_date': td}, {'ts_code': 1, '_id': 0}):
            target_codes.append(doc['ts_code'])
        
        if not target_codes:
            continue
        
        ops = []
        batch_size = 500
        
        for bi in range(0, len(target_codes), batch_size):
            batch_codes = target_codes[bi:bi+batch_size]
            
            cursor = db['stock_daily_ak_full'].find(
                {'ts_code': {'$in': batch_codes}, 'trade_date': {'$in': recent_dates}},
                {'ts_code': 1, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1,
                 'pct_chg': 1, 'vol': 1, 'pre_close': 1, '_id': 0}
            )
            
            stock_data = defaultdict(list)
            async for doc in cursor:
                stock_data[doc['ts_code']].append(doc)
            
            for ts_code, records in stock_data.items():
                records.sort(key=lambda x: x['trade_date'])
                
                closes = np.array([r.get('close', 0) or 0 for r in records], dtype=float)
                highs = np.array([r.get('high', 0) or 0 for r in records], dtype=float)
                lows = np.array([r.get('low', 0) or 0 for r in records], dtype=float)
                pct_chgs = np.array([r.get('pct_chg', 0) or 0 for r in records], dtype=float)
                
                valid = closes > 0
                if valid.sum() < 20:
                    continue
                
                update = {}
                
                # EMA12/EMA26/MACD
                ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
                ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
                dif = ema12 - ema26
                dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
                macd_hist = (dif - dea) * 2
                if not np.isnan(dif[-1]): update['macd'] = round(float(dif[-1]), 4)
                if not np.isnan(dea[-1]): update['macd_signal'] = round(float(dea[-1]), 4)
                if not np.isnan(macd_hist[-1]): update['macd_hist'] = round(float(macd_hist[-1]), 4)
                
                # RSI
                for period, field in [(6, 'rsi_6'), (12, 'rsi_12'), (24, 'rsi_24')]:
                    delta = np.diff(closes, prepend=closes[0])
                    gain = np.where(delta > 0, delta, 0.0)
                    loss = np.where(delta < 0, -delta, 0.0)
                    avg_gain = pd.Series(gain).ewm(alpha=1.0/period, min_periods=period).mean().values
                    avg_loss = pd.Series(loss).ewm(alpha=1.0/period, min_periods=period).mean().values
                    rs = avg_gain / (avg_loss + 1e-10)
                    rsi_vals = 100 - 100 / (1 + rs)
                    if not np.isnan(rsi_vals[-1]): update[field] = round(float(rsi_vals[-1]), 4)
                
                # Bollinger Bands
                ma20_s = pd.Series(closes).rolling(20).mean().values
                std20_s = pd.Series(closes).rolling(20).std().values
                if not np.isnan(ma20_s[-1]):
                    update['boll_upper'] = round(float(ma20_s[-1] + 2 * std20_s[-1]), 4)
                    update['boll_mid'] = round(float(ma20_s[-1]), 4)
                    update['boll_lower'] = round(float(ma20_s[-1] - 2 * std20_s[-1]), 4)
                
                # ATR
                prev_closes = np.roll(closes, 1); prev_closes[0] = closes[0]
                tr1 = highs - lows
                tr2 = np.abs(highs - prev_closes)
                tr3 = np.abs(lows - prev_closes)
                tr = np.maximum(tr1, np.maximum(tr2, tr3))
                atr_val = pd.Series(tr).rolling(14).mean().values
                if not np.isnan(atr_val[-1]):
                    update['atr'] = round(float(atr_val[-1]), 4)
                    if closes[-1] > 0: update['natr'] = round(float(atr_val[-1] / closes[-1] * 100), 4)
                update['trange'] = round(float(tr[-1]), 4)
                
                # 恐贪指数
                if update.get('rsi_12') is not None:
                    rsi_norm = (update['rsi_12'] - 50) / 50
                    update['fear_greed_index'] = round(rsi_norm * 2.5 + 5, 4)
                
                # 动量
                if len(closes) >= 2: update['momentum_1d'] = round(float(closes[-1]/closes[-2]-1), 6)
                if len(closes) >= 5: update['momentum_5d'] = round(float(closes[-1]/closes[-5]-1), 6)
                if len(closes) >= 10: update['momentum_10d'] = round(float(closes[-1]/closes[-10]-1), 6)
                if len(closes) >= 20: update['momentum_20d'] = round(float(closes[-1]/closes[-20]-1), 6)
                
                # 波动率
                if len(pct_chgs) >= 5: update['volatility_5d'] = round(float(np.std(pct_chgs[-5:])), 6)
                if len(pct_chgs) >= 10: update['volatility_10d'] = round(float(np.std(pct_chgs[-10:])), 6)
                if len(pct_chgs) >= 20: update['volatility_20d'] = round(float(np.std(pct_chgs[-20:])), 6)
                
                # 清理NaN
                update = {k: v for k, v in update.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}
                
                if update:
                    ops.append(UpdateOne({'ts_code': ts_code, 'trade_date': td}, {'$set': update}))
                
                if len(ops) >= 2000:
                    await db['stock_daily_ak_full'].bulk_write(ops)
                    ops = []
        
        if ops:
            await db['stock_daily_ak_full'].bulk_write(ops)
        
        print(f"  {td}: technical indicators computed ({time.time()-t0:.1f}s)")

async def detect_missing_dates(db, lookback_days: int = 30) -> list[int]:
    """检测最近N天中缺因子的日期 - 检查所有关键因子"""
    all_dates = await db['stock_daily_ak_full'].distinct('trade_date')
    if not all_dates:
        return []
    
    all_dates_sorted = sorted(all_dates, reverse=True)
    recent_dates = all_dates_sorted[:lookback_days]
    
    # 关键因子：任一缺失率>10%则该日期需补
    # 包含技术指标(MACD/RSI/BOLL/ATR/fear_greed_index) - 现由lightweight_factor_fill补算
    key_factors = [
        'ma5', 'ma10', 'ma20', 'ma60',
        'turnover_rate', 'volume_ratio', 'circ_mv',
        'is_limit_up', 'is_limit_down',
        'opening_pct_chg', 'open_above_limit',
        'intraday_max_rise_pct', 'intraday_open_rise_pct',
        'limit_up_count',
        'macd', 'rsi_6', 'boll_upper', 'atr', 'fear_greed_index',
    ]
    
    trade_dates = []
    for td in sorted(recent_dates):
        total = await db['stock_daily_ak_full'].count_documents({'trade_date': td})
        if total == 0:
            continue
        
        # 检查关键因子覆盖率
        has_missing = False
        for factor in key_factors:
            with_factor = await db['stock_daily_ak_full'].count_documents({
                'trade_date': td,
                factor: {'$ne': None, '$exists': True} if factor not in ('is_limit_up', 'is_limit_down', 'open_above_limit') else {'$ne': None, '$exists': True}
            })
            rate = with_factor / total if total > 0 else 0
            if rate < 0.9:
                has_missing = True
                break
        
        if has_missing:
            trade_dates.append(td)
    
    return trade_dates


async def main():
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    # 【v2.9.110】清理close=None的空壳记录(退市/停牌票被采补脚本误写入)
    shell_count = 0
    async for doc in db['stock_daily_ak_full'].find({'close': None}, {'trade_date': 1, '_id': 0}):
        shell_count += 1
    if shell_count > 0:
        result = await db['stock_daily_ak_full'].delete_many({'close': None})
        print(f'🧹 清理空壳记录: {result.deleted_count}条 (close=None)')
    
    # 【v2.9.110】清理daily_basic中close=None的空壳记录
    basic_shell = await db['daily_basic'].count_documents({'close': None})
    if basic_shell > 0:
        result = await db['daily_basic'].delete_many({'close': None})
        print(f'🧹 清理daily_basic空壳: {result.deleted_count}条 (close=None)')
    
    # 使用增强的检测逻辑
    trade_dates = await detect_missing_dates(db, lookback_days=30)
    
    if not trade_dates:
        print('所有日期的因子已完整，无需补算')
        return
    
    print(f'需补算因子的日期({len(trade_dates)}天): {trade_dates[:5]}{"..." if len(trade_dates) > 5 else ""}')
    
    print("\n=== Step 1: Sync basic factors from daily_basic ===")
    await fill_simple_factors(trade_dates)
    
    print("\n=== Step 2: Compute MA5/MA10/MA20/MA60 ===")
    await compute_ma(trade_dates, periods=[5, 10, 20, 60])
    
    print("\n=== Step 3: Compute limit flags ===")
    await compute_limit_flags(trade_dates)
    
    print("\n=== Step 4: Compute opening_pct_chg + intraday_max/open_rise_pct ===")
    await compute_opening_and_intraday(trade_dates)
    
    print("\n=== Step 5: Compute limit_up_count (连板数) ===")
    await compute_limit_up_count(trade_dates)
    
    print("\n=== Step 6: Compute pullback_pct ===")
    await compute_pullback(trade_dates)
    
    print("\n=== Step 7: Compute technical indicators (MACD/RSI/BOLL/ATR/FearGreed/Momentum/Vol) ===")
    # 【v2.9.110】分批执行避免OOM: 每次3天, 间隔GC
    import gc
    batch_size = 3
    for i in range(0, len(trade_dates), batch_size):
        batch = trade_dates[i:i+batch_size]
        await compute_technical_indicators(batch)
        gc.collect()
        if i + batch_size < len(trade_dates):
            print(f"  [batch {i//batch_size+1}/{(len(trade_dates)+batch_size-1)//batch_size}] 已完成{len(batch)}天, GC后继续...")
    
    # Verify
    print("\n=== Verification ===")
    for td in trade_dates[-3:]:  # 只验证最近3天
        sample = await db['stock_daily_ak_full'].find_one(
            {'trade_date': td},
            {'ts_code': 1, 'ma5': 1, 'ma10': 1, 'macd': 1, 'rsi_6': 1, 'boll_upper': 1, 'atr': 1,
             'turnover_rate': 1, 'is_limit_up': 1, 'opening_pct_chg': 1, 'open_above_limit': 1,
             'intraday_max_rise_pct': 1, 'limit_up_count': 1, 'pullback_pct': 1, 'fear_greed_index': 1, '_id': 0}
        )
        if sample:
            print(f"  {td}: {sample}")
        else:
            print(f"  {td}: NO DATA")


if __name__ == '__main__':
    asyncio.run(main())
