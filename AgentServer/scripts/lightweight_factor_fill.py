#!/usr/bin/env python3
"""
轻量因子补算 - 仅补3天缺失的简单因子
避免全量加载导致OOM，分批处理

用法: python3 scripts/lightweight_factor_fill.py
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pymongo import UpdateOne
from core.managers import mongo_manager


async def fill_simple_factors(trade_dates: list[int]):
    """从daily_basic同步turnover_rate/volume_ratio/circ_mv到stock_daily_ak_full"""
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    for td in trade_dates:
        t0 = time.time()
        
        # Step 1: 从daily_basic同步基础因子
        basic_cursor = db['daily_basic'].find({'trade_date': td}, {
            'ts_code': 1, 'turnover_rate': 1, 'volume_ratio': 1, 'circ_mv': 1, 'total_mv': 1, '_id': 0
        })
        basic_map = {}
        async for doc in basic_cursor:
            basic_map[doc['ts_code']] = doc
        
        # Step 2: 批量更新stock_daily_ak_full
        ops = []
        for ts_code, basic in basic_map.items():
            update = {}
            for k in ['turnover_rate', 'volume_ratio', 'circ_mv', 'total_mv']:
                if k in basic and basic[k] is not None:
                    update[k] = basic[k]
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


async def compute_ma5(trade_dates: list[int]):
    """计算MA5 - 需要前5天数据，分批处理"""
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    for td in trade_dates:
        t0 = time.time()
        
        # 获取该日期及前5个交易日的数据
        pipeline = [
            {'$match': {'trade_date': {'$lte': td}}},
            {'$group': {'_id': '$trade_date'}},
            {'$sort': {'_id': -1}},
            {'$limit': 6}  # 当天+前5天
        ]
        recent_dates = []
        async for doc in db['stock_daily_ak_full'].aggregate(pipeline):
            recent_dates.append(doc['_id'])
        
        if len(recent_dates) < 2:
            print(f"  {td}: not enough historical data for MA5")
            continue
        
        recent_dates.sort()
        
        # 加载这些日期的数据
        cursor = db['stock_daily_ak_full'].find(
            {'trade_date': {'$in': recent_dates}},
            {'ts_code': 1, 'trade_date': 1, 'close': 1, '_id': 0}
        )
        
        # 按股票分组
        from collections import defaultdict
        stock_data = defaultdict(list)
        async for doc in cursor:
            stock_data[doc['ts_code']].append((doc['trade_date'], doc.get('close', 0)))
        
        # 计算MA5
        ops = []
        target_date = td
        for ts_code, records in stock_data.items():
            records.sort()
            # 找到target_date在records中的位置
            closes = [r[1] for r in records if r[1] and r[1] > 0]
            if len(closes) >= 5:
                ma5 = sum(closes[-5:]) / 5
            elif len(closes) >= 2:
                ma5 = sum(closes) / len(closes)
            else:
                continue
            
            ops.append(UpdateOne(
                {'ts_code': ts_code, 'trade_date': target_date},
                {'$set': {'ma5': round(ma5, 4)}}
            ))
        
        if ops:
            result = await db['stock_daily_ak_full'].bulk_write(ops)
            print(f"  {td}: MA5 computed for {result.modified_count} records ({time.time()-t0:.1f}s)")


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
        
        # 更新当天数据
        ops = []
        cursor = db['stock_daily_ak_full'].find({'trade_date': td}, {'ts_code': 1, '_id': 0})
        async for doc in cursor:
            ts_code = doc['ts_code']
            update = {
                'limit_up_yesterday': 1 if ts_code in prev_limit_up else 0,
                'limit_down_yesterday': 1 if ts_code in prev_limit_down else 0,
                'first_limit_up': 0,  # 需要盘中数据，日线模式填0
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


async def compute_opening_pct_chg(trade_dates: list[int]):
    """计算开盘涨幅 opening_pct_chg = (open - pre_close) / pre_close * 100"""
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    for td in trade_dates:
        t0 = time.time()
        cursor = db['stock_daily_ak_full'].find(
            {'trade_date': td, 'open': {'$ne': None}, 'pre_close': {'$ne': None, '$gt': 0}},
            {'ts_code': 1, 'open': 1, 'pre_close': 1, 'high': 1, 'low': 1, '_id': 0}
        )
        
        ops = []
        async for doc in cursor:
            ts_code = doc['ts_code']
            open_p = doc.get('open', 0)
            pre_close = doc.get('pre_close', 0)
            high = doc.get('high', 0)
            low = doc.get('low', 0)
            
            if pre_close > 0 and open_p > 0:
                opening_pct = (open_p - pre_close) / pre_close * 100
                
                # 计算其他衍生因子
                update = {'opening_pct_chg': round(opening_pct, 4)}
                
                # open_above_limit: 开盘高于涨停价
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
                
                ops.append(UpdateOne(
                    {'ts_code': ts_code, 'trade_date': td},
                    {'$set': update}
                ))
        
        if ops:
            result = await db['stock_daily_ak_full'].bulk_write(ops)
            print(f"  {td}: opening_pct_chg computed for {result.modified_count} records ({time.time()-t0:.1f}s)")


async def main():
    from pymongo import MongoClient
    db = MongoClient('localhost', 27017)['stock_agent']
    # 自动检测缺因子的日期(有日线但缺turnover_rate/ma5的)
    all_dates = sorted(db['stock_daily_ak_full'].distinct('trade_date'))
    # 只处理最近30天
    recent_dates = [d for d in all_dates if d >= 20260420]
    trade_dates = []
    for td in recent_dates:
        total = db['stock_daily_ak_full'].count_documents({'trade_date': td})
        with_ma5 = db['stock_daily_ak_full'].count_documents({'trade_date': td, 'ma5': {'$gt': 0}})
        if total > 0 and with_ma5 < total * 0.5:
            trade_dates.append(td)
    if not trade_dates:
        print('所有日期的因子已完整，无需补算')
        return
    print(f'需补算因子的日期: {trade_dates}')
    
    print("=== Step 1: Sync basic factors from daily_basic ===")
    await fill_simple_factors(trade_dates)
    
    print("\n=== Step 2: Compute MA5 ===")
    await compute_ma5(trade_dates)
    
    print("\n=== Step 3: Compute limit flags ===")
    await compute_limit_flags(trade_dates)
    
    print("\n=== Step 4: Compute opening_pct_chg ===")
    await compute_opening_pct_chg(trade_dates)
    
    # Verify
    print("\n=== Verification ===")
    await mongo_manager.initialize()
    for td in trade_dates:
        sample = await mongo_manager.db['stock_daily_ak_full'].find_one(
            {'trade_date': td, 'ma5': {'$ne': None}},
            {'ts_code': 1, 'ma5': 1, 'turnover_rate': 1, 'volume_ratio': 1, 'circ_mv': 1,
             'is_limit_up': 1, 'opening_pct_chg': 1, 'limit_up_yesterday': 1, '_id': 0}
        )
        if sample:
            print(f"  {td}: {sample}")
        else:
            print(f"  {td}: STILL NO FACTORS")


if __name__ == '__main__':
    asyncio.run(main())
