#!/usr/bin/env python3
"""
统一扩展数据下载入口
自动处理路径问题，支持直接运行
"""
import sys
import os

# 自动添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'AgentServer'))
sys.path.insert(0, os.path.dirname(__file__))

import asyncio
import argparse
from datetime import datetime

from core.managers import mongo_manager
from backtest_module.data_download.akshare.extended.download_lhb_akshare import download_lhb_date_range, download_lhb_by_date
from backtest_module.data_download.akshare.extended.download_north_money_akshare import download_north_money_date_range, download_north_money_by_date
from backtest_module.data_download.akshare.extended.download_bid_auction_akshare import download_bid_auction_by_date

async def main():
    # 初始化MongoDB连接
    await mongo_manager.initialize()
    parser = argparse.ArgumentParser(description="扩展数据下载工具")
    parser.add_argument("--type", required=True, choices=["lhb", "north", "auction"], help="数据类型")
    parser.add_argument("--date", help="指定日期(YYYYMMDD)")
    parser.add_argument("--start", help="开始日期(YYYYMMDD)")
    parser.add_argument("--end", help="结束日期(YYYYMMDD)")
    
    args = parser.parse_args()
    
    if args.date:
        if args.type == "lhb":
            await download_lhb_by_date(args.date)
        elif args.type == "north":
            await download_north_money_by_date(args.date)
        elif args.type == "auction":
            await download_bid_auction_by_date(args.date)
    
    elif args.start and args.end:
        if args.type == "lhb":
            await download_lhb_date_range(args.start, args.end)
        elif args.type == "north":
            await download_north_money_date_range(args.start, args.end)
    
    else:
        # 默认下载最近一个交易日数据
        latest_date = datetime.now().strftime("%Y%m%d")
        print(f"未指定日期，下载最近交易日[{latest_date}]数据")
        if args.type == "lhb":
            await download_lhb_by_date(latest_date)
        elif args.type == "north":
            await download_north_money_by_date(latest_date)
        elif args.type == "auction":
            await download_bid_auction_by_date(latest_date)

if __name__ == "__main__":
    asyncio.run(main())
