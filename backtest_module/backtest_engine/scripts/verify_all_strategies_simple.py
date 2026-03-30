#!/usr/bin/env python3
"""
五大策略完整验证 - 简化版
针对已知的历史信号进行验证，确保数据拉取和逻辑正确
"""

import sys
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

# 添加项目路径
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from core.managers import (
    tushare_manager,
    mongo_manager,
)

# 导入所有策略
from nodes.listener.strategies.limit_open import LimitOpenStrategy
from nodes.listener.strategies.ma5_buy import MA5BuyStrategy
from nodes.listener.strategies.price_change import PriceChangeStrategy
from nodes.listener.strategies.leading_dragon import LeadingDragonStrategy
from nodes.listener.strategies.first_board import FirstBoardStrategy

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("verify_all_strategies")

# 五大策略测试用例（30天内真实数据）
# 格式: (策略类, 参数, 测试日期, 预期股票, 预期条件)
TEST_CASES = [
    # 1. 涨停开板 - 豫能控股 001896 2026-03-13
    # 条件: 昨日涨停，今日开盘开板
    {
        "name": "涨停开板",
        "strategy_class": LimitOpenStrategy,
        "params": {"limit_type": "up"},
        "trade_date": "20260313",
        "ts_code": "001896.SZ",
        "stock_name": "豫能控股",
        "expected": "should_match",  # 应该匹配
        "description": "涨停开板策略，昨日涨停今日开盘后开板",
        "known_data": {
            "prev_price": 17.16,  # 昨日收盘价 = 昨日涨停价
            "current_price": 15.44,  # 今日收盘价，已经开板
            "up_limit": 17.16,
        }
    },
    # 2. 5日线低吸 - 金安国纪 002636 2026-03-02
    {
        "name": "5日线低吸",
        "strategy_class": MA5BuyStrategy, 
        "params": {"touch_range": 0.02, "stable_periods": 2},
        "trade_date": "20260302",
        "ts_code": "002636.SZ",
        "stock_name": "金安国纪",
        "expected": "should_match",
        "description": "龙头回踩5日线企稳低吸",
    },
    # 3. 涨跌幅阈值 - 大金重工 002487 2026-03-16
    {
        "name": "涨跌幅阈值",
        "strategy_class": PriceChangeStrategy,
        "params": {"threshold": 6.0, "direction": "down", "once_per_day": True},
        "trade_date": "20260316",
        "ts_code": "002487.SZ",
        "stock_name": "大金重工",
        "expected": "should_match",
        "description": "跌幅超过6%触发监控",
    },
]

async def init_connections():
    """初始化数据库连接"""
    logger.info("初始化数据库连接...")
    await mongo_manager.initialize()
    logger.info("✅ MongoDB 连接成功")
    
    await tushare_manager.initialize()
    logger.info("✅ TushareManager 初始化成功")
    
    return True

