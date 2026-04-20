
import asyncio
import sys
sys.path.append('/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import mongo_manager

async def main():
    print("===== MongoDB 数据统计 =====")
    # 初始化MongoManager
    await mongo_manager.initialize()
    
    # 1. 查询所有集合
    collections = await mongo_manager.db.list_collection_names()
    print(f"\n📚 现有集合: {collections}")
    
    # 2. 查询每个集合的文档数量
    for coll in collections:
        count = await mongo_manager.count(coll, {})
        print(f"  {coll}: {count} 条记录")
    
    # 3. 查询stock_daily_ak_full集合的日期范围
    if 'stock_daily_ak_full' in collections:
        # 最小日期
        min_date = await mongo_manager.find_one(
            'stock_daily_ak_full',
            {},
            sort=[('trade_date', 1)]
        )
        # 最大日期
        max_date = await mongo_manager.find_one(
            'stock_daily_ak_full',
            {},
            sort=[('trade_date', -1)]
        )
        print("\n📈 stock_daily_ak_full 日期范围:")
        if min_date:
            print(f"  最早日期: {min_date.get('trade_date', 'N/A')}")
        if max_date:
            print(f"  最新日期: {max_date.get('trade_date', 'N/A')}")
    
    # 4. 查询limit_list集合的日期范围
    if 'limit_list' in collections:
        min_limit_date = await mongo_manager.find_one(
            'limit_list',
            {},
            sort=[('trade_date', 1)]
        )
        max_limit_date = await mongo_manager.find_one(
            'limit_list',
            {},
            sort=[('trade_date', -1)]
        )
        print("\n📉 limit_list (涨跌停数据) 日期范围:")
        if min_limit_date:
            print(f"  最早日期: {min_limit_date.get('trade_date', 'N/A')}")
        if max_limit_date:
            print(f"  最新日期: {max_limit_date.get('trade_date', 'N/A')}")
    
    # 5. 查询trade_cal交易日历范围
    if 'trade_cal' in collections:
        min_cal_date = await mongo_manager.find_one(
            'trade_cal',
            {},
            sort=[('cal_date', 1)]
        )
        max_cal_date = await mongo_manager.find_one(
            'trade_cal',
            {},
            sort=[('cal_date', -1)]
        )
        print("\n📆 trade_cal (交易日历) 日期范围:")
        if min_cal_date:
            print(f"  最早日期: {min_cal_date.get('cal_date', 'N/A')}")
        if max_cal_date:
            print(f"  最新日期: {max_cal_date.get('cal_date', 'N/A')}")
    
    # 6. 查询backtest_tasks任务数量
    if 'backtest_tasks' in collections:
        task_count = await mongo_manager.count('backtest_tasks', {})
        print(f"\n📝 backtest_tasks (回测任务): {task_count} 个任务")
    
    print("\n✅ 数据查询完成！")

if __name__ == "__main__":
    asyncio.run(main())
