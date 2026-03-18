"""
运行每日复盘

使用方式:
    python scripts/run_review.py
    python scripts/run_review.py --date 20260305
    python scripts/run_review.py --push
"""

import asyncio
import argparse
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


async def run_review(
    trade_date: str = None,
    push: bool = False,
):
    """
    运行复盘工作流
    
    Args:
        trade_date: 交易日期
        push: 是否推送到企业微信
    """
    # 初始化
    from core.managers import data_source_manager
    from core.llm import llm_service
    from src.workflows import ReviewWorkflow, ReviewReportFormatter, ReviewReportPusher
    
    logger.info("Initializing...")
    
    # 初始化数据源
    await data_source_manager.initialize()
    
    # 获取交易日期
    if not trade_date:
        trade_date, _ = await data_source_manager.get_latest_trade_date()
    
    logger.info(f"Running review for {trade_date}")
    
    # 创建工作流
    workflow = ReviewWorkflow(llm_service)
    
    # 执行（返回 ReviewState dict）
    start_time = datetime.now()
    result = await workflow.run(trade_date=trade_date)
    elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
    
    # 检查是否成功（通过 errors 字段判断）
    errors = result.get("errors", [])
    success = len(errors) == 0 and result.get("report") is not None
    
    if success:
        logger.info(f"Review workflow completed successfully in {elapsed_ms:.1f}ms")
        
        # 格式化输出
        formatter = ReviewReportFormatter()
        markdown = formatter.to_markdown(result)
        
        print("\n" + "=" * 60)
        print(markdown)
        print("=" * 60 + "\n")
        
        # 推送
        if push:
            pusher = ReviewReportPusher()
            push_result = await pusher.push_review_report(result)
            logger.info(f"Push result: {push_result}")
    else:
        logger.error(f"Review workflow failed: {errors}")
        
        # 输出各维度状态
        for key in ["market_result", "sector_result", "limit_result", 
                    "linkage_result", "sentiment_result"]:
            value = result.get(key)
            status = "completed" if value else "failed"
            logger.info(f"  {key}: {status}")
    
    # 关闭
    await data_source_manager.shutdown()
    
    return result


async def collect_data(trade_date: str = None):
    """
    采集复盘数据（如果尚未采集）
    """
    from core.managers import data_source_manager
    from nodes.data_sync.collectors.stock import ReviewDataCollector
    
    logger.info("Collecting review data...")
    
    await data_source_manager.initialize()
    
    collector = ReviewDataCollector()
    result = await collector.collect()
    
    logger.info(f"Collection result: {result}")
    
    await data_source_manager.shutdown()
    
    return result


def main():
    parser = argparse.ArgumentParser(description="运行每日复盘")
    parser.add_argument("--date", type=str, help="交易日期 (YYYYMMDD)")
    parser.add_argument("--push", action="store_true", help="推送到企业微信")
    parser.add_argument("--collect", action="store_true", help="先采集数据")
    
    args = parser.parse_args()
    
    async def _run():
        if args.collect:
            await collect_data(args.date)
        
        await run_review(args.date, args.push)
    
    asyncio.run(_run())


if __name__ == "__main__":
    main()
