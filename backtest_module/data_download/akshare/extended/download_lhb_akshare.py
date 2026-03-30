"""
AKShare 龙虎榜数据下载脚本
数据源：东方财富网龙虎榜数据
免费无Token限制
"""
import sys
import asyncio
from datetime import datetime, timedelta
import akshare as ak
import pandas as pd

sys.path.insert(0, '.')
from core.managers import mongo_manager
from common.utils import date_utils
import logging

logger = logging.getLogger(__name__)

COLLECTION_NAME = "stock_lhb"


async def download_lhb_by_date(trade_date: str) -> int:
    """
    下载指定日期的龙虎榜数据
    trade_date格式：YYYYMMDD
    返回：新增/更新的记录数
    """
    try:
        # 转换日期格式为YYYY-MM-DD（AKShare需要）
        dt = datetime.strptime(trade_date, "%Y%m%d")
        ak_date = dt.strftime("%Y%m%d")
        
        logger.info(f"开始下载 {ak_date} 龙虎榜数据")
        
        # 调用AKShare接口
        df = ak.stock_lhb_gg_em(date=ak_date)
        
        if df.empty:
            logger.info(f"{ak_date} 无龙虎榜数据")
            return 0
        
        # 数据清洗和格式转换
        df = df.rename(columns={
            "序号": "rank",
            "代码": "ts_code",
            "名称": "name",
            "收盘价": "close",
            "涨跌幅": "pct_chg",
            "成交额": "amount",
            "净买入额": "net_buy_amount",
            "买入金额最大的前5名买入总计": "buy_amount_top5",
            "卖出金额最大的前5名卖出总计": "sell_amount_top5",
            "解读": "interpretation",
            "上榜原因": "reason",
        })
        
        # 统一格式
        df["ts_code"] = df["ts_code"].apply(lambda x: f"{x}.SH" if x.startswith("6") else f"{x}.SZ")
        df["trade_date"] = int(trade_date)
        df["update_time"] = datetime.now()
        
        # 转换为字典列表
        records = df.to_dict("records")
        
        # 写入MongoDB：先删除当日旧数据，再插入新数据
        await mongo_manager.delete_many(COLLECTION_NAME, {"trade_date": int(trade_date)})
        await mongo_manager.insert_many(COLLECTION_NAME, records)
        
        logger.info(f"成功下载 {ak_date} 龙虎榜数据，共{len(records)}条记录")
        return len(records)
    
    except Exception as e:
        logger.error(f"下载 {trade_date} 龙虎榜数据失败: {e}", exc_info=True)
        return 0


async def download_lhb_date_range(start_date: str, end_date: str) -> int:
    """
    下载日期范围内的龙虎榜数据
    start_date/end_date格式：YYYYMMDD
    """
    trade_dates = date_utils.get_trade_dates(start_date, end_date)
    total = 0
    
    for trade_date in trade_dates:
        count = await download_lhb_by_date(trade_date)
        total += count
        # 防限流
        await asyncio.sleep(0.2)
    
    logger.info(f"日期范围 {start_date}~{end_date} 龙虎榜数据下载完成，共{total}条记录")
    return total


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="下载龙虎榜数据")
    parser.add_argument("--date", help="指定日期(YYYYMMDD)，默认下载最近一个交易日")
    parser.add_argument("--start", help="开始日期(YYYYMMDD)")
    parser.add_argument("--end", help="结束日期(YYYYMMDD)")
    
    args = parser.parse_args()
    
    async def main():
        if args.start and args.end:
            await download_lhb_date_range(args.start, args.end)
        elif args.date:
            await download_lhb_by_date(args.date)
        else:
            # 默认下载最近一个交易日
            latest_trade_date = date_utils.get_latest_trade_date()
            await download_lhb_by_date(latest_trade_date)
    
    asyncio.run(main())
