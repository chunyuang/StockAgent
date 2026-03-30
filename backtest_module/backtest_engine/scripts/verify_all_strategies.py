#!/usr/bin/env python3
"""
五大策略完整验证脚本
对每个策略使用真实历史数据进行模拟，触发后写入飞书多维表格
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
    feishu_bitable_manager,
)
from core.protocols import StrategySubscription

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
# 格式: (策略类, 参数, 测试日期, 预期股票)
TEST_CASES = [
    # 1. 涨停开板 - 豫能控股 001896 2026-03-13
    {
        "name": "涨停开板",
        "strategy_class": LimitOpenStrategy,
        "params": {"limit_type": "up"},
        "trade_date": "20260313",
        "ts_code": "001896.SZ",
        "stock_name": "豫能控股",
        "description": "涨停开板策略，昨日涨停今日开盘后开板"
    },
    # 2. 5日线低吸 - 金安国纪 002636 2026-03-02
    {
        "name": "5日线低吸",
        "strategy_class": MA5BuyStrategy, 
        "params": {"touch_range": 0.02, "stable_periods": 2},
        "trade_date": "20260302",
        "ts_code": "002636.SZ",
        "stock_name": "金安国纪",
        "description": "龙头回踩5日线企稳低吸"
    },
    # 3. 涨跌幅阈值 - 大金重工 002487 2026-03-16
    {
        "name": "涨跌幅阈值",
        "strategy_class": PriceChangeStrategy,
        "params": {"threshold": 6.0, "direction": "down", "once_per_day": True},
        "trade_date": "20260316",
        "ts_code": "002487.SZ",
        "stock_name": "大金重工",
        "description": "跌幅超过6%触发监控"
    },
    # 4. 龙头战法 - 查找3连板以上股票（最近30天）
    {
        "name": "龙头战法",
        "strategy_class": LeadingDragonStrategy,
        "params": {"min_height": 3, "min_turnover": 15},
        "trade_date": "20260314",  # 找最近交易日
        "description": "3连板以上，换手率15%+，涨停"
    },
    # 5. 首板打板 - 查找首板满足条件
    {
        "name": "首板打板",
        "strategy_class": FirstBoardStrategy,
        "params": {"min_turnover": 8, "min_volume_ratio": 1.5},
        "trade_date": "20260314",
        "description": "首次涨停，换手率8%+，成交量1.5x放量"
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

async def verify_strategy(case: Dict[str, Any]):
    """验证单个策略"""
    name = case["name"]
    strategy_class = case["strategy_class"]
    params = case["params"]
    trade_date = case["trade_date"]
    
    logger.info(f"\n{'='*60}")
    logger.info(f"开始验证: {name}")
    logger.info(f"描述: {case.get('description', '')}")
    logger.info(f"参数: {params}")
    logger.info(f"测试日期: {trade_date}")
    
    # 创建策略实例
    strategy = strategy_class()
    
    # 创建订阅
    subscription = StrategySubscription(
        id=f"test_{name}_{trade_date}",
        strategy_type=strategy.strategy_type,
        params=params,
        is_all_market=False,
        stocks=[case.get("ts_code")] if "ts_code" in case else [],
    )
    
    # 获取涨跌停数据（测试日期）
    logger.info(f"获取涨跌停数据 for {trade_date}...")
    limit_list = await tushare_manager.get_stk_limit(trade_date)
    # 转换为字典 {ts_code: info}
    limit_data = {item["ts_code"]: item for item in limit_list}
    logger.info(f"✓ 获取到 {len(limit_data)} 只涨跌停股票")
    
    if len(limit_data) == 0:
        logger.warning(f"⚠️  未获取到涨跌停数据，跳过")
        return []
    
    # 这里简化：我们直接对目标股票进行验证
    alerts = []
    
    if "ts_code" in case:
        # 单只股票测试
        ts_code = case["ts_code"]
        stock_name = case["stock_name"]
        
        # 获取最新日线数据计算需要的指标
        # 这里直接构造snapshot进行评估
        from core.protocols import MarketSnapshot
        
        snapshot = MarketSnapshot(
            trade_date=trade_date,
            timestamp=datetime.now().isoformat(),
            limit_stocks=limit_data,
            quotes={},
        )
        
        # 获取实时quote信息
        # 从MongoDB获取最近数据
        daily_data = await mongo_manager.find_one(
            "stock_daily",
            {"ts_code": ts_code, "trade_date": trade_date},
        )
        
        if not daily_data:
            logger.error(f"❌ 未找到 {ts_code} 在 {trade_date} 的日线数据")
            return []
        
        logger.info(f"✓ 找到日线数据: {daily_data}")
        
        # 构造quote
        quote = {
            "price": daily_data.get("close", 0),
            "open": daily_data.get("open", 0),
            "high": daily_data.get("high", 0),
            "low": daily_data.get("low", 0),
            "pct_chg": daily_data.get("pct_chg", 0),
            "vol": daily_data.get("vol", 0),
            "amount": daily_data.get("amount", 0),
            "turnover": daily_data.get("turnover", 0),  # 换手率百分比
            "volume": daily_data.get("vol", 0) * 100,  # 手转股
            "volume_5d_avg": await get_5d_avg_volume(ts_code, trade_date),
            "name": stock_name,
        }
        
        snapshot.quotes[ts_code] = quote
        
        # 对于涨跌幅阈值，不需要 previous_snapshot
        # 大金重工 2026-03-16 pct_chg=-6.39 应该满足 threshold=6.0 direction=down
        result = await strategy.evaluate(subscription, snapshot, None)
        
        if result:
            logger.info(f"🎯 策略触发! {ts_code} {stock_name}")
            for alert in result:
                logger.info(f"   - {alert.reason}")
            alerts.extend(result)
        else:
            # 调试：输出实际数据看看
            quote_pct = quote.get('pct_chg', 0)
            logger.info(f"ℹ️  策略未触发。实际涨跌幅: {quote_pct:.2f}%")
    
    else:
        # 全市场搜索满足条件
        from core.protocols import MarketSnapshot
        
        snapshot = MarketSnapshot(
            trade_date=trade_date,
            timestamp=datetime.now().isoformat(),
            limit_stocks=limit_data,
            quotes={},
        )
        
        # 遍历涨跌停股票，获取数据
        count = 0
        matched = 0
        for ts_code in limit_data.keys():
            # 获取日线
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
            
            # 构造quote
            quote = {
                "price": daily_data.get("close", 0),
                "open": daily_data.get("open", 0),
                "pct_chg": daily_data.get("pct_chg", 0),
                "turnover": daily_data.get("turnover", 0),
                "volume": daily_data.get("vol", 0) * 100,
                "volume_5d_avg": await get_5d_avg_volume(ts_code, trade_date),
                "name": stock_name,
            }
            snapshot.quotes[ts_code] = quote
            count += 1
        
        logger.info(f"✓ 加载了 {count} 只涨跌停股票数据")
        
        # 执行评估
        result = await strategy.evaluate(subscription, snapshot, None)
        
        if result:
            logger.info(f"🎯 策略触发 {len(result)} 只股票:")
            for alert in result:
                logger.info(f"   - {alert.stock_name}({alert.ts_code}): {alert.reason}")
            alerts.extend(result)
        else:
            logger.info(f"ℹ️  没有股票满足条件")
    
    # 写入飞书
    if settings.feishu.enabled and alerts:
        for alert in alerts:
            success = await feishu_bitable_manager.write_alert(alert)
            if success:
                logger.info(f"✅ 已写入飞书多维表格: {alert.stock_name}")
            else:
                logger.error(f"❌ 写入飞书失败: {alert.stock_name}")
    
    logger.info(f"验证完成: {name}，触发 {len(alerts)} 个信号")
    return alerts

async def get_5d_avg_volume(ts_code: str, end_date: str) -> float:
    """获取5日平均成交量"""
    # 获取最近5个交易日
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
    return avg * 100  # 转股

async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("StockAgent 五大策略完整验证")
    logger.info("验证时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)
    
    # 初始化连接
    try:
        await init_connections()
    except Exception as e:
        logger.error(f"❌ 初始化失败: {e}")
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
    
    for result in all_results:
        status = "✅" if result["success"] else "❌"
        logger.info(f"{status} {result['name']}: 触发 {result['alerts']} 个信号")
    
    logger.info(f"\n📈 总计: {total_alerts} 个信号被触发并写入飞书")
    logger.info("=" * 60)
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
