#!/usr/bin/env python3
"""
简化版回测前检查，同步执行，避免异步问题
"""
import logging
import pymongo
from typing import Dict

logger = logging.getLogger(__name__)
client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']

def pre_flight_check(config: Dict) -> bool:
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
    
    # 2. 检查策略条件逻辑矛盾
    strategies = config.get("strategies", [])
    for strategy in strategies:
        filters = strategy.get("filters", [])
        filter_names = [f[0] for f in filters]
        # 首板打板不能同时要求limit_up_yesterday=1和first_limit_up=1（昨日已经涨停不可能是今日首板）
        has_limit_up_yesterday = any(f[0] == "limit_up_yesterday" and f[1] == 1 for f in filters)
        has_first_limit_up = any(f[0] == "first_limit_up" and f[1] == 1 for f in filters)
        if has_limit_up_yesterday and has_first_limit_up:
            raise ValueError(f"❌ 策略[{strategy['name']}]逻辑矛盾: 同时要求昨日涨停和今日首板，条件互斥")
    logger.info(f"✅ 策略逻辑检查通过: 共{len(strategies)}个策略，无逻辑矛盾")
    
    # 3. 检查流动性阈值单位匹配
    liquidity_threshold = config.get("liquidity_threshold", 0)
    if liquidity_threshold > 100000:  # 超过10亿说明可能单位错误（把万元当成元）
        raise ValueError(f"❌ 流动性阈值异常: {liquidity_threshold}万元，可能单位错误，正常范围应该是100~10000万元")
    logger.info(f"✅ 流动性阈值检查通过: {liquidity_threshold}万元")
    
    logger.info("✅ 所有回测前检查通过！")
    logger.info("="*60)
    return True

# 测试用
if __name__ == "__main__":
    pre_flight_check({
        "data_collection": "stock_daily_ak_full",
        "strategies": [
            {"name": "首板打板", "filters": [("first_limit_up", 1)]},
            {"name": "半路追涨", "filters": [("limit_up_yesterday", 1), ("open_below_limit", 1)]}
        ],
        "liquidity_threshold": 1000,
    })
