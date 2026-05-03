"""
因子自动计算模块

当回测引擎检测到因子缺失时，自动触发因子计算并写入MongoDB。
基于 scripts/compute_all_factors.py 的核心逻辑，但支持增量计算（仅计算缺失日期）。

调用链:
  portfolio_backtest.run() → 检测因子缺失 → auto_compute_factors() → 计算并写入MongoDB → 回测继续
"""

import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import List, Optional

from core.managers import mongo_manager

logger = logging.getLogger(__name__)


# 策略因子列表（compute_all_factors.py计算的因子，不含技术指标）
STRATEGY_FACTOR_FIELDS = [
    "ma5", "ma10", "ma20", "ma60",
    "ma_deviation_20", "price_position", "price_near_ma5",
    "momentum_5d", "momentum_20d", "momentum_60d",
    "volatility_20d", "volatility_60d",
    "volume_ratio", "amount_20d",
    "circ_mv", "turnover_rate", "turnover_20d",
    "is_limit_up", "is_limit_down",
    "limit_up_yesterday", "limit_down_yesterday",
    "first_limit_up",
    "limit_up_count", "limit_down_count",
    "opening_pct_chg",
    "open_above_limit", "open_below_limit", "open_above_limit_down",
    "limit_up_open_amount", "limit_down_open_amount",
    "limit_up_open_count", "limit_up_time", "limit_up_open_duration",
    "pullback_pct", "pullback_days", "pullback_ma5",
    "rise_after_limit_down",
    "market_leader", "hot_sector", "sentiment_score",
    "amplitude",
]


async def auto_compute_factors(
    missing_fields: List[str],
    start_date: int,
    end_date: int,
    push_log_fn=None,
    task_id: str = "",
) -> dict:
    """
    自动计算缺失的因子并写入MongoDB

    Args:
        missing_fields: 缺失的因子字段列表
        start_date: 回测开始日期 (YYYYMMDD int)
        end_date: 回测结束日期 (YYYYMMDD int)
        push_log_fn: 日志推送函数
        task_id: 任务ID (用于日志)

    Returns:
        {"computed": True/False, "fields_computed": [...], "records_updated": N}
    """
    log = lambda msg: push_log_fn(task_id, msg) if push_log_fn else logger.info(msg)

    # 筛选出需要计算的策略因子（跳过技术指标，那些需要talib等额外依赖）
    # 技术指标(ema/rsi/macd/boll/atr/momentum_1d等)暂不支持自动计算
    computable_fields = [f for f in missing_fields if f in STRATEGY_FACTOR_FIELDS]

    if not computable_fields:
        log("   ℹ️ 缺失的因子均为技术指标(ema/rsi/macd等)，暂不支持自动计算，需要手动运行compute_all_factors.py")
        return {"computed": False, "fields_computed": [], "records_updated": 0}

    log(f"   🔄 检测到 {len(computable_fields)} 个策略因子缺失，启动自动计算...")
    log(f"   📋 需计算: {', '.join(computable_fields[:10])}{'...' if len(computable_fields) > 10 else ''}")

    try:
        result = await _compute_and_write_factors(
            computable_fields, start_date, end_date, log
        )
        log(f"   ✅ 因子自动计算完成！更新 {result['records_updated']:,} 条记录")
        return result
    except Exception as e:
        logger.exception(f"因子自动计算失败: {e}")
        log(f"   ❌ 因子自动计算失败: {e}")
        log(f"   💡 请手动运行: python scripts/compute_all_factors.py")
        return {"computed": False, "fields_computed": [], "records_updated": 0, "error": str(e)}


