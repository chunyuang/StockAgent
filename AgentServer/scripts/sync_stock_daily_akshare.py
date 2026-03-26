"""
手动同步指定日期范围的 stock_daily 数据 (使用 AKShare 数据源)

用法:
    cd AgentServer
    
    # 同步单个日期
    python scripts/sync_stock_daily_akshare.py --date 20260106
    
    # 同步时间段
    python scripts/sync_stock_daily_akshare.py --start 20251224 --end 20260324
"""

import asyncio
import argparse
import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import akshare as ak

from core.managers import mongo_manager


def generate_trade_dates_in_range(start_date: str, end_date: str) -> list:
    """生成日期范围内所有日期"""
    start_dt = datetime.strptime(start_date, "%Y%m%d")
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    
    dates = []
    current = start_dt
    while current <= end_dt:
        date_str = current.strftime("%Y%m%d")
        dates.append(date_str)
        current += timedelta(days=1)
    
    return dates


async def get_stock_basic_list() -> list:
    """获取当前正常上市的股票列表"""
    print("Getting stock list from AKShare...")
    stock_info = ak.stock_info_a_code_name()
    
    # AKShare 返回代码和名称，转换为 ts_code 格式 (带后缀)
    def add_suffix(code: str) -> str:
        if code.startswith(('6', '5', '9')):
            return f"{code}.SH"
        else:
            return f"{code}.SZ"
    
    stock_info['ts_code'] = stock_info['code'].apply(add_suffix)
    stock_list = stock_info['ts_code'].tolist()
    
    print(f"Found {len(stock_list)} listed stocks")
    return stock_list


async def sync_stock_daily_range(ts_codes: list, start_date: str, end_date: str) -> dict:
    """
    批量同步指定股票在时间范围内的日线数据
    
    Args:
        ts_codes: 股票代码列表
        start_date: 开始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD
    
    Returns:
        统计结果
    """
    total_synced = 0
    success_count = 0
    fail_count = 0
    
    total_stocks = len(ts_codes)
    print(f"\nStarting sync for {total_stocks} stocks from {start_date} to {end_date}...")
    
    for idx, ts_code in enumerate(ts_codes):
        # 转换 AKShare 格式 (去掉后缀)
        pure_code = ts_code.split('.')[0]
        
        try:
            # AKShare 获取历史行情
            # 注意: AKShare 使用 YYYY-MM-DD 格式
            start_date_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
            end_date_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
            
            df = ak.stock_zh_a_daily(symbol=pure_code, start_date=start_date_fmt, end_date=end_date_fmt, adjust="qfq")
            
            if df is None or df.empty:
                fail_count += 1
                if (idx + 1) % 50 == 0:
                    print(f"  Progress: {idx+1}/{total_stocks}, synced: {total_synced}, fails: {fail_count}")
                continue
            
            # 标准化列名匹配 Tushare 格式
            # AKShare 返回: date, open, high, low, close, volume
            df = df.reset_index()
            df.rename(columns={
                'date': 'trade_date',
                'volume': 'vol',
            }, inplace=True)
            
            # 转换 trade_date 为整型 YYYYMMDD
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime("%Y%m%d").astype(int)
            
            # 添加 ts_code
            df['ts_code'] = ts_code
            
            # 计算 pct_chg (涨跌幅)
            if 'pct_chg' not in df.columns:
                df['pct_chg'] = df['close'].pct_change() * 100
            
            # 删除缺失数据
            df = df.dropna(subset=['open', 'high', 'low', 'close', 'vol'])
            
            if df.empty:
                fail_count += 1
                continue
            
            # 批量写入
            records = df.to_dict("records")
            result = await mongo_manager.bulk_upsert(
                collection="stock_daily",
                documents=records,
                key_fields=["ts_code", "trade_date"],
            )
            
            count = result.get("upserted", 0) + result.get("modified", 0)
            total_synced += count
            success_count += 1
            
            if (idx + 1) % 20 == 0:
                print(f"  Progress: {idx+1}/{total_stocks}, synced: {total_synced}, fails: {fail_count}")
            
            # 限速，避免被封
            await asyncio.sleep(0.3)
            
        except Exception as e:
            fail_count += 1
            print(f"  ERROR: Failed to sync {ts_code}: {e}")
            continue
    
    return {
        "total_stocks": total_stocks,
        "success_stocks": success_count,
        "failed_stocks": fail_count,
        "total_records": total_synced,
    }


async def main(args):
    print("=" * 60)
    print("Stock Daily Data Sync Script (AKShare DataSource)")
    print("=" * 60)
    print("AKShare is free, no token required\n")
    
    # 初始化
    await mongo_manager.initialize()
    
    # 获取股票列表
    ts_codes = await get_stock_basic_list()
    
    # 同步范围
    start_date = args.start
    end_date = args.end
    
    print(f"\nSyncing from {start_date} to {end_date}...")
    
    # 批量同步
    result = await sync_stock_daily_range(ts_codes, start_date, end_date)
    
    # 汇总
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Total stocks processed: {result['total_stocks']}")
    print(f"  Success: {result['success_stocks']}")
    print(f"  Failed: {result['failed_stocks']}")
    print(f"  Total records synced: {result['total_records']}")
    print("\nDone!")
    
    # 关闭连接
    await mongo_manager.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync stock_daily via AKShare (free, no token needed)")
    parser.add_argument("--start", type=str, required=True, help="Start date (e.g., 20251224)")
    parser.add_argument("--end", type=str, required=True, help="End date (e.g., 20260324)")
    
    args = parser.parse_args()
    
    asyncio.run(main(args))
