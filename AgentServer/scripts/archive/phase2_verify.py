"""Phase2 快速验证脚本 - 测试新因子计算是否正确"""
import asyncio, sys, os, types, json, time
import pandas as pd
import numpy as np

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager
from nodes.backtest_engine.factor_selection.factor_engine import FactorEngine
# 直接使用字符串常量
C = type('C', (), {'STOCK_DAILY': 'stock_daily_ak_full'})()

async def test_new_factors():
    """测试新因子计算"""
    await mongo_manager.initialize()
    
    # 创建因子引擎实例
    factor_engine = FactorEngine()
    
    # 测试日期
    test_date = "20260506"
    
    # 获取一些样本股票数据
    cursor = mongo_manager.db[C.STOCK_DAILY].find(
        {"trade_date": test_date},
        {"ts_code": 1, "open": 1, "high": 1, "pre_close": 1, "pct_chg": 1, "_id": 0}
    ).limit(10)
    stocks = await cursor.to_list(length=10)
    
    print("📊 测试新因子计算")
    print("=" * 60)
    
    for stock in stocks:
        ts_code = stock["ts_code"]
        open_price = stock.get("open")
        high = stock.get("high")
        pre_close = stock.get("pre_close")
        pct_chg = stock.get("pct_chg", 0)
        
        # 计算新因子
        if pre_close and pre_close != 0:
            intraday_max_rise_pct = (high - pre_close) / pre_close * 100 if high else None
            intraday_open_rise_pct = (open_price - pre_close) / pre_close * 100 if open_price else None
            
            print(f"{ts_code}:")
            print(f"  昨收: {pre_close:.2f}, 今开: {open_price:.2f}, 最高: {high:.2f}")
            print(f"  收盘涨幅(pct_chg): {pct_chg:.2f}%")
            print(f"  盘中最高涨幅(intraday_max_rise_pct): {intraday_max_rise_pct:.2f}%" if intraday_max_rise_pct else "  盘中最高涨幅: N/A")
            print(f"  开盘涨幅(intraday_open_rise_pct): {intraday_open_rise_pct:.2f}%" if intraday_open_rise_pct else "  开盘涨幅: N/A")
            print()

async def test_factor_engine():
    """测试因子引擎是否能正确计算新因子"""
    await mongo_manager.initialize()
    
    factor_engine = FactorEngine()
    
    # 测试因子配置
    factor_configs = [
        {"name": "intraday_max_rise_pct", "weight": 1.0, "ascending": True},
        {"name": "intraday_open_rise_pct", "weight": 1.0, "ascending": True},
        {"name": "volume_ratio", "weight": 1.0, "ascending": True}
    ]
    
    test_date = "20260506"
    
    print("📊 测试因子引擎新因子计算")
    print("=" * 60)
    
    try:
        # 调用因子引擎
        result = await factor_engine.compute_factors(
            stock_list=[],
            factor_configs=factor_configs,
            trade_date=test_date
        )
        
        if isinstance(result, pd.DataFrame):
            print(f"✅ 因子引擎返回 {len(result)} 条记录")
            print("包含的列:", result.columns.tolist())
            
            # 检查新因子是否存在
            if "intraday_max_rise_pct" in result.columns:
                print(f"✅ intraday_max_rise_pct 存在，范围: {result['intraday_max_rise_pct'].min():.2f}% ~ {result['intraday_max_rise_pct'].max():.2f}%")
            else:
                print("❌ intraday_max_rise_pct 不存在")
                
            if "intraday_open_rise_pct" in result.columns:
                print(f"✅ intraday_open_rise_pct 存在，范围: {result['intraday_open_rise_pct'].min():.2f}% ~ {result['intraday_open_rise_pct'].max():.2f}%")
            else:
                print("❌ intraday_open_rise_pct 不存在")
                
            # 显示前5只股票
            print("\n📈 前5只股票因子值:")
            for i, row in result.head().iterrows():
                print(f"{row['ts_code']}: max_rise={row.get('intraday_max_rise_pct', 'N/A'):.2f}%, open_rise={row.get('intraday_open_rise_pct', 'N/A'):.2f}%")
                
        else:
            print("❌ 因子引擎返回的不是DataFrame")
            
    except Exception as e:
        print(f"❌ 因子引擎测试失败: {e}")
        import traceback
        traceback.print_exc()

async def main():
    await mongo_manager.initialize()
    
    print("🔍 Phase2 因子修复验证")
    print("=" * 60)
    
    # 测试1: 基本因子计算
    await test_new_factors()
    
    # 测试2: 因子引擎集成
    await test_factor_engine()
    
    print("=" * 60)
    print("✅ 验证完成")

if __name__ == "__main__":
    asyncio.run(main())