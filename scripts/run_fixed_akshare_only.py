#!/usr/bin/env python3
"""
修正的 AKShare 独立流程回测
修复流动性门槛计算问题
"""

import sys

# 添加 workspace 根目录和 StockAgent 项目根目录到 path
sys.path.insert(0, '/root/.openclaw/workspace')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

import asyncio
import logging

from core.managers import (
    redis_manager,
    mongo_manager,
    baostock_manager,
    akshare_manager,
)

from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
from backtest_module.backtest_engine.factor_selection.universe import UniverseManager, ExcludeRule
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine

# ========== 配置 ==========
START_DATE = "20260105"
END_DATE = "20260320"
INITIAL_CAPITAL = 1000000  # 初始资金 100万
LIQUIDITY_THRESHOLD = 100  # 流动性门槛 100万元（单位：万元，已经修复）
MAX_POSITION_PERCENT = 20  # 单票最大仓位 20%

# ========== 策略定义 ==========
STRATEGIES = [
    {
        "name": "半路追涨",
        "filters": [
            ("limit_up_yesterday", 1),
            ("open_below_limit", 1),
            ("volume_increase", 1),
        ],
    },
    {
        "name": "涨停开板",
        "filters": [
            ("limit_up_yesterday", 1),
            ("first_limit_up", 0),
        ],
    },
    {
        "name": "跌停翘板",
        "filters": [
            ("limit_down_yesterday", 1),
            ("open_above_limit", 1),
        ],
    },
    {
        "name": "MA5低吸",
        "filters": [
            ("pullback_ma5", 1),
        ],
    },
    {
        "name": "龙头低吸",
        "filters": [
            ("market_leader", 1),
            ("pullback_ma5", 1),
            ("lhb_buy_in", 1),
        ],
    },
    {
        "name": "首板打板",
        "filters": [
            ("limit_up_yesterday", 1),
            ("first_limit_up", 1),
        ],
    },
]

