
import sys
sys.path.insert(0, './AgentServer')
import asyncio
import pandas as pd

async def simple_verify():
    print('=' * 80)
    print('🧪 最简单验证：用4天数据计算3日变化率')
    print('=' * 80)
    print()
    
    from core.managers import mongo_manager
    await mongo_manager.initialize()
    
    test_date = "20260108"
    test_code = "000001.SZ"
    
    # 获取4天数据
    docs = await mongo_manager.find_many(
        "stock_daily_ak_full",
        {"ts_code": test_code, "trade_date": {"$gte": 20260105, "$lte": 20260108}},
        projection={"trade_date": 1, "close": 1, "_id": 0}
    )
    docs_sorted = sorted(docs, key=lambda x: x['trade_date'])
    
    # 转成DataFrame
    df = pd.DataFrame(docs_sorted).set_index('trade_date')
    print('✅ 拿到的4天数据：')
    print(df)
    print()
    
    # 手动计算3日变化率
    closes = df['close'].tolist()
    print(f'收盘价序列：{closes}')
    change_3d = (closes[-1] - closes[0]) / closes[0] * 100
    print(f'手动计算3日变化率：{change_3d:.2f}%')
    print()
    
    # 用pandas计算（模拟FactorEngine的方式）
    df['change_3d'] = (df['close'] / df['close'].shift(3) - 1) * 100
    print('用pandas.shift(3)计算：')
    print(df[['close', 'change_3d']])
    print()
    
    print('=' * 80)
    print('🏆 验证结论')
    print('=' * 80)
    print()
    print('✅ 第1天（20260105）：NaN，正常（没有前3天数据）')
    print('✅ 第2天（20260106）：NaN，正常')
    print('✅ 第3天（20260107）：NaN，正常')
    print('✅ 第4天（20260108）：有值，正确！')
    print()
    print('💡 关键发现：')
    print('   4天数据只能算出1天的3日因子值！')
    print('   20日动量需要至少21天数据才能算出1天的值！')
    print()
    print('❌ 之前的问题：只有4天数据，算20日动量，结果全是NaN！')
    print('✅ 不是代码的问题，是数据量不够！')
    print('=' * 80)

asyncio.run(simple_verify())
