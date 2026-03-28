#!/usr/bin/env python3
"""
详细步骤调试：分析每个过滤步骤，找出为什么选不出股票
"""
import asyncio
import logging
import pandas as pd
import numpy as np
from datetime import datetime
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')

from core.managers import mongo_manager, redis_manager
from backtest_module.backtest_engine.factor_selection.universe import UniverseManager
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler('/tmp/debug_step_by_step.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

async def debug_strategy_step_by_step(strategy_name: str = "半路追涨"):
    """调试策略的每一步过滤"""
    
    # 初始化管理器
    await redis_manager.initialize()
    await mongo_manager.initialize()
    
    # 创建 UniverseManager 和 FactorEngine
    universe_mgr = UniverseManager(source="ak")
    factor_engine = FactorEngine(source="ak")
    
    # 定义策略参数
    strategy_params = {
        "半路追涨": {
            "liquidity_threshold": 1000,
            "factors": ["limit_up_yesterday", "open_below_limit"],
            "condition": lambda df: (df["limit_up_yesterday"] > 0.5) & (df["open_below_limit"] > 0)
        },
        "涨停开板": {
            "liquidity_threshold": 1000,
            "factors": ["limit_up_yesterday", "open_below_limit"],
            "condition": lambda df: (df["limit_up_yesterday"] > 0.5) & (df["open_below_limit"] > 0)
        },
        "龙头战法": {
            "liquidity_threshold": 1000,
            "factors": ["is_dragon", "dragon_callback"],
            "condition": lambda df: (df["is_dragon"] > 0.5) & (df["dragon_callback"] > 0)
        },
        "首板打板": {
            "liquidity_threshold": 1000,
            "factors": ["first_limit_up", "volume_increase"],
            "condition": lambda df: (df["first_limit_up"] > 0.5) & (df["volume_increase"] > 0)
        }
    }
    
    params = strategy_params[strategy_name]
    
    # 获取回测日期
    start_date = "20260105"
    end_date = "20260320"
    
    # 获取调仓日期列表
    rebalance_dates = await universe_mgr._get_rebalance_dates(start_date, end_date, freq="daily")
    
    # 分析第一个交易日
    first_date = rebalance_dates[0] if rebalance_dates else start_date
    print(f"\n{'='*60}")
    print(f"📊 分析策略: {strategy_name}")
    print(f"📅 交易日: {first_date}")
    print(f"{'='*60}\n")
    
    # 1. 获取基础股票池
    stocks = await universe_mgr._get_tradable_stocks(first_date)
    print(f"1️⃣  基础股票池: {len(stocks)} 只股票")
    if len(stocks) < 10:
        print(f"   样本股票: {list(stocks)[:10]}")
    
    if not stocks:
        print("🚫 基础股票池为空！可能是数据问题")
        return
    
    # 2. 排除规则
    exclude_rules = ["st", "new_stock", "limit_up", "limit_down"]
    excluded_st = await universe_mgr._get_st_stocks()
    excluded_new = await universe_mgr._get_new_stocks(first_date)
    
    # 获取涨停跌停股
    limit_docs = await mongo_manager.find_many(
        "limit_list",
        {"trade_date": int(first_date)},
        projection={"ts_code": 1, "limit_type": 1}
    )
    limit_codes = {
        doc["ts_code"]: doc.get("limit_type", "unknown")
        for doc in limit_docs
    }
    
    excluded_limit_up = {code for code, limit_type in limit_codes.items() if limit_type in ["U", "UC"]}
    excluded_limit_down = {code for code, limit_type in limit_codes.items() if limit_type in ["D", "DC"]}
    
    # 应用排除
    if "st" in exclude_rules:
        stocks = stocks - excluded_st
        print(f"2️⃣  排除 ST 股后: {len(stocks)} 只")
    
    if "new_stock" in exclude_rules:
        stocks = stocks - excluded_new
        print(f"   排除次新股后: {len(stocks)} 只")
    
    if "limit_up" in exclude_rules:
        stocks = stocks - excluded_limit_up
        print(f"   排除涨停股后: {len(stocks)} 只")
    
    if "limit_down" in exclude_rules:
        stocks = stocks - excluded_limit_down
        print(f"   排除跌停股后: {len(stocks)} 只")
    
    print(f"    最终排除后股票数: {len(stocks)} 只\n")
    
    if not stocks:
        print("🚫 所有股票都被排除了！")
        return
    
    # 3. 加载数据并计算因子
    print(f"3️⃣  加载数据并计算因子...")
    
    # 获取前一日数据用于因子计算
    date_int = int(first_date)
    prev_date_query = {
        "trade_date": {"$lt": date_int}
    }
    latest_prev = await mongo_manager.find_one(
        "stock_daily_ak",
        prev_date_query,
        sort=[("trade_date", -1)]
    )
    
    if not latest_prev:
        print("   ⚠️  没有前一日数据，无法计算因子")
        return
    
    prev_date = latest_prev["trade_date"]
    
    # 加载昨日数据
    data = await factor_engine._load_daily_data(
        list(stocks),
        str(prev_date),
        str(prev_date),
        source="ak"
    )
    
    if not data:
        print("   ⚠️  加载数据失败")
        return
    
    # 转换为 DataFrame 并计算因子
    df_list = []
    for ts_code, docs in data.items():
        for doc in docs:
            # 提取所需字段
            row = {
                "ts_code": ts_code,
                "trade_date": doc["trade_date"],
                "open": doc.get("open", np.nan),
                "close": doc.get("close", np.nan),
                "up_limit": doc.get("up_limit", np.nan),
                "down_limit": doc.get("down_limit", np.nan),
                "amount": doc.get("amount", np.nan),
                "vol": doc.get("vol", np.nan)
            }
            df_list.append(row)
    
    df = pd.DataFrame(df_list)
    
    # 检查数据完整性
    print(f"   ✅  已加载 {len(df)} 条记录（股票数：{len(df['ts_code'].unique())}）")
    
    # 4. 计算因子值
    print(f"4️⃣  计算因子值...")
    
    # 手动计算 limit_up_yesterday
    df["limit_up_yesterday"] = (df["close"] >= df["up_limit"] * 0.998).astype(float)
    
    # 手动计算 open_below_limit（昨日涨停价 vs 今日开盘价）
    # 注意：这是简化计算，实际中需要今日开盘价
    
    print(f"   ✅  已计算因子:")
    print(f"       limit_up_yesterday 平均值: {df['limit_up_yesterday'].mean():.4f}")
    print(f"       涨停股数量（limit_up_yesterday > 0.5）: {(df['limit_up_yesterday'] > 0.5).sum()}")
    
    # 5. 应用策略条件
    print(f"5️⃣  应用策略条件...")
    
    # 先查看 limit_up_yesterday 大于 0.5 的股票
    limit_up_stocks = df[df["limit_up_yesterday"] > 0.5]["ts_code"].unique()
    print(f"      昨日涨停的股票数: {len(limit_up_stocks)} 只")
    if len(limit_up_stocks) > 0:
        print(f"      涨停股票样本: {limit_up_stocks[:10]}")
    
    # 需要获取今日开盘价来计算 open_below_limit
    # 获取今日数据
    today_query = {"trade_date": date_int, "ts_code": {"$in": list(limit_up_stocks)}}
    today_docs = await mongo_manager.find_many(
        "stock_daily_ak",
        today_query,
        projection={"ts_code": 1, "open": 1}
    )
    
    if today_docs:
        # 构建今日开盘价字典
        today_open = {doc["ts_code"]: doc.get("open", np.nan) for doc in today_docs}
        
        # 为每个股票计算 open_below_limit 条件
        # 注意：这是简化，实际因子引擎有更复杂的计算
        selected = []
        for ts_code in limit_up_stocks:
            # 昨日数据
            prev_data = df[df["ts_code"] == ts_code].iloc[0]
            prev_up_limit = prev_data["up_limit"]
            
            # 今日开盘价
            today_open_price = today_open.get(ts_code, np.nan)
            
            # 检查条件: 今日开盘价 < 昨日涨停价
            if not np.isnan(today_open_price) and not np.isnan(prev_up_limit):
                if today_open_price < prev_up_limit:
                    selected.append(ts_code)
        
        print(f"      满足今日开盘价 < 昨日涨停价的股票数: {len(selected)} 只")
        
        if len(selected) > 0:
            print(f"      选中股票: {selected}")
        else:
            print(f"   🚫  没有股票满足策略条件: 昨日涨停 AND 今日开盘价 < 昨日涨停价")
            
            # 进一步分析: 查看具体数据
            print(f"\n   🔍  详细分析（第一个涨停股票为例）：")
            if len(limit_up_stocks) > 0:
                sample_code = limit_up_stocks[0]
                
                # 昨日数据
                prev_data = df[df["ts_code"] == sample_code].iloc[0]
                print(f"      股票代码: {sample_code}")
                print(f"      昨日收盘价: {prev_data['close']}")
                print(f"      昨日涨停价: {prev_data['up_limit']}")
                print(f"      limit_up_yesterday: {prev_data['limit_up_yesterday']}")
                
                # 今日数据
                today_open_price = today_open.get(sample_code, np.nan)
                print(f"      今日开盘价: {today_open_price}")
                
                if not np.isnan(today_open_price) and not np.isnan(prev_data["up_limit"]):
                    if today_open_price >= prev_data["up_limit"]:
                        print(f"      ❌ 今日开盘价 >= 昨日涨停价 → 不满足条件")
                        print(f"        差值: {today_open_price - prev_data['up_limit']}")
                    else:
                        print(f"      ✅ 今日开盘价 < 昨日涨停价 → 满足条件！")
                        print(f"        差值: {prev_data['up_limit'] - today_open_price}")
                else:
                    print(f"      ⚠️  缺少今日开盘价数据")
    
    else:
        print(f"      ⚠️  没有今日数据")
    
    print(f"\n{'='*60}")
    print(f"📋 总结:")
    print(f"  策略: {strategy_name}")
    print(f"  条件: 昨日涨停 AND 今日开盘价 < 昨日涨停价")
    print(f"  昨日涨停股数: {len(limit_up_stocks)}")
    print(f"  最终选中股票数: {len(selected) if 'selected' in locals() else 0}")
    print(f"{'='*60}\n")
    
    # 清理
    await redis_manager.close()
    await mongo_manager.close()

async def main():
    """主函数"""
    print("🔍 StockAgent 策略过滤步骤分析")
    print("分析 2026-01-05 到 2026-03-20 区间的每一步过滤")
    
    strategies = ["半路追涨", "涨停开板", "龙头战法", "首板打板"]
    
    for strategy in strategies:
        await debug_strategy_step_by_step(strategy)

if __name__ == "__main__":
    asyncio.run(main())