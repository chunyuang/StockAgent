"""
重新计算指定时间段的 market_analysis 数据 (仅分析，不重算 daily_stats)

V2.1 平滑版双评分系统:
- 核心分经过 3 日 EMA 平滑，消除单日脉冲
- 趋势阈值放宽到 ±10%，减少频繁切换
- 强弱差 ≥10 分才显示，图表更干净
- 因子权重聚焦核心，减少噪音

用法:
    cd AgentServer
    
    # 重算单个日期
    python scripts/recalc_market_analysis.py --date 20260128
    
    # 重算时间段
    python scripts/recalc_market_analysis.py --start 20260106 --end 20260128
    
    # 重算最近N个交易日
    python scripts/recalc_market_analysis.py --days 20
"""

import asyncio
import argparse
from datetime import datetime, timedelta
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.managers import mongo_manager, data_source_manager, analysis_manager


async def get_trade_dates_in_range(start_date: str, end_date: str) -> list:
    """获取指定范围内的交易日"""
    await data_source_manager.initialize()
    
    dates, _ = await data_source_manager.get_trade_calendar(start_date, end_date)
    return sorted(dates) if dates else []


async def get_recent_trade_dates(days: int) -> list:
    """获取最近N个交易日"""
    await data_source_manager.initialize()
    
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
    
    dates, _ = await data_source_manager.get_trade_calendar(start_date, end_date)
    
    if not dates:
        return []
    
    sorted_dates = sorted(dates, reverse=True)
    return sorted_dates[:days][::-1]  # 取最近N天，然后反转为从早到晚


async def recalc_analysis_for_dates(trade_dates: list):
    """
    重新计算指定日期列表的 market_analysis (V2.1 平滑版)
    
    V2.1 优化:
    1. 核心分经过 3 日 EMA 平滑 (0.6/0.3/0.1 权重)
    2. 趋势阈值放宽到 ±10%
    3. 强弱差 ≥10 分才视为有效背离
    4. 因子权重聚焦核心因子
    """
    print(f"=== Recalculating market_analysis (V2.1 Smoothed) for {len(trade_dates)} trading days ===")
    print(f"Date range: {trade_dates[0]} ~ {trade_dates[-1]}")
    print(f"Algorithm: 3-day EMA Core + Trend(±10%) + Divergence(≥10)\n")
    
    # 清除 analysis_manager 的缓存
    analysis_manager._ma_cache.clear()
    
    success_count = 0
    skip_count = 0
    error_count = 0
    
    for i, trade_date in enumerate(trade_dates):
        try:
            # 从 daily_stats 获取当日数据
            stats = await mongo_manager.find_one(
                "daily_stats",
                {"trade_date": trade_date},
            )
            
            if not stats:
                print(f"[{i+1}/{len(trade_dates)}] {trade_date} - SKIP (no daily_stats)")
                skip_count += 1
                continue
            
            # 获取前一天数据 (兼容旧接口)
            prev_stats = await mongo_manager.find_one(
                "daily_stats",
                {"trade_date": {"$lt": trade_date}},
                sort=[("trade_date", -1)],
            )
            
            # 重新计算分析 (V2 双评分系统)
            analysis_result = await analysis_manager.analyze_and_store(
                stats=stats,
                prev_stats=prev_stats,
                mongo_manager=mongo_manager,
            )
            
            # 显示结果 (V2 格式)
            sentiment = analysis_result.get("sentiment_score", 0)
            strength = analysis_result.get("strength_score", 0)
            sent_trend = analysis_result.get("sentiment_trend", "?")
            stren_trend = analysis_result.get("strength_trend", "?")
            cycle = analysis_result.get("cycle", "unknown")
            position = analysis_result.get("position_advice", {})
            pos_range = position.get("range", "?")
            
            # 趋势符号
            trend_sym = {"up": "↑", "flat": "→", "down": "↓"}
            sent_sym = trend_sym.get(sent_trend, "?")
            stren_sym = trend_sym.get(stren_trend, "?")
            
            print(
                f"[{i+1}/{len(trade_dates)}] {trade_date} "
                f"情绪:{sentiment:.0f}{sent_sym} "
                f"强度:{strength:.0f}{stren_sym} "
                f"| {cycle} | {pos_range}"
            )
            success_count += 1
            
        except Exception as e:
            print(f"[{i+1}/{len(trade_dates)}] {trade_date} - ERROR: {e}")
            import traceback
            traceback.print_exc()
            error_count += 1
    
    print(f"\n=== Done! ===")
    print(f"  Success: {success_count}")
    print(f"  Skipped: {skip_count}")
    print(f"  Errors:  {error_count}")
    print(f"\nLegend: ↑=走强 →=横盘 ↓=走弱")
    print(f"Cycles: ice_point/recovery/main_upward/divergence/decline/chaos")


async def main(args):
    # 初始化
    await mongo_manager.initialize()
    await data_source_manager.initialize()
    await analysis_manager.initialize()
    
    # 确定要处理的日期范围
    if args.date:
        trade_dates = [args.date]
    elif args.start and args.end:
        trade_dates = await get_trade_dates_in_range(args.start, args.end)
    elif args.days:
        trade_dates = await get_recent_trade_dates(args.days)
    else:
        print("Error: Please specify --date, --start/--end, or --days")
        return
    
    if not trade_dates:
        print("No trading dates found in the specified range")
        return
    
    # 重新计算
    await recalc_analysis_for_dates(trade_dates)
    
    # 关闭连接
    await mongo_manager.shutdown()
    await data_source_manager.shutdown()
    await analysis_manager.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recalculate market_analysis for specified date range")
    parser.add_argument("--date", type=str, help="Single date to recalculate (e.g., 20260128)")
    parser.add_argument("--start", type=str, help="Start date of range (e.g., 20260106)")
    parser.add_argument("--end", type=str, help="End date of range (e.g., 20260128)")
    parser.add_argument("--days", type=int, help="Number of recent trading days to recalculate")
    
    args = parser.parse_args()
    
    if not args.date and not (args.start and args.end) and not args.days:
        parser.print_help()
        print("\nExamples:")
        print("  python scripts/recalc_market_analysis.py --date 20260128")
        print("  python scripts/recalc_market_analysis.py --start 20260106 --end 20260128")
        print("  python scripts/recalc_market_analysis.py --days 20")
        sys.exit(1)
    
    asyncio.run(main(args))