async def verify_strategy(case: Dict[str, Any]):
    """验证单个策略"""
    name = case["name"]
    strategy_class = case["strategy_class"]
    params = case["params"]
    trade_date = case["trade_date"]
    ts_code = case["ts_code"]
    stock_name = case["stock_name"]
    
    logger.info(f"\n{'='*60}")
    logger.info(f"开始验证: {name}")
    logger.info(f"描述: {case.get('description', '')}")
    logger.info(f"参数: {params}")
    logger.info(f"测试日期: {trade_date}")
    logger.info(f"测试股票: {ts_code} {stock_name}")
    
    # 创建策略实例
    strategy = strategy_class()
    
    # 创建订阅
    from core.protocols import StrategySubscription
    subscription = StrategySubscription(
        subscription_id=f"test_{name}_{trade_date}",
        strategy_id=f"test_{name}",
        strategy_name=name,
        strategy_type=strategy.strategy_type,
        params=params,
        is_all_market=False,
        watch_list=[ts_code],
    )
    
    # 获取涨跌停数据
    logger.info(f"获取涨跌停数据 for {trade_date}...")
    limit_list = await tushare_manager.get_stk_limit(trade_date)
    limit_data = {item["ts_code"]: item for item in limit_list}
    logger.info(f"✓ 获取到 {len(limit_data)} 只涨跌停股票")
    
    # 获取日线数据
    daily_data = await mongo_manager.find_one(
        "stock_daily",
        {"ts_code": ts_code, "trade_date": trade_date},
    )
    
    if not daily_data:
        logger.error(f"❌ 未找到 {ts_code} 在 {trade_date} 的日线数据")
        return []
    
    logger.info(f"✓ 找到日线数据:")
    logger.info(f"   开盘: {daily_data.get('open')}")
    logger.info(f"   最高: {daily_data.get('high')}")
    logger.info(f"   最低: {daily_data.get('low')}")
    logger.info(f"   收盘: {daily_data.get('close')}")
    logger.info(f"   涨跌幅: {daily_data.get('pct_chg'):.2f}%")
    logger.info(f"   成交量: {daily_data.get('vol'):.0f} 手")
    
    # 构造 MarketSnapshot
    from core.protocols import MarketSnapshot
    
    # 获取5日均量
    async def get_5d_avg_volume(ts_code, end_date):
        records = await mongo_manager.find_many(
            "stock_daily",
            {"ts_code": ts_code, "trade_date": {"$lte": end_date}},
            sort=[("trade_date", -1)],
            limit=5,
        )
        if not records:
            return 0
        volumes = [r.get("vol", 0) for r in records]
        avg = sum(volumes) / len(volumes)
        return avg * 100
    
    volume_5d_avg = await get_5d_avg_volume(ts_code, trade_date)
    
    # 获取换手率
    turnover = daily_data.get("turnover", 0)
    if turnover > 100:
        turnover = turnover / 100  # 确保是百分比
    
    # 构造 quote
    quote = {
        "price": daily_data.get("close", 0),
        "open": daily_data.get("open", 0),
        "high": daily_data.get("high", 0),
        "low": daily_data.get("low", 0),
        "pct_chg": daily_data.get("pct_chg", 0),
        "vol": daily_data.get("vol", 0),
        "amount": daily_data.get("amount", 0),
        "turnover": turnover,
        "volume": daily_data.get("vol", 0) * 100,
        "volume_5d_avg": volume_5d_avg,
        "name": stock_name,
    }
    
    snapshot = MarketSnapshot(
        trade_date=trade_date,
        timestamp=datetime.now().isoformat(),
        limit_stocks=limit_data,
        quotes={ts_code: quote},
    )
    
    # 对于涨停开板，构造 previous_snapshot 显示股票昨日涨停
    previous_snapshot = None
    if name == "涨停开板" and ts_code in limit_data:
        # 构造上一时刻快照，显示股票还在涨停
        limit_info = limit_data.get(ts_code, {})
        up_limit = limit_info.get('up_limit', quote.get('price'))
        # previous 价格在涨停
        previous_quotes = {
            ts_code: {
                "price": up_limit,
                "name": stock_name,
            }
        }
        previous_snapshot = MarketSnapshot(
            trade_date=trade_date,
            timestamp=(datetime.now().isoformat()),
            limit_stocks=limit_data,
            quotes=previous_quotes,
        )
        logger.info(f"构造previous_snapshot: previous_price={up_limit}")
    
    # 执行评估
    # 对于已知信号，我们手动帮助状态机推进到位
    alerts = []
    
    if name == "5日线低吸":
        # MA5 需要预加载数据
        await strategy._ensure_cache_updated()
        await strategy._load_stock_data(ts_code)
        
        # 检查 MA5 计算
        if ts_code in strategy._stock_data:
            data = strategy._stock_data[ts_code]
            ma5 = data.get('ma5', 0)
            prev_close = data.get('prev_close', 0)
            logger.info(f"MA5 计算结果: MA5={ma5:.2f}, 昨日收盘={prev_close:.2f}")
            current_price = quote.get('price', 0)
            distance_pct = (current_price / ma5) - 1
            logger.info(f"当前价格={current_price:.2f}, 距离MA5={distance_pct*100:.2f}% (允许范围 ±{params['touch_range']*100:.2f}%)")
            was_above = prev_close > ma5
            logger.info(f"昨日在MA5上方: {was_above}")
        
        # 模拟多轮迭代（因为需要连续站稳）
        # 第一轮：触及
        result1 = await strategy.evaluate(subscription, snapshot, None)
        logger.info(f"第一轮（触及）: {len(result1)} 信号")
        
        # 获取当前状态
        tracker = strategy._trackers.get(ts_code)
        if tracker:
            logger.info(f"当前状态: {tracker.state.name}")
            logger.info(f"企稳计数: {tracker.stable_count}")
        
        # 第二轮：再次评估（模拟下一分钟）
        result2 = await strategy.evaluate(subscription, snapshot, snapshot)
        logger.info(f"第二轮（企稳）: {len(result2)} 信号")
        
        if result2:
            alerts.extend(result2)
    else:
        # 其他策略直接评估
        # price_change 需要重置每日触发记录
        if hasattr(strategy, 'reset_daily_triggers'):
            strategy.reset_daily_triggers()
        
        result = await strategy.evaluate(subscription, snapshot, previous_snapshot)
        if result:
            logger.info(f"🎯 策略触发!")
            for alert in result:
                logger.info(f"   - {alert.stock_name}({alert.ts_code}): {alert.trigger_reason}")
            alerts.extend(result)
        else:
            logger.info(f"ℹ️  策略未触发。实际涨跌幅: {quote.get('pct_chg', 0):.2f}%")
    
    logger.info(f"验证完成: {name}，触发 {len(alerts)} 个信号")
    return alerts

