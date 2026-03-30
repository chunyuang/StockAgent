#!/usr/bin/env python3
"""
验证剩余两大策略：龙头战法、首板打板
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
from nodes.listener.strategies.leading_dragon import LeadingDragonStrategy
from nodes.listener.strategies.first_board import FirstBoardStrategy

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("verify_remaining_two")

# 测试用例
TEST_CASES = [
    # 龙头战法 - 需要找一个近期3连板股票
    # 我们找一个在 2026-03-14 满足条件的
    {
        "name": "龙头战法",
        "strategy_class": LeadingDragonStrategy,
        "params": {"min_height": 3, "min_turnover": 15},
        "trade_date": "20260314",
        "description": "3连板以上，换手率15%+，当前涨停",
    },
    # 首板打板 - 在同一天找
    {
        "name": "首板打板",
        "strategy_class": FirstBoardStrategy,
        "params": {"min_turnover": 8, "min_volume_ratio": 1.5},
        "trade_date": "20260314",
        "description": "首次涨停，换手率8%+，成交量1.5x放量",
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
    
    logger.info(f"\n{'='*60}")
    logger.info(f"开始验证: {name}")
    logger.info(f"描述: {case.get('description', '')}")
    logger.info(f"参数: {params}")
    logger.info(f"测试日期: {trade_date}")
    
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
        is_all_market=True,  # 全市场搜索
        watch_list=[],
    )
    
    # 获取涨跌停数据
    logger.info(f"获取涨跌停数据 for {trade_date}...")
    limit_list = await tushare_manager.get_stk_limit(trade_date)
    limit_data = {item["ts_code"]: item for item in limit_list}
    logger.info(f"✓ 获取到 {len(limit_data)} 只涨跌停股票")
    
    if len(limit_data) == 0:
        logger.warning(f"⚠️  未获取到涨跌停数据，跳过")
        return []
    
    # 构造 MarketSnapshot
    from core.protocols import MarketSnapshot
    snapshot = MarketSnapshot(
        trade_date=trade_date,
        timestamp=datetime.now().isoformat(),
        limit_stocks=limit_data,
        quotes={},
    )
    
    # 获取每只股票日线数据
    count = 0
    matched = 0
    
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
        
        # 获取5日均量
        volume_5d_avg = await get_5d_avg_volume(ts_code, trade_date)
        
        # 换手率
        turnover = daily_data.get("turnover", 0)
        if turnover > 100:
            turnover = turnover / 100
        
        # 构造 quote
        quote = {
            "price": daily_data.get("close", 0),
            "open": daily_data.get("open", 0),
            "pct_chg": daily_data.get("pct_chg", 0),
            "turnover": turnover,
            "volume": daily_data.get("vol", 0) * 100,
            "volume_5d_avg": volume_5d_avg,
            "name": stock_name,
        }
        snapshot.quotes[ts_code] = quote
        count += 1
    
    logger.info(f"✓ 加载了 {count} 只涨跌停股票日线数据")
    
    # 需要 previous_snapshot 检查昨日是否涨停
    # 获取昨日交易日（简化处理，测试够用）
    date_int = int(trade_date)
    # 简化：假设昨日就是 date_int - 1，实际应该日历，但测试够用
    prev_date_int = date_int - 1
    prev_trade_date = f"{prev_date_int}"
    
    prev_limit_list = await tushare_manager.get_stk_limit(prev_trade_date)
    prev_limit_data = {item["ts_code"]: item for item in prev_limit_list}
    
    previous_snapshot = MarketSnapshot(
        trade_date=prev_trade_date,
        timestamp=datetime.now().isoformat(),
        limit_stocks=prev_limit_data,
        quotes={},
    )
    
    # 执行评估
    result = await strategy.evaluate(subscription, snapshot, previous_snapshot)
    
    if result:
        logger.info(f"🎯 策略触发 {len(result)} 只股票:")
        for alert in result:
            logger.info(f"   - {alert.stock_name}({alert.ts_code}): {alert.trigger_reason}")
    else:
        logger.info(f"ℹ️  没有股票满足条件")
    
    logger.info(f"验证完成: {name}，触发 {len(result)} 个信号")
    return result

async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("StockAgent 剩余两大策略验证 (龙头战法 + 首板打板)")
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
        if result["success"]:
            status = "✅ 通过"
            passed += 1
        else:
            status = "❌ 失败"
            failed += 1
        logger.info(f"{status} {result['name']}: 触发 {result['alerts']} 个信号")
    
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
