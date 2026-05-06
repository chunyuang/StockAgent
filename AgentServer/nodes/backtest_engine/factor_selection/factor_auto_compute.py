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

from core.constants import C
from core.managers import mongo_manager

logger = logging.getLogger(__name__)


# 技术指标因子列表（需要talib）
TECHNICAL_FACTOR_FIELDS = [
    "ema12", "ema26",
    "rsi_6", "rsi_12", "rsi_24",
    "macd", "macd_signal", "macd_hist",
    "boll_upper", "boll_mid", "boll_lower",
    "atr", "natr", "trange",
    "momentum_1d", "momentum_5d", "momentum_10d", "momentum_20d",
    "volatility_5d", "volatility_10d", "volatility_20d",
    "turnover_5d_avg", "turnover_20d_avg",
    "fear_greed_index",
]

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

# 所有可自动计算的因子
ALL_COMPUTABLE_FIELDS = STRATEGY_FACTOR_FIELDS + TECHNICAL_FACTOR_FIELDS


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

    # 筛选出需要计算的因子（策略因子+技术指标）
    computable_fields = [f for f in missing_fields if f in ALL_COMPUTABLE_FIELDS]

    if not computable_fields:
        log("   ℹ️ 缺失的因子无法自动计算，请手动运行: python scripts/compute_all_factors.py")
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
    coll = mongo_manager.db[C.STOCK_DAILY]

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

    # 确保数值列为float类型，避免int64列赋值float时TypeError
    for col in ['circ_mv', 'turnover_rate', 'amount', 'vol', 'close', 'open', 'high', 'low']:
        if col in group.columns:
            group[col] = group[col].astype(float)

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
    # 优先使用已有精确值(来自daily_basic)，仅缺失时用近似值
    if 'volume_ratio' not in group.columns or group['volume_ratio'].isna().all():
        group['volume_ratio'] = group['vol'] / vol_5d_avg

    # 20日平均成交额
    group['amount_20d'] = group['amount'].rolling(20).mean()

    # 流通市值和换手率
    # 优先使用已有精确值(来自daily_basic合并或修复脚本)，仅缺失时用近似值
    if 'circ_mv' not in group.columns or group['circ_mv'].isna().all():
        # 近似值: 成交额/换手率*100（需要turnover_rate先算好）
        if 'turnover_rate' in group.columns and group['turnover_rate'].notna().any() and (group['turnover_rate'] > 0).any():
            group['circ_mv'] = group['amount'] / (group['turnover_rate'] / 100) / 10000  # 元→万元
        else:
            group['circ_mv'] = None  # 无法近似时不设假值
    if 'turnover_rate' not in group.columns or group['turnover_rate'].isna().all():
        if group.get('circ_mv') is not None and (group['circ_mv'] > 0).any():
            group['turnover_rate'] = group['amount'] / group['circ_mv'] / 10000 * 100  # circ_mv万元→元
        # else: 留空
    group['turnover_20d'] = group['turnover_rate'].rolling(20).mean()

    # 振幅
    group['amplitude'] = (group['high'] - group['low']) / group['close'].shift(1) * 100

    # 涨跌停识别（分板块阈值）
    # 主板10%/ST5%, 创业板/科创板20%, 北交所30%
    # 用9.5%作为主板阈值（考虑四舍五入），19.5%作为创业板/科创板阈值
    ts_code_prefix = group['ts_code'].iloc[0][:3] if 'ts_code' in group.columns else '000'
    if ts_code_prefix.startswith(('300', '301', '688')):
        limit_up_thresh = 19.5
        limit_down_thresh = -19.5
    elif ts_code_prefix.startswith(('8', '4')):
        limit_up_thresh = 29.5
        limit_down_thresh = -29.5
    else:
        limit_up_thresh = 9.5  # 主板(含ST的5%会漏掉，但ST一般不是策略目标)
        limit_down_thresh = -9.5
    group['is_limit_up'] = group['pct_chg'] >= limit_up_thresh
    group['is_limit_down'] = group['pct_chg'] <= limit_down_thresh
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
    # 情绪评分: 基于市场数据计算(而非硬编码0.5)
    # 使用RSI和波动率的z-score映射到[0,1]，RSI>50且波动率低→高情绪
    if 'rsi_6' not in group.columns:
        # talib不可用时，用pct_chg近似
        group['rsi_6'] = 50 + group['pct_chg'].rolling(6).mean() * 10
    rsi_normalized = (group['rsi_6'] - 50) / 50  # [-1, 1]
    volatility = group['pct_chg'].rolling(20).std()
    vol_mean = volatility.rolling(60).mean()
    vol_zscore = (volatility - vol_mean) / vol_mean.clip(lower=0.01)  # 避免除0
    # 高RSI + 低波动率 = 高情绪(贪婪), 低RSI + 高波动率 = 低情绪(恐惧)
    group['sentiment_score'] = (0.5 + rsi_normalized * 0.3 - vol_zscore.clip(-2, 2) * 0.1).clip(0, 1)
    # 填充NaN为中性
    group['sentiment_score'] = group['sentiment_score'].fillna(0.5)

    # ========== 技术指标因子（需要talib） ==========
    try:
        import talib

        close_arr = group['close'].values.astype(float)
        high_arr = group['high'].values.astype(float)
        low_arr = group['low'].values.astype(float)
        vol_arr = group['vol'].values.astype(float)

        # EMA
        group['ema12'] = talib.EMA(close_arr, timeperiod=12)
        group['ema26'] = talib.EMA(close_arr, timeperiod=26)

        # RSI
        group['rsi_6'] = talib.RSI(close_arr, timeperiod=6)
        group['rsi_12'] = talib.RSI(close_arr, timeperiod=12)
        group['rsi_24'] = talib.RSI(close_arr, timeperiod=24)

        # MACD
        macd, macd_signal, macd_hist = talib.MACD(close_arr)
        group['macd'] = macd
        group['macd_signal'] = macd_signal
        group['macd_hist'] = macd_hist

        # Bollinger Bands
        bb_upper, bb_mid, bb_lower = talib.BBANDS(close_arr, timeperiod=20)
        group['boll_upper'] = bb_upper
        group['boll_mid'] = bb_mid
        group['boll_lower'] = bb_lower

        # ATR / NATR / TRANGE
        group['atr'] = talib.ATR(high_arr, low_arr, close_arr, timeperiod=14)
        group['natr'] = talib.NATR(high_arr, low_arr, close_arr, timeperiod=14)
        group['trange'] = talib.TRANGE(high_arr, low_arr, close_arr)

        # 动量 (补充 momentum_1d, momentum_10d)
        group['momentum_1d'] = group['close'].pct_change(1)
        group['momentum_10d'] = group['close'].pct_change(10)

        # 波动率 (补充 volatility_5d, volatility_10d)
        group['volatility_5d'] = group['pct_chg'].rolling(5).std()
        group['volatility_10d'] = group['pct_chg'].rolling(10).std()

        # 换手率均值
        group['turnover_5d_avg'] = group['turnover_rate'].rolling(5).mean()
        group['turnover_20d_avg'] = group['turnover_rate'].rolling(20).mean()

        # 恐贪指数(简化版: 基于RSI和波动率)
        rsi_norm = (group['rsi_12'] - 50) / 50  # -1 to 1
        vol_zscore = (group['volatility_20d'] - group['volatility_20d'].rolling(60).mean()) / (group['volatility_20d'].rolling(60).std() + 0.001)
        group['fear_greed_index'] = (rsi_norm - vol_zscore) * 2.5 + 5  # 简化映射到0~10

    except ImportError:
        # talib不可用时跳过技术指标
        pass

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
                from pymongo import UpdateOne
                update_ops.append(UpdateOne(
                    {'ts_code': row['ts_code'], 'trade_date': int(row['trade_date'])},
                    {'$set': update_fields}
                ))

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
