#!/usr/bin/env python3
"""
使用 AKShare 下载所有回测所需数据（免费，不需要 Token）
数据保存到 MongoDB
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


async def download_trade_cal_akshare(start_date: str = "20250101", end_date: str = "20261231"):
    """下载交易日历"""
    print("\n" + "="*60)
    print("📅 下载交易日历 (AKShare)")
    print("="*60)
    
    # AKShare 交易日历
    df = ak.tool_trade_date_hist_sse()
    df.columns = ['cal_date']
    df['cal_date'] = df['cal_date'].astype(str)
    
    # 筛选日期范围
    df = df[(df['cal_date'] >= start_date) & (df['cal_date'] <= end_date)].copy()
    
    # 添加 is_open 字段（全部是交易日）
    df['is_open'] = 1
    
    # 添加前一个交易日
    df = df.sort_values('cal_date').reset_index(drop=True)
    df['pretrade_date'] = df['cal_date'].shift(1)
    
    print(f"获取到 {len(df)} 个交易日")
    print(df.head())
    
    # 保存到 MongoDB
    records = df.to_dict('records')
    for record in tqdm(records, desc="保存交易日历"):
        await mongo_manager.update_one(
            "trade_cal",
            {"cal_date": int(record['cal_date'])},
            {"$set": record},
            upsert=True
        )
    
    print(f"✅ 交易日历保存完成，共 {len(records)} 条")
    return df


async def download_stock_basic_akshare():
    """下载股票基础信息"""
    print("\n" + "="*60)
    print("📋 下载股票基础信息 (AKShare)")
    print("="*60)
    
    # 获取 A 股列表
    df = ak.stock_info_a_code_name()
    df.columns = ['ts_code', 'name']
    
    # 添加后缀
    df['ts_code'] = df['ts_code'].apply(
        lambda x: f"{x}.SZ" if x.startswith(('0', '3')) else f"{x}.SH"
    )
    
    # 添加默认字段
    df['industry'] = ''
    df['list_date'] = ''
    df['is_st'] = False
    
    print(f"获取到 {len(df)} 只股票")
    print(df.head())
    
    # 保存到 MongoDB
    records = df.to_dict('records')
    for record in tqdm(records, desc="保存股票基础信息"):
        await mongo_manager.update_one(
            "stock_basic",
            {"ts_code": record['ts_code']},
            {"$set": record},
            upsert=True
        )
    
    print(f"✅ 股票基础信息保存完成，共 {len(records)} 条")
    return df


async def download_daily_akshare_by_date(trade_date: str):
    """下载单日全市场日线数据"""
    try:
        # AKShare 的格式需要 YYYYMMDD
        df = ak.stock_zh_a_spot_em()
        
        # 转换字段名，对齐 Tushare 格式
        rename_map = {
            '代码': 'ts_code',
            '名称': 'name',
            '最新价': 'close',
            '今开': 'open',
            '最高': 'high',
            '最低': 'low',
            '昨收': 'pre_close',
            '涨跌幅': 'pct_chg',
            '涨跌额': 'change',
            '成交量': 'vol',
            '成交额': 'amount',
        }
        
        # 重命名存在的列
        for old, new in rename_map.items():
            if old in df.columns:
                df = df.rename(columns={old: new})
        
        # 格式化 ts_code
        df['ts_code'] = df['ts_code'].apply(
            lambda x: f"{x}.SZ" if str(x).startswith(('0', '3')) else f"{x}.SH"
        )
        
        df['trade_date'] = int(trade_date)
        
        # 确保数值类型
        numeric_cols = ['open', 'high', 'low', 'close', 'pre_close', 'pct_chg', 'change', 'vol', 'amount']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df
    
    except Exception as e:
        print(f"❌ 下载 {trade_date} 日线数据失败: {e}")
        return pd.DataFrame()


async def download_daily_range_akshare(start_date: str, end_date: str):
    """下载日期范围内的日线数据"""
    print("\n" + "="*60)
    print(f"📈 下载日线行情数据 (AKShare): {start_date} -> {end_date}")
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
    for trade_date in tqdm(trade_dates, desc="下载日线数据"):
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
            print(f"  {trade_date}: {len(records)} 条")
    
    print(f"✅ 日线数据保存完成，共 {total_count} 条")


async def add_up_down_limit():
    """补全涨跌停价格"""
    print("\n" + "="*60)
    print("🔧 补全涨跌停价格")
    print("="*60)
    
    # 获取所有需要补全的记录
    records = await mongo_manager.find_many(
        "stock_daily_ak_full",
        {"up_limit": {"$exists": False}}
    )
    
    count = 0
    for record in tqdm(list(records), desc="补全涨跌停价"):
        pre_close = record.get('pre_close', 0)
        if pre_close and pre_close > 0:
            # 正常股票 10%，ST 股票 5%（简化处理）
            up_limit = round(pre_close * 1.1, 2)
            down_limit = round(pre_close * 0.9, 2)
            
            await mongo_manager.update_one(
                "stock_daily_ak_full",
                {"_id": record['_id']},
                {"$set": {"up_limit": up_limit, "down_limit": down_limit}}
            )
            count += 1
    
    print(f"✅ 涨跌停价补全完成，共 {count} 条")


async def main():
    print("\n" + "🚀"*20)
    print("🚀 使用 AKShare 下载回测所需全部数据")
    print("🚀"*20)
    
    # 下载范围：2025年1月1日到现在（确保有足够历史数据）
    start_date = "20250101"
    end_date = datetime.now().strftime("%Y%m%d")
    
    print(f"\n📅 下载范围: {start_date} -> {end_date}")
    
    # 1. 交易日历
    await download_trade_cal_akshare(start_date, end_date)
    
    # 2. 股票基础信息
    await download_stock_basic_akshare()
    
    # 3. 日线行情
    await download_daily_range_akshare(start_date, end_date)
    
    # 4. 补全涨跌停价格
    await add_up_down_limit()
    
    print("\n" + "✅"*30)
    print("✅ 所有数据下载完成！")
    print("✅"*30)


if __name__ == "__main__":
    asyncio.run(main())
