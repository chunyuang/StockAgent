#!/usr/bin/env python3
"""
全市场真实回测
使用stock_agent_full数据库的全市场数据
包含所有新增模拟功能：滑点、涨跌停限制、仓位管理
"""
import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

import asyncio
import json
from datetime import datetime
from pymongo import AsyncMongoClient

# 全局指定数据库名称
MONGO_DB_NAME = "stock_agent_full"
MONGO_URI = "mongodb://localhost:27017/"

#  monkey patch 替换mongo_manager的数据库连接
from core.managers import mongo_manager, redis_manager

# 重新初始化mongo管理器到全市场数据库
mongo_manager.client = AsyncMongoClient(MONGO_URI)
mongo_manager.db = mongo_manager.client[MONGO_DB_NAME]

from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester

async def run_full_market_backtest():
    print("="*80)
    print("🚀 全市场真实回测")
    print("="*80)
    print(f"数据库: {MONGO_DB_NAME}")
    print("回测区间: 20260105 ~ 20260320")
    print("初始资金: 1,000,000 元")
    print("模拟参数: 滑点千1、佣金万2、印花税千1、涨停无法买入、跌停无法卖出")
    print("仓位限制: 单票最大20%、总仓位最大100%")
    print("="*80)
    
    # 初始化管理器
    await mongo_manager.initialize()
    await redis_manager.initialize()
    
    print("✅ 管理器初始化完成")
    
    # 验证数据
    db = mongo_manager.db
    stocks = await db.stock_daily_ak_full.distinct("ts_code")
    dates = sorted(await db.stock_daily_ak_full.distinct("trade_date"))
    start_date = "20260105"
    end_date = "20260320"
    
    # 筛选回测区间内的日期
    test_dates = [d for d in dates if str(d) >= start_date and str(d) <= end_date]
    total_records = await db.stock_daily_ak_full.count_documents({
        "trade_date": {"$gte": int(start_date), "$lte": int(end_date)}
    })
    
    print("\n📊 数据统计:")
    print(f"  股票数量: {len(stocks)}只")
    print(f"  回测交易日: {len(test_dates)}天")
    print(f"  回测区间总记录数: {total_records}条")
    
    # 策略配置（五大超短策略）
    strategies = [
        {
            "name": "半路追涨",
            "factors": [
                {"name": "limit_up_yesterday", "weight": 0.4, "direction": "asc"},
                {"name": "open_below_limit", "weight": 0.3, "direction": "asc"},
                {"name": "volume_increase", "weight": 0.3, "direction": "desc"}
            ],
            "n_stocks": 5,
            "weight_method": "equal"
        },
        {
            "name": "涨停开板",
            "factors": [
                {"name": "limit_up_yesterday", "weight": 0.4, "direction": "asc"},
                {"name": "first_limit_up", "weight": 0.6, "direction": "desc"}
            ],
            "n_stocks": 5,
            "weight_method": "equal"
        },
        {
            "name": "MA5低吸",
            "factors": [
                {"name": "pullback_ma5", "weight": 0.6, "direction": "asc"},
                {"name": "volume_increase", "weight": 0.4, "direction": "desc"}
            ],
            "n_stocks": 10,
            "weight_method": "equal"
        },
        {
            "name": "龙头低吸",
            "factors": [
                {"name": "market_leader", "weight": 0.5, "direction": "asc"},
                {"name": "pullback_ma5", "weight": 0.3, "direction": "asc"},
                {"name": "lhb_buy_in", "weight": 0.2, "direction": "desc"}
            ],
            "n_stocks": 3,
            "weight_method": "equal"
        },
        {
            "name": "首板打板",
            "factors": [
                {"name": "first_limit_up", "weight": 0.6, "direction": "asc"},
                {"name": "volume_increase", "weight": 0.4, "direction": "desc"}
            ],
            "n_stocks": 3,
            "weight_method": "equal"
        }
    ]
    
    print(f"\n📈 运行策略: {len(strategies)}个")
    
    # 运行所有策略
    all_results = []
    for strategy in strategies:
        print(f"\n🔍 运行策略: {strategy['name']}")
        
        backtester = PortfolioBacktester(source=None)
        
        config = {
            "strategy_name": strategy["name"],
            "universe": "all_a",
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": 1000000,
            "rebalance_freq": "daily",
            "top_n": strategy["n_stocks"],
            "weight_method": strategy["weight_method"],
            "liquidity_threshold": 1000,  # 1000万流动性门槛
            "max_position_per_stock": 0.2,  # 单票最大20%
            "slippage": 0.001,  # 千1滑点
            "max_position": 1.0,  # 满仓
            "factors": strategy["factors"],
            "data_collection": "stock_daily_ak_full",
        }
        
        try:
            result = await backtester.run(config)
            perf = result.get('performance', {})
            
            print(f"  ✅ 完成: 总收益{perf.get('total_return', 0):.2f}%, "
                  f"交易数{len(result.get('rebalance_records', []))}次, "
                  f"胜率{perf.get('win_rate', 0):.2f}%")
            
            all_results.append({
                "strategy": strategy["name"],
                "total_return": perf.get('total_return', 0),
                "total_trades": len(result.get('rebalance_records', [])),
                "win_rate": perf.get('win_rate', 0),
                "max_drawdown": perf.get('max_drawdown', 0),
                "sharpe_ratio": perf.get('sharpe_ratio', 0)
            })
            
        except Exception as e:
            print(f"  ❌ 失败: {str(e)}")
            import traceback
            traceback.print_exc()
    
    # 输出汇总报告
    print("\n" + "="*80)
    print("📊 全市场回测最终报告")
    print("="*80)
    print(f"{'策略':<8} | {'交易数':>6} | {'胜率':>6} | {'总收益':>8} | {'最大回撤':>8} | {'夏普比率':>8}")
    print("-"*80)
    
    total_trades = 0
    total_return = 0
    for res in all_results:
        total_trades += res['total_trades']
        total_return += res['total_return']
        print(f"{res['strategy']:<8} | {res['total_trades']:6d} | {res['win_rate']:6.2f}% | {res['total_return']:7.2f}% | {res['max_drawdown']:7.2f}% | {res['sharpe_ratio']:8.2f}")
    
    print("-"*80)
    print(f"{'合计':<8} | {total_trades:6d} | {'-':>6} | {total_return/len(all_results):7.2f}% | {'-':>8} | {'-':>8}")
    print("="*80)
    
    # 保存结果
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"/tmp/full_market_backtest_{timestamp}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            "config": {
                "start_date": start_date,
                "end_date": end_date,
                "initial_cash": 1000000,
                "slippage": 0.001,
                "liquidity_threshold": 1000
            },
            "results": all_results
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 详细结果已保存到: {output_file}")
    
    if total_trades > 0:
        print("\n✅ 全市场回测完成，成功产生交易信号！")
    else:
        print("\n⚠️  本区间没有符合条件的交易信号（行情低迷，策略空仓）")
    
    return all_results

if __name__ == "__main__":
    asyncio.run(run_full_market_backtest())
