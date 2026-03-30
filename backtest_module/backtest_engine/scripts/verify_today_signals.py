#!/usr/bin/env python3
"""
验证今日（2026-03-16）涨跌停列表中满足五大策略条件的信号
并写入飞书多维表格
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
logger = logging.getLogger("verify_today_signals")

# 五大策略配置
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

async def process_today():
    """处理今日数据，找出所有满足条件的信号"""
    
    trade_date = "20260316"
    logger.info(f"处理今日 {trade_date} 涨跌停数据...")
    
    from core.protocols import StrategySubscription, MarketSnapshot
    
    # 获取涨跌停数据
    limit_list = await tushare_manager.get_stk_limit(trade_date)
    limit_data = {item["ts_code"]: item for item in limit_list}
    logger.info(f"✓ 获取到 {len(limit_data)} 只涨跌停股票")
    
    # 获取昨日涨跌停数据 - 使用 fallback 逻辑
    yesterday = "20260315"
    logger.info(f"获取昨日 {yesterday} 涨跌停数据...")
    prev_limit_list = await tushare_manager.get_stk_limit(yesterday)
    prev_limit_data = {item["ts_code"]: item for item in prev_limit_list}
    logger.info(f"✓ 昨日 {yesterday} 获取到 {len(prev_limit_data)} 只涨跌停股票")
    
    # 构造快照
    snapshot = MarketSnapshot(
        trade_date=trade_date,
        timestamp=datetime.now().isoformat(),
        limit_stocks=limit_data,
        quotes={},
    )
    
    previous_snapshot = MarketSnapshot(
        trade_date=yesterday,
        timestamp=datetime.now().isoformat(),
        limit_stocks=prev_limit_data,
        quotes={},
    )
    
    # 加载每只股票日线数据
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
        return avg * 100
    
    count = 0
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
        
        # 过滤 ST
        if any(p in stock_name.upper() for p in ["ST", "*ST", "S*ST", "SST"]):
            logger.debug(f"  过滤ST: {stock_name}")
            continue
        
        volume_5d_avg = await get_5d_avg_volume(ts_code, trade_date)
        turnover = daily_data.get("turnover", 0)
        if turnover > 100:
            turnover = turnover / 100
        
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
    
    logger.info(f"✓ 加载了 {count} 只股票日线数据")
    
    # 逐个策略验证
    total_alerts = 0
    all_alerts = []
    
    for config in STRATEGY_CONFIGS:
        name = config["name"]
        strategy_class = config["strategy_class"]
        params = config["params"]
        
        logger.info(f"\n  ─── 验证策略: {name} ───")
        
        strategy = strategy_class()
        
        subscription = StrategySubscription(
            subscription_id=f"today_{name}",
            strategy_id=f"today_{name}",
            strategy_name=name,
            strategy_type=config["strategy_type"],
            params=params,
            is_all_market=True,
            watch_list=[],
        )
        
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
        
        alerts = await strategy.evaluate(subscription, snapshot, previous_snapshot)
        
        if alerts:
            logger.info(f"  🎯 触发 {len(alerts)} 个信号:")
            for alert in alerts:
                logger.info(f"      - {alert.stock_name}({alert.ts_code}): {alert.trigger_reason}")
            total_alerts += len(alerts)
            all_alerts.extend(alerts)
        else:
            logger.info(f"  ℹ️  没有满足条件的信号")
    
    # 写入飞书
    if settings.feishu.enabled and all_alerts:
        written = 0
        for alert in all_alerts:
            success = await feishu_bitable_manager.write_alert(alert)
            if success:
                written += 1
        logger.info(f"\n✓ 已写入 {written}/{len(all_alerts)} 个信号到飞书多维表格")
    
    # 总结
    logger.info("\n" + "="*60)
    logger.info(f"📊 今日 {trade_date} 验证总结")
    logger.info("="*60)
    for config in STRATEGY_CONFIGS:
        name = config["name"]
        cnt = sum(1 for a in all_alerts if a.strategy_name == name)
        logger.info(f"  {name}: {cnt} 个信号")
    logger.info(f"\n📈 总计: {total_alerts} 个信号满足条件")
    if settings.feishu.enabled:
        logger.info(f"   已写入飞书多维表格")
    logger.info("="*60)
    
    return all_alerts

async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("StockAgent 今日（2026-03-16）信号验证")
    logger.info("找出所有满足五大策略条件的信号，写入飞书多维表格")
    logger.info("验证时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)
    
    try:
        await init_connections()
        await process_today()
        logger.info("\n🎉 验证完成！")
        return 0
    except Exception as e:
        logger.error(f"❌ 验证失败: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
