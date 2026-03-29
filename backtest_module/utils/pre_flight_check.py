#!/usr/bin/env python3
"""
回测前自动检查清单
不满足条件直接报错退出，禁止运行回测
"""
import logging
from typing import Dict, List
from core.managers import mongo_manager

logger = logging.getLogger(__name__)

async def pre_flight_check(config: Dict) -> bool:
    """
    回测前强制检查，返回True表示所有检查通过，否则抛出异常
    """
    logger.info("="*60)
    logger.info("🚀 执行回测前强制检查...")
    
    # 1. 检查数据源集合
    allowed_collections = ["stock_daily_ak_full", "stock_daily_ts"]
    data_collection = config.get("data_collection", "")
    if data_collection not in allowed_collections:
        raise ValueError(f"❌ 非法数据源集合: {data_collection}，必须使用全市场集合: {allowed_collections}")
    logger.info(f"✅ 数据源集合检查通过: {data_collection}")
    
    # 2. 检查数据完整性
    start_date = config.get("start_date", 0)
    end_date = config.get("end_date", 0)
    if start_date == 0 or end_date == 0:
        raise ValueError(f"❌ 回测日期未配置: start_date={start_date}, end_date={end_date}")
    
    # 统计日期范围内的记录数
    from core.managers import mongo_manager
    await mongo_manager.initialize()
    coll = mongo_manager.db['stock_daily_ak_full']
    total_days = len(coll.distinct("trade_date", {
        "trade_date": {"$gte": start_date, "$lte": end_date}
    }))
    expected_days = (end_date - start_date) // 10000 * 365 + ((end_date % 10000) // 100 - (start_date % 10000) // 100) * 30 + (end_date % 100 - start_date % 100)
    expected_days = int(expected_days * 0.7)  # 交易日占自然日70%
    
    if total_days < expected_days:
        raise ValueError(f"❌ 数据完整性不足: 日期范围内仅{total_days}个交易日，预期至少{expected_days}个")
    logger.info(f"✅ 数据完整性检查通过: 日期范围内共{total_days}个交易日")
    
    # 3. 检查策略条件逻辑矛盾
    strategies = config.get("strategies", [])
    for strategy in strategies:
        filters = strategy.get("filters", [])
        filter_names = [f[0] for f in filters]
        # 首板打板不能同时要求limit_up_yesterday和first_limit_up
        if "first_limit_up" in filter_names and "limit_up_yesterday" in filter_names:
            raise ValueError(f"❌ 策略[{strategy['name']}]逻辑矛盾: 同时要求昨日涨停和今日首板，条件互斥")
        # 其他矛盾检查可以继续扩展
    logger.info(f"✅ 策略逻辑检查通过: 共{len(strategies)}个策略，无逻辑矛盾")
    
    # 4. 检查流动性阈值单位匹配
    liquidity_threshold = config.get("liquidity_threshold", 0)
    if liquidity_threshold > 100000:  # 超过10亿说明可能单位错误（把万元当成元）
        raise ValueError(f"❌ 流动性阈值异常: {liquidity_threshold}万元，可能单位错误，正常范围应该是100~10000万元")
    logger.info(f"✅ 流动性阈值检查通过: {liquidity_threshold}万元")
    
    logger.info("✅ 所有回测前检查通过！")
    logger.info("="*60)
    return True