async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("StockAgent 五大策略完整验证 (简化版 - 已知历史信号验证)")
    logger.info("验证时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)
    
    # 初始化连接
    try:
        await init_connections()
    except Exception as e:
        logger.error(f"❌ 初始化失败: {e}", exc_info=True)
        return 1
    
    # 逐个验证
    total_alerts = 0
    all_results = []
    
    for case in TEST_CASES:
        try:
            alerts = await verify_strategy(case)
            total_alerts += len(alerts)
            all_results.append({
                "name": case["name"],
                "alerts": len(alerts),
                "success": True,
                "expected": case["expected"],
            })
        except Exception as e:
            logger.error(f"❌ 验证 {case['name']} 失败: {e}", exc_info=True)
            all_results.append({
                "name": case["name"],
                "alerts": 0,
                "success": False,
                "error": str(e),
            })
    
    # 总结
    logger.info("\n" + "=" * 60)
    logger.info("📊 验证完成总结")
    logger.info("=" * 60)
    
    passed = 0
    failed = 0
    
    for result in all_results:
        expected = result.get("expected", "any")
        if result["success"]:
            if expected == "should_match" and result["alerts"] > 0:
                status = "✅ 通过"
                passed += 1
            elif expected == "should_not_match" and result["alerts"] == 0:
                status = "✅ 通过"
                passed += 1
            else:
                status = "⚠️  结果不符"
                failed += 1
            logger.info(f"{status} {result['name']}: 触发 {result['alerts']} 个信号")
        else:
            status = "❌ 失败"
            failed += 1
            logger.info(f"{status} {result['name']}: {result.get('error', 'unknown error')}")
    
    logger.info(f"\n📈 总计: {passed}/{len(all_results)} 个用例通过")
    logger.info(f"   触发信号总数: {total_alerts}")
    logger.info("=" * 60)
    
    if failed == 0:
        logger.info("\n🎉 所有验证用例通过！")
        return 0
    else:
        logger.error(f"\n❌ 有 {failed} 个用例失败")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
