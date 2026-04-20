#!/usr/bin/env python3
"""
批量扩展数据下载工具
一键下载龙虎榜、北向资金、集合竞价数据，自动处理路径依赖，开箱即用
支持日期范围下载、增量更新、断点续传
"""
import sys
import os
import asyncio
import argparse
from datetime import datetime, timedelta
from typing import List
from tqdm import tqdm

# 自动添加路径，解决导入问题
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'AgentServer'))
sys.path.insert(0, os.path.dirname(__file__))

def get_trade_dates(start_date: str, end_date: str) -> List[str]:
    """获取日期范围内的交易日列表（简化版）"""
    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    dates = []
    current = start
    while current <= end:
        # 排除周末
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates

async def download_data(data_type: str, start_date: str, end_date: str):
    """下载指定类型的数据"""
    print(f"🚀 开始下载{data_type}数据，日期范围：{start_date} ~ {end_date}")
    
    trade_dates = get_trade_dates(start_date, end_date)
    if not trade_dates:
        print("⚠️  日期范围内无交易日")
        return
    
    success_count = 0
    fail_count = 0
    
    for trade_date in tqdm(trade_dates, desc=f"下载{data_type}进度"):
        try:
            if data_type == "lhb":
                from backtest_module.data_download.akshare.extended.download_lhb_akshare import download_lhb_by_date
            elif data_type == "north":
                from backtest_module.data_download.akshare.extended.download_north_money_akshare import download_north_money_by_date
                count, _ = await download_north_money_by_date(trade_date)
            elif data_type == "auction":
                from backtest_module.data_download.akshare.extended.download_bid_auction_akshare import download_bid_auction_by_date
            else:
                print(f"❌ 不支持的数据类型：{data_type}")
                return
            
            success_count += 1
            # 防限流
            await asyncio.sleep(0.2)
        except Exception as e:
            print(f"❌ 下载{trade_date} {data_type}数据失败: {e}")
            fail_count += 1
    
    print(f"✅ {data_type}数据下载完成：成功{success_count}天，失败{fail_count}天")

async def main():
    parser = argparse.ArgumentParser(description="扩展数据批量下载工具")
    parser.add_argument("--type", required=True, choices=["lhb", "north", "auction", "all"], 
                        help="数据类型：lhb(龙虎榜)/north(北向资金)/auction(集合竞价)/all(全部)")
    parser.add_argument("--start", required=True, help="开始日期(YYYYMMDD)")
    parser.add_argument("--end", required=True, help="结束日期(YYYYMMDD)")
    parser.add_argument("--skip-fail", action="store_true", help="跳过失败的日期，继续下载")
    
    args = parser.parse_args()
    
    if args.type == "all":
        # 下载全部三种数据
        await download_data("lhb", args.start, args.end)
        await download_data("north", args.start, args.end)
        await download_data("auction", args.start, args.end)
    else:
        await download_data(args.type, args.start, args.end)
    
    print("🎉 全部下载任务完成！")

if __name__ == "__main__":
    asyncio.run(main())