async def main():
    # 初始化日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    )
    
    logger = logging.getLogger(__name__)
    logger.info("🚀 修正版 AKShare 独立流程回测启动")
    logger.info(f"   回测区间: {START_DATE} -> {END_DATE}")
    logger.info(f"   初始资金: {INITIAL_CAPITAL}")
    logger.info(f"   单票最大仓位: {MAX_POSITION_PERCENT}%")
    logger.info(f"   流动性门槛: {LIQUIDITY_THRESHOLD} 万元 (已修复单位)")
    
    # 初始化管理器
    logger.info("初始化管理器...")
    await redis_manager.initialize()
    await mongo_manager.initialize()
    await baostock_manager.initialize()
    await akshare_manager.initialize()
    
    logger.info("所有管理器初始化完成 ✓")
    logger.info("")
    print("=" * 80)
    
    # 检查数据库连接
    try:
        import pymongo
        client = pymongo.MongoClient('localhost', 27017)
        db = client['stock_agent']
        stock_daily_ak_full_coll = db['stock_daily_ak_full_ak']
        
        # 检查数据
        total = stock_daily_ak_full_coll.count_documents({})
        stocks = len(stock_daily_ak_full_coll.distinct('ts_code'))
        dates = len(stock_daily_ak_full_coll.distinct('trade_date'))
        
        logger.info("数据库检查:")
        logger.info(f"  总记录数: {total}")
        logger.info(f"  股票数量: {stocks}")
        logger.info(f"  交易日数量: {dates}")
        
        # 检查流动性数据
        sample = stock_daily_ak_full_coll.find_one({})
        if sample:
            amount = sample.get('amount', 0)
            logger.info(f"  成交额示例: {amount:,.2f} 万元")
            logger.info(f"  对应人民币: {amount * 10000:,.0f} 元")
            
            # 检查满足流动性门槛的股票
            pipeline = [
                {"$match": {"amount": {"$gte": LIQUIDITY_THRESHOLD}}},
                {"$group": {"_id": "$ts_code"}}
            ]
            
            liquid_stocks = list(stock_daily_ak_full_coll.aggregate(pipeline))
            logger.info(f"  满足流动性门槛 ({LIQUIDITY_THRESHOLD}万元) 的股票: {len(liquid_stocks)} 只")
            
            if len(liquid_stocks) > 0:
                logger.info("  流动性股票示例:")
                for i, stock in enumerate(liquid_stocks[:5], 1):
                    stock_code = stock['_id']
                    latest = stock_daily_ak_full_coll.find_one({'ts_code': stock_code}, sort=[('trade_date', -1)])
                    if latest:
                        amount = latest.get('amount', 0)
                        logger.info(f"    {i}. {stock_code}: {amount:,.2f} 万元")
        
        client.close()
        
    except Exception as e:
        logger.error(f"数据库检查失败: {e}")
    
    print("=" * 80)
    
    # 初始化因子引擎 - 指定数据源为 AKShare (source="ak")
    factor_engine = FactorEngine(source="ak")
    
    # 初始化宇宙管理器
    universe_mgr = UniverseManager()
    
    # 获取调仓日期
    rebalance_dates = await baostock_manager.get_trade_dates(START_DATE, END_DATE)
    if not rebalance_dates:
        logger.error("无法获取交易日历，退出")
        return
    
    rebalance_dates = sorted(rebalance_dates)
    logger.info(f"总调仓日期: {len(rebalance_dates)}")
    
    # 结果收集
    all_results = []
    
    # 遍历每个策略
    for strategy in STRATEGIES:
        logger.info("")
        print("=" * 80)
        logger.info(f"开始回测策略: {strategy['name']}")
        logger.info(f"   周期: {START_DATE} -> {END_DATE}")
        logger.info(f"   初始资金: {INITIAL_CAPITAL}")
        print("=" * 80)
        logger.info("")
        
        try:
            # 创建回测器 - 指定数据源为 AKShare (source="ak")
            backtester = PortfolioBacktester(source="ak")
            
            # 配置回测参数 - 使用修正后的流动性门槛
            config = {
                "start_date": START_DATE,
                "end_date": END_DATE,
                "initial_cash": INITIAL_CAPITAL,
                "max_position_percent": MAX_POSITION_PERCENT / 100.0,
                "liquidity_threshold": LIQUIDITY_THRESHOLD,  # 单位：万元，已修复
                "universe_mgr": universe_mgr,
                "factor_engine": factor_engine,
                "exclude_rules": [ExcludeRule.ST, ExcludeRule.NEW_STOCK],
                "factors": [
                    {"name": factor_name, "target": target}
                    for factor_name, target in strategy["filters"]
                ],
                "top_n": 1,
                "rebalance_freq": "daily",
            }
            
            # 运行回测
            result = await backtester.run(config)
            
            if result is None or "error" in result:
                logger.error(f"回测失败 {strategy['name']}: {result.get('error', '未知错误')}")
                continue
            
            # 检查必要字段
            required_fields = ['trade_days', 'win_rate', 'avg_daily_return', 'total_return', 'max_drawdown', 'sharpe_ratio']
            missing = [f for f in required_fields if f not in result]
            if missing:
                logger.error(f"回测缺少字段: {missing}")
                continue
            
            # 保存结果
            result["strategy_name"] = strategy["name"]
            all_results.append(result)
            
            logger.info(f"回测完成 {strategy['name']}")
            logger.info(f"   信号数: {result['trade_days']}")
            logger.info(f"   胜率: {result['win_rate']:.2f}%")
            logger.info(f"   平均日收益: {result['avg_daily_return']:.4f}")
            logger.info(f"   总收益: {result['total_return']:.2f}%")
            logger.info(f"   最大回撤: {result['max_drawdown']:.2f}%")
            logger.info(f"   夏普比率: {result['sharpe_ratio']:.2f}")
            logger.info("")
            
        except Exception as e:
            logger.error(f"策略 {strategy['name']} 异常: {e}")
            import traceback
            traceback.print_exc()
    
    # 生成报告
    print("\n")
    print("=" * 80)
    print(f"📊  修正版 AKShare 回测报告 {START_DATE} ~ {END_DATE}")
    print("=" * 80)
    print()
    
    if all_results:
        print("| 策略名称     | 信号数 | 胜率   | 平均日收益 | 总收益   | 最大回撤 | 夏普比率 |")
        print("|--------------|--------|--------|------------|----------|----------|----------|")
        
        for result in sorted(all_results, key=lambda x: -x['total_return']):
            print(f"| {result['strategy_name']:<10} | {result['trade_days']:>6} | {result['win_rate']:>6.1f}% | {result['avg_daily_return']:>10.4f} | {result['total_return']:>8.1f}% | {result['max_drawdown']:>8.1f}% | {result['sharpe_ratio']:>8.2f} |")
        
        # 总结
        print()
        print("📋 总结:")
        total_signals = sum(r['trade_days'] for r in all_results)
        profitable_strategies = sum(1 for r in all_results if r['total_return'] > 0)
        
        print(f"   总策略数: {len(all_results)} 个")
        print(f"   总信号数: {total_signals} 次")
        print(f"   盈利策略: {profitable_strategies} 个")
        
        if all_results:
            best = max(all_results, key=lambda x: x['total_return'])
            worst = min(all_results, key=lambda x: x['total_return'])
            print(f"   最佳策略: {best['strategy_name']} ({best['total_return']:.1f}%)")
            print(f"   最差策略: {worst['strategy_name']} ({worst['total_return']:.1f}%)")
    else:
        print("❌ 没有回测结果")
        print("   可能原因:")
        print("     1. 没有找到可交易的股票")
        print("     2. 流动性门槛设置太高")
        print("     3. 数据源问题")
    
    print("\n" + "=" * 80)
    print("✅ 回测完成!")
    
    # 关闭连接
    await baostock_manager.shutdown()
    await akshare_manager.shutdown()
    await mongo_manager.shutdown()
    await redis_manager.shutdown()
    
    logger.info("完成!")

if __name__ == "__main__":
    asyncio.run(main())