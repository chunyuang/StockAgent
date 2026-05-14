"""检查limit_down相关数据"""
import asyncio, sys, os, types

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

async def check_limit_down_data():
    """检查跌停相关数据"""
    await mongo_manager.initialize()
    
    print('📊 检查跌停相关因子数据')
    print('=' * 60)
    
    # 检查limit_down_open_amount
    cursor = mongo_manager.db['stock_daily_ak_full'].find(
        {"limit_down_open_amount": {"$exists": True}},
        {"ts_code": 1, "limit_down_open_amount": 1, "trade_date": 1, "_id": 0}
    ).limit(10)
    
    records = await cursor.to_list(length=10)
    
    print('1. limit_down_open_amount 样本:')
    if records:
        for r in records:
            amount = r.get('limit_down_open_amount', 0)
            print(f'  {r.get("ts_code")} ({r.get("trade_date")}): {amount}')
    else:
        print('  ❌ 无记录')
    
    # 检查rise_after_limit_down不为0的记录
    cursor = mongo_manager.db['stock_daily_ak_full'].find(
        {"rise_after_limit_down": {"$ne": 0}},
        {"ts_code": 1, "rise_after_limit_down": 1, "trade_date": 1, "_id": 0}
    ).limit(5)
    
    records = await cursor.to_list(length=5)
    
    print('\n2. rise_after_limit_down 非零记录:')
    if records:
        for r in records:
            value = r.get('rise_after_limit_down', 0)
            print(f'  {r.get("ts_code")} ({r.get("trade_date")}): {value}')
    else:
        print('  ✅ 无记录（可能跌停开板股票很少）')
    
    # 统计跌停数量
    pipeline = [
        {"$match": {"trade_date": "20260105"}},
        {"$group": {
            "_id": "$trade_date",
            "total_stocks": {"$sum": 1},
            "limit_down_count": {"$sum": {"$cond": [{"$lte": ["$pct_chg", -9.8]}, 1, 0]}}
        }}
    ]
    
    result = await mongo_manager.db['stock_daily_ak_full'].aggregate(pipeline).to_list(length=1)
    
    if result:
        stats = result[0]
        print(f'\n3. 20260105 跌停统计:')
        print(f'   总股票数: {stats.get("total_stocks", 0)}')
        print(f'   跌停数量: {stats.get("limit_down_count", 0)}')
        print(f'   跌停比例: {stats.get("limit_down_count", 0)/stats.get("total_stocks", 1)*100:.2f}%')

async def main():
    await mongo_manager.initialize()
    await check_limit_down_data()

if __name__ == "__main__":
    asyncio.run(main())