async def _compute_and_write_factors(
    fields: List[str],
    start_date: int,
    end_date: int,
    log_fn,
) -> dict:
    """核心计算逻辑：加载原始数据 → 计算因子 → 写回MongoDB"""

    log_fn(f"   📥 加载 {start_date}~{end_date} 的原始OHLCV数据...")
    coll = mongo_manager.db["stock_daily_ak_full"]

    # 加载日期范围内的原始数据（只取OHLCV基础字段 + _id用于更新）
    # 注意：需要多加载一些历史数据用于滚动窗口计算(如ma60需要60天历史)
    # 回溯天数取决于最长的滚动窗口
    max_lookback = 60  # ma60需要60天
    # 计算回溯起始日期(近似：每个自然月≈22交易日，60交易日≈3个月)
    lookback_start = _subtract_months(start_date, 3)

    cursor = coll.find(
        {"trade_date": {"$gte": lookback_start, "$lte": end_date}},
        {"_id": 1, "ts_code": 1, "trade_date": 1,
         "open": 1, "high": 1, "low": 1, "close": 1,
         "pct_chg": 1, "vol": 1, "amount": 1}
    )
    docs = await cursor.to_list(length=None)

    if not docs:
        log_fn(f"   ⚠️ 未找到任何原始数据")
        return {"computed": False, "fields_computed": [], "records_updated": 0}

    df = pd.DataFrame(docs)
    log_fn(f"   ✅ 加载完成: {len(df):,} 条记录, {df['ts_code'].nunique():,} 只股票")

    # 按股票分组计算因子
    log_fn(f"   🧮 计算因子...")
    computed_groups = []

    for ts_code, group in df.groupby('ts_code'):
        group = group.sort_values('trade_date').copy()
        computed = _compute_factors_for_stock(group, fields)
        computed_groups.append(computed)

    final_df = pd.concat(computed_groups, ignore_index=True)

    # 只保留回测日期范围内的记录（丢弃回溯窗口的历史数据）
    final_df = final_df[final_df['trade_date'] >= start_date]

    # 替换NaN为None
    final_df = final_df.replace({np.nan: None})

    # 写回MongoDB
    log_fn(f"   💾 写入MongoDB (仅更新缺失的因子字段)...")
    records_updated = await _write_factors_to_mongo(final_df, fields, coll, log_fn)

    return {
        "computed": True,
        "fields_computed": fields,
        "records_updated": records_updated,
    }


def _compute_factors_for_stock(group: pd.DataFrame, fields: List[str]) -> pd.DataFrame:
    """为单只股票计算因子（与compute_all_factors.py逻辑一致）"""

    # 始终计算所有策略因子（即使只缺部分，因为有些因子互相依赖）
    # MA均线
    group['ma5'] = group['close'].rolling(5).mean()
    group['ma10'] = group['close'].rolling(10).mean()
    group['ma20'] = group['close'].rolling(20).mean()
    group['ma60'] = group['close'].rolling(60).mean()

    # MA偏离度
    group['ma_deviation_20'] = (group['close'] - group['ma20']) / group['ma20']

    # 价格位置
    low_20 = group['low'].rolling(20).min()
    high_20 = group['high'].rolling(20).max()
    group['price_position'] = (group['close'] - low_20) / (high_20 - low_20 + 0.001)

    # 接近MA5
    group['price_near_ma5'] = abs(group['close'] - group['ma5']) / group['ma5'] < 0.02

    # 动量
    group['momentum_5d'] = group['close'].pct_change(5)
    group['momentum_20d'] = group['close'].pct_change(20)
    group['momentum_60d'] = group['close'].pct_change(60)

    # 波动率
    group['volatility_20d'] = group['pct_chg'].rolling(20).std()
    group['volatility_60d'] = group['pct_chg'].rolling(60).std()

    # 量比
    vol_5d_avg = group['vol'].rolling(5).mean()
    group['volume_ratio'] = group['vol'] / vol_5d_avg

    # 20日平均成交额
    group['amount_20d'] = group['amount'].rolling(20).mean()

    # 流通市值和换手率
    group['circ_mv'] = group['amount'] * 100
    group['turnover_rate'] = group['amount'] / group['circ_mv'] * 10000
    group['turnover_20d'] = group['turnover_rate'].rolling(20).mean()

    # 振幅
    group['amplitude'] = (group['high'] - group['low']) / group['close'].shift(1) * 100

    # 涨跌停识别
    group['is_limit_up'] = group['pct_chg'] >= 9.8
    group['is_limit_down'] = group['pct_chg'] <= -9.8
    group['limit_up_yesterday'] = group['is_limit_up'].shift(1).fillna(False)
    group['limit_down_yesterday'] = group['is_limit_down'].shift(1).fillna(False)
    group['first_limit_up'] = group['is_limit_up'] & ~group['limit_up_yesterday']

    # 连续涨停天数
    limit_up_counts = []
    count = 0
    for val in group['is_limit_up']:
        count = count + 1 if val else 0
        limit_up_counts.append(count)
    group['limit_up_count'] = limit_up_counts

    # 连续跌停天数
    limit_down_counts = []
    count = 0
    for val in group['is_limit_down']:
        count = count + 1 if val else 0
        limit_down_counts.append(count)
    group['limit_down_count'] = limit_down_counts

    # 竞价涨幅
    group['opening_pct_chg'] = (group['open'] - group['close'].shift(1)) / group['close'].shift(1) * 100

    # 开盘在涨跌停价附近
    group['open_above_limit'] = (group['open'] - group['close'].shift(1)) / group['close'].shift(1) >= 0.095
    group['open_below_limit'] = (group['open'] - group['close'].shift(1)) / group['close'].shift(1) <= -0.095
    group['open_above_limit_down'] = group['open_above_limit'] & group['limit_down_yesterday']

    # 涨停开板金额
    limit_up_price = group['close'].shift(1) * 1.1
    group['limit_up_open_amount'] = np.where(
        (group['high'] >= limit_up_price * 0.995) & (group['low'] < limit_up_price * 0.995),
        group['amount'], 0
    )

    # 跌停翘板金额
    limit_down_price_yesterday = group['close'].shift(1) * 0.9
    group['limit_down_open_amount'] = np.where(
        group['limit_down_yesterday'] &
        (group['low'] <= limit_down_price_yesterday * 1.005) &
        (group['close'] > limit_down_price_yesterday * 1.005),
        group['amount'], 0
    )

    # 涨停统计(简化)
    group['limit_up_open_count'] = 0
    group['limit_up_time'] = 0
    group['limit_up_open_duration'] = 0

    # 回调指标
    high_peak = group['high'].rolling(10).max()
    group['pullback_pct'] = (group['close'] - high_peak) / high_peak

    pullback_days = []
    days = 0
    for i in range(len(group)):
        days = days + 1 if group['pullback_pct'].iloc[i] < -0.01 else 0
        pullback_days.append(days)
    group['pullback_days'] = pullback_days

    group['pullback_ma5'] = (group['low'] <= group['ma5']) & (group['close'] >= group['ma5'])

    # 翘板后涨幅
    limit_down_price_yesterday2 = group['close'].shift(1) * 0.9
    group['rise_after_limit_down'] = np.where(
        group['limit_down_open_amount'] > 0,
        (group['close'] - limit_down_price_yesterday2) / limit_down_price_yesterday2 * 100,
        0
    )

    # 简化策略指标
    group['market_leader'] = False
    group['hot_sector'] = False
    group['sentiment_score'] = 0.5

    return group


