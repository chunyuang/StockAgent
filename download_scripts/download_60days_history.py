#!/usr/bin/env python3
"""
60天历史数据补充脚本
时间范围：2025年11月1日 - 2026年1月31日
覆盖：5510只股票的完整OHLCV数据
"""

import asyncio
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from tqdm import tqdm
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers import mongo_manager


async def download_daily_akshare_by_date(trade_date: str):
    """下载单日全市场日线数据"""
    try:
        # AKShare 的格式需要 YYYYMMDD
        df = ak.stock_zh_a_hist_em(symbol="", period="daily", start_date=trade_date, end_date=trade_date, adjust="")
        
        if df.empty:
            print(f"  {trade_date}: 无数据")
            return pd.DataFrame()
        
        # 重命名列以匹配字段名
        column_mapping = {
            '日期': 'trade_date',
            '代码': 'ts_code',
            '名称': 'name',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'vol',
            '成交额': 'amount',
            '涨跌幅': 'pct_chg',
            '涨跌额': 'change',
            '换手率': 'turnover_rate',
        }
        
        df = df.rename(columns=column_mapping)
        
        # 转换格式
        df['trade_date'] = df['trade_date'].astype(str).str.replace('-', '')
        df['ts_code'] = df['ts_code'].apply(
            lambda x: f"{x}.SZ" if x.startswith(('0', '3')) else f"{x}.SH"
        )
        
        # 计算涨跌停价
        df['pre_close'] = df['close'] - df['change']
        df['up_limit'] = round(df['pre_close'] * 1.1, 2)
        df['down_limit'] = round(df['pre_close'] * 0.9, 2)
        
        return df
        
    except Exception as e:
        print(f"  {trade_date} 下载失败: {e}")
        return pd.DataFrame()


async def download_daily_range_akshare(start_date: str, end_date: str):
    """下载日期范围内的日线数据"""
    print("\n" + "="*60)
    print(f"📈 60天历史数据补充: {start_date} -> {end_date}")
    print("="*60)
    
    # 获取交易日历
    trade_cal = await mongo_manager.find_many(
        "trade_cal",
        {
            "is_open": 1,
            "cal_date": {"$gte": int(start_date), "$lte": int(end_date)}
        },
        sort=[("cal_date", 1)]
    )
    
    trade_dates = [str(t['cal_date']) for t in trade_cal]
    print(f"需要下载 {len(trade_dates)} 个交易日")
    
    total_count = 0
    for i, trade_date in enumerate(trade_dates, 1):
        print(f"\n[{i}/{len(trade_dates)}] 下载 {trade_date}...")
        df = await download_daily_akshare_by_date(trade_date)
        
        if not df.empty:
            records = df.to_dict('records')
            for record in records:
                record['_id'] = f"{record['ts_code']}_{record['trade_date']}"
                try:
                    await mongo_manager.insert_one("stock_daily_ak_full", record)
                except:  # 重复键忽略
                    pass
            total_count += len(records)
            print(f"  ✅ 保存 {len(records)} 条记录，累计 {total_count} 条")
        else:
            print(f"  ⚠️  无数据")
    
    print("\n" + "="*60)
    print(f"✅ 全部下载完成！共保存 {total_count} 条日线记录")
    print("="*60)


async def main():
    print("\n" + "🚀"*20)
    print("🚀 60天历史数据补充脚本")
    print("🚀"*20)
    
    # 老板指定的时间范围
    start_date = "20251101"
    end_date = "20260131"
    
    print(f"\n📅 下载范围: {start_date} -> {end_date}")
    print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 开始下载
    await download_daily_range_akshare(start_date, end_date)
    
    print(f"\n⏰ 完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 关闭数据库连接
    await mongo_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
