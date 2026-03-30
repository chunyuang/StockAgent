"""
AKShare 集合竞价数据下载脚本
数据源：东方财富网A股实时行情（9:25集合竞价结束后获取当日竞价数据）
包含：开盘价、竞价量、未匹配量、竞价涨幅
免费无Token限制
"""
import sys
import asyncio
from datetime import datetime, timedelta
import akshare as ak
import pandas as pd

sys.path.insert(0, '.')
from core.managers import mongo_manager
import logging

logger = logging.getLogger(__name__)

COLLECTION_NAME = "stock_bid_auction"


async def download_bid_auction_by_date(trade_date: str = None) -> int:
    """
    下载指定日期的集合竞价数据
    trade_date格式：YYYYMMDD，不填默认取当前交易日（需在9:25之后运行）
    返回：新增/更新的记录数
    """
    try:
        if not trade_date:
            trade_date = date_utils.get_current_trade_date()
        
        logger.info(f"开始下载 {trade_date} 集合竞价数据")
        
        # 调用AKShare接口获取当前全部A股实时行情（包含集合竞价数据）
        df = ak.stock_zh_a_spot_em()
        
        if df.empty:
            logger.error(f"获取竞价数据失败，返回为空")
            return 0
        
        # 数据清洗和格式转换
        df = df.rename(columns={
            "代码": "ts_code",
            "名称": "name",
            "最新价": "open",  # 9:25时最新价就是开盘竞价价
            "涨跌幅": "auction_pct_chg",
            "成交量": "auction_volume",  # 竞价成交量（手）
            "成交额": "auction_amount",  # 竞价成交额（元）
        })
        
        # 计算未匹配量（通过买卖盘差估算，后续可扩展更精确的数据源）
        if "买一量" in df.columns and "卖一量" in df.columns:
            df["unmatched_volume"] = df["卖一量"] - df["买一量"]
        else:
            df["unmatched_volume"] = 0
        
        # 统一格式
        df["ts_code"] = df["ts_code"].apply(lambda x: f"{x}.SH" if x.startswith("6") else f"{x}.SZ")
        df["trade_date"] = int(trade_date)
        df["update_time"] = datetime.now()
        
        # 过滤掉科创板、北交所等非主板标的
        df = df[~df["ts_code"].str.startswith("688") & ~df["ts_code"].str.startswith("8") & ~df["ts_code"].str.startswith("4")]
        
        # 转换为字典列表
        records = df.to_dict("records")
        
        # 写入MongoDB：先删除当日旧数据，再插入新数据
        await mongo_manager.delete_many(COLLECTION_NAME, {"trade_date": int(trade_date)})
        await mongo_manager.insert_many(COLLECTION_NAME, records)
        
        logger.info(f"成功下载 {trade_date} 集合竞价数据，共{len(records)}条记录")
        return len(records)
    
    except Exception as e:
        logger.error(f"下载 {trade_date} 集合竞价数据失败: {e}", exc_info=True)
        return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="下载集合竞价数据")
    parser.add_argument("--date", help="指定日期(YYYYMMDD)，默认当前交易日（需9:25后运行）")
    
    args = parser.parse_args()
    
    async def main():
        if args.date:
            await download_bid_auction_by_date(args.date)
        else:
            await download_bid_auction_by_date()
    
    asyncio.run(main())
