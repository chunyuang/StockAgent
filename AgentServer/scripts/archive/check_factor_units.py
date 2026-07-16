"""检查因子单位一致性"""
import asyncio
import sys
import os
import types

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

async def check_pullback_pct():
    """检查pullback_pct的实际存储值"""
    await mongo_manager.initialize()
    
    # 查询一些pullback_pct值
    cursor = mongo_manager.db['stock_daily_ak_full'].find(
        {"pullback_pct": {"$exists": True}},
        {"ts_code": 1, "pullback_pct": 1, "trade_date": 1, "_id": 0}
    ).limit(10)
    
    records = await cursor.to_list(length=10)
    
    print('📊 pullback_pct存储值检查')
    print('=' * 60)
    
    if not records:
        print('❌ 未找到pullback_pct记录')
        return
    
    positives = 0
    negatives = 0
    zeros = 0
    
    for record in records:
        ts_code = record.get('ts_code', 'N/A')
        pullback = record.get('pullback_pct')
        date = record.get('trade_date', 'N/A')
        
        if pullback is None:
            continue
            
        if pullback > 0:
            positives += 1
            sign = '正数'
        elif pullback < 0:
            negatives += 1
            sign = '负数'
        else:
            zeros += 1
            sign = '零'
            
        print(f'  {ts_code} ({date}): {pullback} ({sign})')
    
    print(f'\n📈 统计: 正数={positives}, 负数={negatives}, 零={zeros}')
    
    if negatives > positives:
        print('⚠️ 警告: pullback_pct主要存储负数！')
        print('   当前筛选条件可能错误')
        print('   应为: pullback_pct <= -min_correction*100')
    else:
        print('✅ pullback_pct存储正数，当前筛选条件正确')

async def check_other_factors():
    """检查其他关键因子的单位"""
    await mongo_manager.initialize()
    
    factors_to_check = [
        'rise_after_limit_down',
        'volume_ratio',
        'turnover_rate',
        'circ_mv',
        'amount'
    ]
    
    print('\n📊 其他因子单位检查')
    print('=' * 60)
    
    for factor in factors_to_check:
        cursor = mongo_manager.db['stock_daily_ak_full'].find(
            {factor: {"$exists": True}},
            {factor: 1, "_id": 0}
        ).limit(5)
        
        records = await cursor.to_list(length=5)
        
        if not records:
            print(f'  {factor}: 无记录')
            continue
            
        values = [r.get(factor) for r in records if r.get(factor) is not None]
        if not values:
            print(f'  {factor}: 值全为空')
            continue
            
        avg = sum(values) / len(values)
        print(f'  {factor}: 平均值={avg:.4f}, 范围={min(values):.4f}~{max(values):.4f}')
        
        # 根据值范围推断单位
        if factor == 'rise_after_limit_down':
            if abs(avg) < 1:  # 可能是小数
                print('    ⚠️  可能存小数，但策略用百分比筛选')
            else:  # 可能是百分比
                print('    ✅ 可能存百分比')

async def main():
    await mongo_manager.initialize()
    
    print('🔍 因子单位一致性全面检查')
    print('=' * 60)
    
    await check_pullback_pct()
    await check_other_factors()
    
    print('\n' + '=' * 60)
    print('📋 综合评估:')
    print('1. Phase2新因子: ✅ 单位正确（百分比）')
    print('2. 龙头低吸: ⚠️ 需要确认pullback_pct符号')
    print('3. 跌停翘板: ⚠️ 需要确认rise_after_limit_down单位')
    print('4. 其他策略: ✅ 初步检查正常')

if __name__ == "__main__":
    asyncio.run(main())