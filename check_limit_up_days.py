#!/usr/bin/env python3
import asyncio
import sys

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

async def check():
    from core.managers import mongo_manager
    await mongo_manager.initialize()
    
    # 查询所有日期
    dates = await mongo_manager.db.stock_daily_ak.distinct('trade_date')
    dates.sort()
    
    print(f"总交易日: {len(dates)}天")
    print("日期 | 涨停股票数量")
    print("-"*30)
    
    limit_up_count = 0
    for date in dates:
        # 查询当日涨停股票（收盘价 >= 涨停价*0.995，允许微小误差）
        count = await mongo_manager.db.stock_daily_ak.count_documents({
            "trade_date": date,
            "$expr": {"$gte": ["$close", {"$multiply": ["$up_limit", 0.995]}]}
        })
        
        print(f"{date} | {count}只")
        if count > 0:
            limit_up_count += 1
    
    print("-"*30)
    print(f"有涨停股票的交易日: {limit_up_count}天")
    print(f"无涨停股票的交易日: {len(dates) - limit_up_count}天")

if __name__ == "__main__":
    asyncio.run(check())
