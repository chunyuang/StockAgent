#!/usr/bin/env python3
"""
完整 30 天仿真验证 - 扩大数据范围
对五大策略在最近可获取数据范围内进行完整验证
"""

import sys
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple

# 添加项目路径
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from core.managers import (
    tushare_manager,
    mongo_manager,
    feishu_bitable_manager,
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
logger = logging.getLogger("full_30days_verify")

# 五大策略完整配置
STRATEGY_CONFIGS = [
    {
        "name": "涨停开板",
        "strategy_class": LimitOpenStrategy,
        "params": {"limit_type": "up"},
        "strategy_type": "limit_open",
    },
    {
        "name": "跌停翘板",
        "strategy_class": LimitOpenStrategy,
        "params": {"limit_type": "down"},
        "strategy_type": "limit_open",
    },
    {
        "name": "5日线低吸",
        "strategy_class": MA5BuyStrategy,
        "params": {"touch_range": 0.02, "stable_periods": 2},
        "strategy_type": "ma5_buy",
    },
    {
        "name": "涨跌幅阈值-跌6%",
        "strategy_class": PriceChangeStrategy,
        "params": {"threshold": 6.0, "direction": "down", "once_per_day": True},
        "strategy_type": "price_change",
    },
    {
        "name": "龙头战法",
        "strategy_class": LeadingDragonStrategy,
        "params": {"min_height": 3, "min_turnover": 15},
        "strategy_type": "leading_dragon",
    },
    {
        "name": "首板打板",
        "strategy_class": FirstBoardStrategy,
        "params": {"min_turnover": 8, "min_volume_ratio": 1.5},
        "strategy_type": "first_board",
    },
]

async def init_connections():
    """初始化数据库连接"""
    logger.info("初始化数据库连接...")
    await mongo_manager.initialize()
    logger.info("✅ MongoDB 连接成功")
    
    await tushare_manager.initialize()
    logger.info("✅ TushareManager 初始化成功")
    
    if settings.feishu.enabled:
        await feishu_bitable_manager.initialize()
        logger.info("✅ 飞书多维表格管理器初始化成功")
    else:
        logger.warning("⚠️  飞书未启用，只验证不写入")
    
    return True

async def get_recent_trade_dates_from_mongo(days: int = 30) -> List[str]:
    """从 MongoDB 获取最近 N 个交易日"""
    pipeline = [
        {"$group": {"_id": "$trade_date"}},
        {"$sort": {"_id": -1}},
        {"$limit": days},
    ]
    
    result = await mongo_manager.aggregate("stock_daily", pipeline)
    dates = [str(r["_id"]) for r in result]
    dates.sort(reverse=True)
    
    logger.info(f"✓ 从 MongoDB 获取到最近 {len(dates)} 个交易日")
    if len(dates) > 0:
        logger.info(f"  最新日期: {dates[0]}, 最老日期: {dates[-1]}")
    
    return dates

async def process_date(
    trade_date: str,
    strategy_config: Dict[str, Any],
) -> List[Any]:
    """处理单个交易日的单个策略"""
    
    name = strategy_config["name"]
    strategy_class = strategy_config["strategy_class"]
    params = strategy_config["params"]
    
    logger.info(f"\n  ─── 处理日期 {trade_date}，策略 {name} ───")
    
    # 创建策略实例
    strategy = strategy_class()
    
    # 创建订阅
    from core.protocols import StrategySubscription, MarketSnapshot
    
    subscription = StrategySubscription(
        subscription_id=f"verify_{name}_{trade_date}",
        strategy_id=f"verify_{name}",
        strategy_name=name,
        strategy_type=strategy_config["strategy_type"],
        params=params,
        is_all_market=True,
        watch_list=[],
    )
    
    # 获取涨跌停数据
    limit_list = await tushare_manager.get_stk_limit(trade_date)
    limit_data = {item["ts_code"]: item for item in limit_list}
    logger.info(f"  ✓ 获取到 {len(limit_data)} 只涨跌停股票")
    
    if len(limit_data) == 0:
        logger.warning(f"  ⚠️  未获取到涨跌停数据，跳过")
        return []
    
    # 构造当前快照
    snapshot = MarketSnapshot(
        trade_date=trade_date,
        timestamp=datetime.now().isoformat(),
        limit_stocks=limit_data,
        quotes={},
    )
    
    # 获取上一个交易日（从 MongoDB）
    all_dates = await get_recent_trade_dates_from_mongo(60)
    prev_trade_date = None
    for d in all_dates:
        if d < trade_date:
            prev_trade_date = d
            break
    
    if prev_trade_date:
        prev_limit_list = await tushare_manager.get_stk_limit(prev_trade_date)
        prev_limit_data = {item["ts_code"]: item for item in prev_limit_list}
        previous_snapshot = MarketSnapshot(
            trade_date=prev_trade_date,
            timestamp=datetime.now().isoformat(),
            limit_stocks=prev_limit_data,
            quotes={},
        )
        logger.info(f"  ✓ 上一交易日 {prev_trade_date}，{len(prev_limit_data)} 只涨跌停")
    else:
        previous_snapshot = None
        logger.warning(f"  ⚠️  未找到上一交易日，previous_snapshot = None")
    
    # 获取 5日平均成交量 函数
    async def get_5d_avg_volume(ts_code: str, end_date: str) -> float:
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
        return avg * 100  # 手转股
    
    # 加载每只股票日线数据
    count = 0
    matched = 0
    
    for ts_code in limit_data.keys():
        daily_data = await mongo_manager.find_one(
            "stock_daily",
            {"ts_code": ts_code, "trade_date": trade_date},
        )
        if not daily_data:
            continue
        
        # 获取股票名称
        stock_basic = await mongo_manager.find_one(
            "stock_basic",
            {"ts_code": ts_code},
        )
        stock_name = stock_basic.get("name", ts_code) if stock_basic else ts_code
        
        # 过滤 ST 股票
        if stock_name and any(p in stock_name.upper() for p in ["ST", "*ST", "S*ST", "SST"]):
            continue
        
        volume_5d_avg = await get_5d_avg_volume(ts_code, trade_date)
        turnover = daily_data.get("turnover", 0)
        if turnover > 100:
            turnover = turnover / 100  # 确保是百分比
        
        quote = {
            "price": daily_data.get("close", 0),
            "open": daily_data.get("open", 0),
            "high": daily_data.get("high", 0),
            "low": daily_data.get("low", 0),
            "pct_chg": daily_data.get("pct_chg", 0),
            "turnover": turnover,
            "volume": daily_data.get("vol", 0) * 100,
            "volume_5d_avg": volume_5d_avg,
            "name": stock_name,
        }
        
        snapshot.quotes[ts_code] = quote
        count += 1
    
    logger.info(f"  ✓ 加载了 {count} 只股票日线数据")
    
    # 重置每日触发
    if hasattr(strategy, 'reset_daily_triggers'):
        strategy.reset_daily_triggers()
        logger.info(f"  ✓ 重置每日触发记录")
    
    # MA5 需要预加载
    if name == "5日线低吸":
        await strategy._ensure_cache_updated()
        for ts_code in snapshot.quotes.keys():
            await strategy._load_stock_data(ts_code)
        logger.info(f"  ✓ 预加载 {len(snapshot.quotes)} 只股票 MA5 数据")
    
    # 执行评估
    alerts = await strategy.evaluate(subscription, snapshot, previous_snapshot)
    
    if alerts:
        logger.info(f"  🎯 策略触发 {len(alerts)} 个信号:")
        for alert in alerts:
            logger.info(f"      - {alert.stock_name}({alert.ts_code}): {alert.trigger_reason}")
        matched += len(alerts)
    else:
        logger.info(f"  ℹ️  没有股票满足条件")
    
    # 写入飞书
    if settings.feishu.enabled and alerts:
        written = 0
        for alert in alerts:
            success = await feishu_bitable_manager.write_alert(alert)
            if success:
                written += 1
        logger.info(f"  ✓ 已写入 {written}/{len(alerts)} 个信号到飞书多维表格")
    
    return alerts

async def main():
    """主函数"""
    logger.info("=" * 70)
    logger.info("StockAgent 完整 30 天验证")
    logger.info("验证五大策略，找出所有满足条件的信号")
    logger.info("验证时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 70)
    
    # 初始化连接
    try:
        await init_connections()
    except Exception as e:
        logger.error(f"❌ 初始化失败: {e}", exc_info=True)
        return 1
    
    # 获取最近 30 个交易日
    try:
        trade_dates = await get_recent_trade_dates_from_mongo(30)
    except Exception as e:
        logger.error(f"❌ 获取交易日失败: {e}", exc_info=True)
        return 1
    
    if len(trade_dates) == 0:
        logger.error("❌ 没有获取到交易日")
        return 1
    
    # 逐个处理
    total_alerts = 0
    total_dates = 0
    all_results = []
    
    for strategy_config in STRATEGY_CONFIGS:
        strategy_name = strategy_config["name"]
        logger.info(f"\n{'='*70}")
        logger.info(f"开始验证策略: {strategy_name}")
        logger.info(f"参数: {strategy_config['params']}")
        logger.info(f"{'='*70}")
        
        strategy_alerts = 0
        
        for trade_date in trade_dates:
            try:
                alerts = await process_date(trade_date, strategy_config)
                strategy_alerts += len(alerts)
                total_alerts += len(alerts)
                total_dates += 1
            except Exception as e:
                logger.error(f"❌ 处理 {trade_date} 失败: {e}", exc_info=True)
                continue
        
        all_results.append({
            "strategy": strategy_name,
            "alerts": strategy_alerts,
        })
        
        logger.info(f"\n📊 策略 {strategy_name} 完成，共触发 {strategy_alerts} 个信号")
    
    # 总结
    logger.info("\n" + "=" * 70)
    logger.info("📊 完整 30 天验证完成总结")
    logger.info("=" * 70)
    
    for result in all_results:
        logger.info(f"  ✅ {result['strategy']}: {result['alerts']} 个信号")
    
    logger.info(f"\n📈 总计:")
    logger.info(f"   验证交易日: {total_dates}")
    logger.info(f"   触发信号总数: {total_alerts}")
    logger.info(f"   飞书写入: {'已启用' if settings.feishu.enabled else '未启用'}")
    logger.info("=" * 70)
    
    logger.info("\n🎉 完整验证完成！")
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
