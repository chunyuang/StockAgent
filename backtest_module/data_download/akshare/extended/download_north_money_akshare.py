"""
AKShare 北向资金数据下载脚本
数据源：东方财富网沪深港通数据
包含：每日北向资金净流入、十大成交股
免费无Token限制
"""
import sys
import asyncio
from datetime import datetime, timedelta
import akshare as ak
import pandas as pd

sys.path.insert(0, '.')
from core.managers import mongo_manager
from utils import date_utils
import logging

logger = logging.getLogger(__name__)

# 北向资金每日概况集合
COLLECTION_DAILY = "stock_north_money_daily"
# 北向资金十大成交股集合
COLLECTION_STOCK = "stock_north_money_stock"


async def download_north_money_by_date(trade_date: str) -> tuple[int, int]:
    """
    下载指定日期的北向资金数据
    trade_date格式：YYYYMMDD
    返回：(概况记录数, 个股记录数)
    """
    try:
        # 转换日期格式为YYYY-MM-DD（AKShare需要）
        dt = datetime.strptime(trade_date, "%Y%m%d")
        ak_date = dt.strftime("%Y%m%d")
        
        logger.info(f"开始下载 {ak_date} 北向资金数据")
        
        # 1. 下载北向资金每日概况
        df_daily = ak.stock_hsgt_north_em()
        
        # 2. 下载北向资金十大成交股
        df_stock = ak.stock_hsgt_hold_stock_em(market="沪股通", start_date=ak_date, end_date=ak_date)
        df_sz = ak.stock_hsgt_hold_stock_em(market="深股通", start_date=ak_date, end_date=ak_date)
        df_stock = pd.concat([df_stock, df_sz], ignore_index=True)
        
        daily_count = 0
        stock_count = 0
        
        # 处理每日概况
        if not df_daily.empty:
            df_daily = df_daily.rename(columns={
                "日期": "trade_date",
                "北向资金-当日净流入": "net_inflow",
                "北向资金-当日余额": "balance",
                "北向资金-历史累计净流入": "total_net_inflow",
                "上证指数-涨跌幅": "sh_pct_chg",
                "深证成指-涨跌幅": "sz_pct_chg",
            })
            df_daily["trade_date"] = int(trade_date)
            df_daily["update_time"] = datetime.now()
            
            records = df_daily.to_dict("records")
            await mongo_manager.delete_many(COLLECTION_DAILY, {"trade_date": int(trade_date)})
            await mongo_manager.insert_many(COLLECTION_DAILY, records)
            daily_count = len(records)
            logger.info(f"成功下载 {ak_date} 北向资金概况，共{daily_count}条记录")
        
        # 处理十大成交股
        if not df_stock.empty:
            df_stock = df_stock.rename(columns={
                "日期": "trade_date",
                "代码": "ts_code",
                "名称": "name",
                "收盘价": "close",
                "涨跌幅": "pct_chg",
                "北向资金持股量": "hold_shares",
                "持股市值": "hold_value",
                "占总股本比例": "hold_ratio",
            })
            df_stock["ts_code"] = df_stock["ts_code"].apply(lambda x: f"{x}.SH" if x.startswith("6") else f"{x}.SZ")
            df_stock["trade_date"] = int(trade_date)
            df_stock["update_time"] = datetime.now()
            
            records = df_stock.to_dict("records")
            await mongo_manager.delete_many(COLLECTION_STOCK, {"trade_date": int(trade_date)})
            await mongo_manager.insert_many(COLLECTION_STOCK, records)
            stock_count = len(records)
            logger.info(f"成功下载 {ak_date} 北向资金个股数据，共{stock_count}条记录")
        
        return daily_count, stock_count
    
    except Exception as e:
        logger.error(f"下载 {trade_date} 北向资金数据失败: {e}", exc_info=True)
        return 0, 0


async def download_north_money_date_range(start_date: str, end_date: str) -> tuple[int, int]:
    """
    下载日期范围内的北向资金数据
    start_date/end_date格式：YYYYMMDD
    """
    trade_dates = date_utils.get_trade_dates(start_date, end_date)
    total_daily = 0
    total_stock = 0
    
    for trade_date in trade_dates:
        daily_count, stock_count = await download_north_money_by_date(trade_date)
        total_daily += daily_count
        total_stock += stock_count
        # 防限流
        await asyncio.sleep(0.2)
    
    logger.info(f"日期范围 {start_date}~{end_date} 北向资金数据下载完成，概况{total_daily}条，个股{total_stock}条")
    return total_daily, total_stock


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="下载北向资金数据")
    parser.add_argument("--date", help="指定日期(YYYYMMDD)，默认下载最近一个交易日")
    parser.add_argument("--start", help="开始日期(YYYYMMDD)")
    parser.add_argument("--end", help="结束日期(YYYYMMDD)")
    
    args = parser.parse_args()
    
    async def main():
        if args.start and args.end:
            await download_north_money_date_range(args.start, args.end)
        elif args.date:
            await download_north_money_by_date(args.date)
        else:
            # 默认下载最近一个交易日
            latest_trade_date = date_utils.get_latest_trade_date()
            await download_north_money_by_date(latest_trade_date)
    
    asyncio.run(main())
