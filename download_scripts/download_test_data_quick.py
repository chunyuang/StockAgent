#!/usr/bin/env python3
"""
快速下载测试数据：20260105-20260320 范围
只下载回测必需的最少数据
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers import mongo_manager


async def create_mock_trade_cal():
    """创建测试用的交易日历（20260105-20260320）"""
    print("\n" + "="*60)
    print("📅 创建交易日历 (模拟数据)")
    print("="*60)
    
    # 手动创建 2026年1月到3月的交易日（简化：周一到周五都是交易日）
    from datetime import datetime, timedelta
    
    start = datetime(2026, 1, 5)
    end = datetime(2026, 3, 20)
    
    trade_dates = []
    current = start
    prev_date = None
    
    while current <= end:
        # 0=周一, 4=周五
        if current.weekday() < 5:
            trade_date_str = current.strftime("%Y%m%d")
            trade_dates.append({
                "cal_date": int(trade_date_str),
                "is_open": 1,
                "pretrade_date": int(prev_date.strftime("%Y%m%d")) if prev_date else None
            })
            prev_date = current
        current += timedelta(days=1)
    
    # 保存到 MongoDB
    for record in trade_dates:
        await mongo_manager.update_one(
            "trade_cal",
            {"cal_date": record['cal_date']},
            {"$set": record},
            upsert=True
        )
    
    print(f"✅ 交易日历创建完成，共 {len(trade_dates)} 个交易日")
    print(f"   范围: {trade_dates[0]['cal_date']} -> {trade_dates[-1]['cal_date']}")
    return trade_dates


async def create_mock_stock_basic():
    """创建模拟股票基础信息（10只测试股票）"""
    print("\n" + "="*60)
    print("📋 创建股票基础信息 (模拟数据)")
    print("="*60)
    
    stocks = [
        {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行", "list_date": "19910403", "is_st": False},
        {"ts_code": "000002.SZ", "name": "万科A", "industry": "房地产", "list_date": "19910129", "is_st": False},
        {"ts_code": "600519.SH", "name": "贵州茅台", "industry": "白酒", "list_date": "20010827", "is_st": False},
        {"ts_code": "300750.SZ", "name": "宁德时代", "industry": "新能源", "list_date": "20180611", "is_st": False},
        {"ts_code": "601318.SH", "name": "中国平安", "industry": "保险", "list_date": "20070301", "is_st": False},
        {"ts_code": "000858.SZ", "name": "五粮液", "industry": "白酒", "list_date": "19980427", "is_st": False},
        {"ts_code": "600036.SH", "name": "招商银行", "industry": "银行", "list_date": "20020409", "is_st": False},
        {"ts_code": "002594.SZ", "name": "比亚迪", "industry": "汽车", "list_date": "20110630", "is_st": False},
        {"ts_code": "600900.SH", "name": "长江电力", "industry": "电力", "list_date": "20031118", "is_st": False},
        {"ts_code": "601899.SH", "name": "紫金矿业", "industry": "有色", "list_date": "20080425", "is_st": False},
    ]
    
    for stock in stocks:
        await mongo_manager.update_one(
            "stock_basic",
            {"ts_code": stock['ts_code']},
            {"$set": stock},
            upsert=True
        )
    
    print(f"✅ 股票基础信息创建完成，共 {len(stocks)} 只股票")
    return stocks


async def create_mock_daily_data(stocks, trade_dates):
    """创建模拟日线数据"""
    print("\n" + "="*60)
    print("📈 创建日线行情数据 (模拟数据)")
    print("="*60)
    
    import random
    
    base_price = {
        "000001.SZ": 10.5,
        "000002.SZ": 8.2,
        "600519.SH": 1800.0,
        "300750.SZ": 180.0,
        "601318.SH": 45.0,
        "000858.SZ": 150.0,
        "600036.SH": 32.0,
        "002594.SZ": 220.0,
        "600900.SH": 25.0,
        "601899.SH": 12.0,
    }
    
    total_records = 0
    
    for trade_date_info in trade_dates:
        trade_date = trade_date_info['cal_date']
        
        for stock in stocks:
            ts_code = stock['ts_code']
            base = base_price.get(ts_code, 10.0)
            
            # 随机波动 ±3%
            price_change = random.uniform(-0.03, 0.03)
            close = round(base * (1 + price_change), 2)
            open_price = round(close * random.uniform(0.98, 1.02), 2)
            high = round(max(open_price, close) * random.uniform(1.0, 1.02), 2)
            low = round(min(open_price, close) * random.uniform(0.98, 1.0), 2)
            
            pre_close = round(base * random.uniform(0.97, 1.03), 2)
            
            record = {
                "_id": f"{ts_code}_{trade_date}",
                "ts_code": ts_code,
                "trade_date": trade_date,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "pre_close": pre_close,
                "change": round(close - pre_close, 2),
                "pct_chg": round((close - pre_close) / pre_close * 100, 2),
                "vol": random.randint(50000, 500000),
                "amount": random.randint(10000, 100000),
                "up_limit": round(pre_close * 1.1, 2),
                "down_limit": round(pre_close * 0.9, 2),
            }
            
            await mongo_manager.update_one(
                "stock_daily_ak_full",
                {"_id": record['_id']},
                {"$set": record},
                upsert=True
            )
            total_records += 1
    
    print(f"✅ 日线数据创建完成，共 {total_records} 条")


async def create_mock_limit_list(stocks, trade_dates):
    """创建模拟涨跌停数据"""
    print("\n" + "="*60)
    print("📊 创建涨跌停数据 (模拟数据)")
    print("="*60)
    
    import random
    
    total_records = 0
    
    for trade_date_info in trade_dates:
        trade_date = trade_date_info['cal_date']
        
        # 每天随机选 3-5 只股票作为涨停
        num_limit_up = random.randint(3, 5)
        selected_stocks = random.sample(stocks, min(num_limit_up, len(stocks)))
        
        for stock in selected_stocks:
            ts_code = stock['ts_code']
            record = {
                "trade_date": trade_date,
                "ts_code": ts_code,
                "name": stock['name'],
                "limit": "U",
                "close": random.uniform(10, 100),
                "amp": random.uniform(5, 15),
                "fc_ratio": random.uniform(10, 50),
                "first_time": "09:30:00",
                "last_time": "15:00:00",
                "open_times": random.randint(0, 3),
                "limit_times": 1,
            }
            
            await mongo_manager.insert_one("limit_list", record)
            total_records += 1
    
    print(f"✅ 涨跌停数据创建完成，共 {total_records} 条")


async def create_mock_daily_basic(stocks, trade_dates):
    """创建模拟每日基本面数据"""
    print("\n" + "="*60)
    print("💰 创建每日基本面数据 (模拟数据)")
    print("="*60)
    
    import random
    
    total_records = 0
    
    for trade_date_info in trade_dates:
        trade_date = trade_date_info['cal_date']
        
        for stock in stocks:
            ts_code = stock['ts_code']
            
            record = {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "pe": random.uniform(10, 50),
                "pb": random.uniform(1, 5),
                "total_mv": random.uniform(100000, 1000000),
                "circ_mv": random.uniform(80000, 800000),
                "turnover_rate": random.uniform(0.5, 10),
            }
            
            await mongo_manager.update_one(
                "daily_basic",
                {"ts_code": ts_code, "trade_date": trade_date},
                {"$set": record},
                upsert=True
            )
            total_records += 1
    
    print(f"✅ 每日基本面数据创建完成，共 {total_records} 条")


async def main():
    print("\n" + "🚀"*20)
    print("🚀 快速创建回测测试数据 (模拟数据)")
    print("🚀 日期范围: 20260105 -> 20260320")
    print("🚀"*20)
    
    # 1. 创建交易日历
    trade_dates = await create_mock_trade_cal()
    
    # 2. 创建股票基础信息
    stocks = await create_mock_stock_basic()
    
    # 3. 创建日线数据
    await create_mock_daily_data(stocks, trade_dates)
    
    # 4. 创建涨跌停数据
    await create_mock_limit_list(stocks, trade_dates)
    
    # 5. 创建每日基本面
    await create_mock_daily_basic(stocks, trade_dates)
    
    print("\n" + "✅"*30)
    print("✅ 所有测试数据创建完成！")
    print("✅ 现在可以提交回测任务进行测试")
    print("✅"*30)


if __name__ == "__main__":
    asyncio.run(main())