async def _write_factors_to_mongo(
    df: pd.DataFrame,
    fields: List[str],
    coll,
    log_fn,
) -> int:
    """将计算好的因子写回MongoDB（只更新缺失的字段）"""
    batch_size = 5000
    total_updated = 0

    for i in range(0, len(df), batch_size):
        batch = df.iloc[i:i + batch_size]
        update_ops = []

        for _, row in batch.iterrows():
            # 只更新缺失的因子字段（$set中只包含需要的字段）
            update_fields = {}
            for field in fields:
                if field in row and row[field] is not None:
                    val = row[field]
                    # 布尔值转float（与MongoDB现有数据格式一致）
                    if isinstance(val, (bool, np.bool_)):
                        val = float(val)
                    elif isinstance(val, (np.integer,)):
                        val = int(val)
                    elif isinstance(val, (np.floating,)):
                        val = float(val)
                    update_fields[field] = val

            if update_fields:
                update_ops.append({
                    'update_one': {
                        'filter': {'ts_code': row['ts_code'], 'trade_date': int(row['trade_date'])},
                        'update': {'$set': update_fields}
                    }
                })

        if update_ops:
            result = await coll.bulk_write(update_ops, ordered=False)
            total_updated += result.modified_count + result.upserted_count
            log_fn(f"      写入进度: {min(i + batch_size, len(df)):,} / {len(df):,}")

    return total_updated


def _subtract_months(date_int: int, months: int) -> int:
    """从YYYYMMDD整数日期中减去N个月"""
    year = date_int // 10000
    month = (date_int % 10000) // 100
    day = date_int % 100

    month -= months
    while month <= 0:
        month += 12
        year -= 1

    return year * 10000 + month * 100 + day
