#!/usr/bin/env python3
"""
刷新预计算交易日历表 trade_calendar

功能：
- 从 stock_daily_ak_full 集合提取所有 distinct 交易日
- 写入 trade_calendar 集合，覆盖原有数据
- 执行完成后，后续回测会自动从 trade_calendar 查询，几毫秒返回

用法：
cd AgentServer && python ../scripts/refresh_trade_calendar.py
"""

import asyncio
import logging
import sys
import os

# 添加 AgentServer 目录到 Python 路径，让 core 模块能被找到
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
agent_server_dir = os.path.join(project_root, 'AgentServer')
sys.path.insert(0, agent_server_dir)

from core.managers import mongo_manager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)


async def refresh_trade_calendar():
    """刷新交易日历"""
    logger.info("=" * 60)
    logger.info("🚀 Starting refresh trade_calendar...")
    logger.info("=" * 60)
    
    # 初始化 MongoDB 连接
    await mongo_manager.initialize()
    
    # 第一步：从 stock_daily_ak_full 获取所有 distinct 交易日
    logger.info("📊 Step 1: Getting all distinct trade dates from stock_daily_ak_full...")
    logger.info("   This may take 30 seconds to 2 minutes depending on data size, please wait...")
    
    pipeline = [
        {"$group": {"_id": "$trade_date"}},
        {"$sort": {"_id": 1}}
    ]
    
    result = await mongo_manager.aggregate("stock_daily_ak_full", pipeline)
    all_dates = [doc["_id"] for doc in result]
    logger.info(f"✅ Found {len(all_dates)} distinct trade dates")
    
    if not all_dates:
        logger.error("❌ No trade dates found in stock_daily_ak_full!")
        return False
    
    # 第二步：清空旧数据
    logger.info("🧹 Step 2: Clearing old data in trade_calendar...")
    # 删除所有文档
    await mongo_manager.delete_many("trade_calendar", {})
    
    # 第三步：插入新数据
    logger.info(f"📝 Step 3: Inserting {len(all_dates)} trade dates to trade_calendar...")
    
    docs = []
    for date_int in all_dates:
        docs.append({"trade_date": date_int})
    
    # 批量插入
    if docs:
        result = await mongo_manager.insert_many("trade_calendar", docs)
        # mongo_manager.insert_many 返回插入的文档列表
        inserted = len(result) if result else 0
        logger.info(f"✅ Inserted {inserted} trade dates to trade_calendar")
    else:
        logger.error("❌ No documents to insert!")
        return False
    
    # 第四步：验证结果
    logger.info("🔍 Step 4: Verifying result...")
    count = await mongo_manager.count_documents("trade_calendar", {})
    logger.info(f"✅ trade_calendar now has {count} documents total")
    
    logger.info("=" * 60)
    logger.info("🎉 refresh_trade_calendar completed successfully!")
    logger.info("📝 All future backtests will use precomputed calendar and be very fast.")
    logger.info("=" * 60)
    
    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(refresh_trade_calendar())
        exit(0 if success else 1)
    except Exception as e:
        logger.exception("💥 Failed to refresh trade_calendar")
        exit(1)
