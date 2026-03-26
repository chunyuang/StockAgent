"""
手动同步指定日期范围的 stock_daily 数据 (使用比盈数据源)

用法:
    cd AgentServer
    
    # 同步单个日期
    python scripts/sync_stock_daily_biying.py --date 20260106
    
    # 同步时间段
    python scripts/sync_stock_daily_biying.py --start 20260106 --end 20260109
"""

import asyncio
import argparse
import sys
import os
from datetime import datetime

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers import mongo_manager, biying_manager


def generate_trade_dates_in_range(start_date: str, end_date: str) -> list:
    """生成日期范围内所有日期，实际交易日期由比盈返回"""
    start_int = int(start_date)
    end_int = int(end_date)
    
    # 这里简化处理，实际每个日期都尝试请求，比盈会返回空如果非交易日
    dates = []
    # 需要更智能的方式，但先简单处理，从开始到结束逐天生成
    from datetime import datetime, timedelta
    
    start_dt = datetime.strptime(start_date, "%Y%m%d")
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    
    current = start_dt
    while current <= end_dt:
        date_str = current.strftime("%Y%m%d")
        dates.append(date_str)
        current += timedelta(days=1)
    
    return dates


async def sync_stock_daily_for_date(trade_date: str) -> dict:
    """
    同步指定日期的 stock_daily 数据 (使用比盈数据源)
    
    Args:
        trade_date: 交易日期 (YYYYMMDD)
        
    Returns:
        同步结果统计
    """
    print(f"\n{'='*60}")
    print(f"Syncing stock_daily for {trade_date} (via Biying)")
    print(f"{'='*60}")
    
    trade_date_int = int(trade_date)
    
    # 使用比盈获取当日所有股票数据
    df = await biying_manager.get_daily(trade_date_int)
    
    if df is None or df.empty:
        print(f"  No data returned for {trade_date} (likely non-trading day)")
        return {"date": trade_date, "count": 0, "status": "no_data"}
    
    print(f"  Got {len(df)} records from Biying API")
    
    records = df.to_dict("records")
    
    # 批量写入 MongoDB
    result = await mongo_manager.bulk_upsert(
        collection="stock_daily",
        documents=records,
        key_fields=["ts_code", "trade_date"],
    )
    
    count = result.get("upserted", 0) + result.get("modified", 0)
    print(f"  Synced {count} records (upserted={result.get('upserted', 0)}, modified={result.get('modified', 0)})")
    
    return {"date": trade_date, "count": count, "status": "ok"}


async def sync_limit_list_for_date(trade_date: str) -> dict:
    """同步指定日期的涨跌停数据 (使用比盈数据源)"""
    print(f"\nSyncing limit_list for {trade_date}...")
    
    trade_date_int = int(trade_date)
    
    df = await biying_manager.get_limit_list(trade_date_int)
    
    if df is None or df.empty:
        print(f"  No limit_list data for {trade_date}")
        return {"date": trade_date, "count": 0}
    
    records = df.to_dict("records")
    
    result = await mongo_manager.bulk_upsert(
        collection="limit_list",
        documents=records,
        key_fields=["ts_code", "trade_date"],
    )
    
    count = result.get("upserted", 0) + result.get("modified", 0)
    print(f"  Synced {count} limit records")
    return {"date": trade_date, "count": count}


async def sync_daily_basic_for_date(trade_date: str) -> dict:
    """同步指定日期的每日指标数据 (PE/PB/市值等) 使用比盈数据源"""
    print(f"\nSyncing daily_basic for {trade_date}...")
    
    trade_date_int = int(trade_date)
    
    df = await biying_manager.get_daily_basic(trade_date_int)
    
    if df is None or df.empty:
        print(f"  No daily_basic data for {trade_date}")
        return {"date": trade_date, "count": 0}
    
    records = df.to_dict("records")
    
    result = await mongo_manager.bulk_upsert(
        collection="daily_basic",
        documents=records,
        key_fields=["ts_code", "trade_date"],
    )
    
    count = result.get("upserted", 0) + result.get("modified", 0)
    print(f"  Synced {count} daily_basic records")
    return {"date": trade_date, "count": count}


async def main(args):
    print("=" * 60)
    print("Stock Daily Data Sync Script (Biying DataSource)")
    print("=" * 60)
    
    # 初始化
    await mongo_manager.initialize()
    await biying_manager.initialize()
    
    if not biying_manager.has_token():
        print("\nERROR: Biying token not configured!")
        print("Please set BIYING_TOKEN in .env file")
        await mongo_manager.shutdown()
        return
    
    # 确定日期范围
    if args.date:
        trade_dates = [args.date]
    elif args.start and args.end:
        trade_dates = generate_trade_dates_in_range(args.start, args.end)
    else:
        print("Error: Please specify --date or --start/--end")
        return
    
    if not trade_dates:
        print("No dates found in the specified range")
        return
    
    print(f"\nWill sync {len(trade_dates)} days: {trade_dates[0]} ~ {trade_dates[-1]}")
    print("Note: Non-trading days will be skipped automatically\n")
    
    # 同步每个日期
    results = []
    for trade_date in trade_dates:
        # 同步 stock_daily
        result = await sync_stock_daily_for_date(trade_date)
        results.append(("stock_daily", result))
        
        if result["count"] > 0:
            # 只在有数据时同步每日指标和涨跌停
            await sync_daily_basic_for_date(trade_date)
            await sync_limit_list_for_date(trade_date)
        
        # 礼貌性延迟，避免超过API限额
        await asyncio.sleep(1)
    
    # 汇总
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    total = 0
    success_days = 0
    for source, r in results:
        if r["status"] == "ok":
            status = "✓"
            total += r["count"]
            if r["count"] > 0:
                success_days += 1
        else:
            status = "✗"
        print(f"  {status} {r['date']}: {r['count']} records")
    
    print(f"\nTotal: {total} records synced across {success_days} trading days")
    
    # 关闭连接
    await mongo_manager.shutdown()
    await biying_manager.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync stock_daily via Biying DataSource")
    parser.add_argument("--date", type=str, help="Single date to sync (e.g., 20260106)")
    parser.add_argument("--start", type=str, help="Start date of range (e.g., 20260106)")
    parser.add_argument("--end", type=str, help="End date of range (e.g., 20260109)")
    
    args = parser.parse_args()
    
    if not args.date and not (args.start and args.end):
        parser.print_help()
        print("\nExamples:")
        print("  python scripts/sync_stock_daily_biying.py --date 20260106")
        print("  python scripts/sync_stock_daily_biying.py --start 20251224 --end 20260324")
        sys.exit(1)
    
    asyncio.run(main(args))
