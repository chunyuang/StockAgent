#!/usr/bin/env python3
"""
因子预计算脚本 - 填充stale因子

从现有MongoDB数据计算以下因子:
- dv_ttm (股息率TTM) → daily_basic.dv_ratio
- amplitude (振幅) → stock_daily_ak_full (high-low)/pre_close
- pullback_pct (回调幅度) → stock_daily_ak_full
- pullback_days (回调天数) → stock_daily_ak_full
- volume_increase (放量标记) → stock_daily_ak_full volume对比
- sentiment_score (情绪评分) → sentiment_scores集合
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))

from pymongo import MongoClient
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger('factor_precompute')

DB_NAME = 'stock_agent'


def get_db():
    return MongoClient('mongodb://localhost:27017')[DB_NAME]


def compute_amplitude(db, ts_code: str, trade_date: str) -> float | None:
    """振幅 = (最高价 - 最低价) / 昨收价 * 100"""
    doc = db['stock_daily_ak_full'].find_one(
        {'ts_code': ts_code, 'trade_date': trade_date},
        {'high': 1, 'low': 1, 'pre_close': 1}
    )
    if not doc or not doc.get('pre_close') or doc['pre_close'] == 0:
        return None
    try:
        return round((doc['high'] - doc['low']) / doc['pre_close'] * 100, 2)
    except (TypeError, ZeroDivisionError):
        return None


def compute_pullback_pct(db, ts_code: str, trade_date: str) -> float | None:
    """回调幅度 = (最近高点 - 当日收盘) / 最近高点 * 100"""
    # 获取近20日数据
    docs = list(db['stock_daily_ak_full'].find(
        {'ts_code': ts_code, 'trade_date': {'$lte': trade_date}},
        {'close': 1, 'trade_date': 1}
    ).sort('trade_date', -1).limit(20))

    if not docs:
        return None
    current_close = docs[0].get('close')
    high_close = max(d.get('close', 0) for d in docs if d.get('close'))
    if not high_close or high_close == 0:
        return None
    return round((high_close - current_close) / high_close * 100, 2)


def compute_volume_increase(db, ts_code: str, trade_date: str) -> float | None:
    """放量标记 = 当日成交量 / 20日平均成交量"""
    docs = list(db['stock_daily_ak_full'].find(
        {'ts_code': ts_code, 'trade_date': {'$lte': trade_date}},
        {'vol': 1, 'trade_date': 1}
    ).sort('trade_date', -1).limit(21))

    if len(docs) < 2:
        return None
    current_vol = docs[0].get('vol')
    if not current_vol:
        return None
    avg_vol = sum(d.get('vol', 0) for d in docs[1:] if d.get('vol')) / max(len(docs) - 1, 1)
    if avg_vol == 0:
        return None
    return round(current_vol / avg_vol, 2)


def compute_dv_ttm(db, ts_code: str, trade_date: str) -> float | None:
    """股息率TTM → 从daily_basic的dv_ratio获取"""
    doc = db['daily_basic'].find_one(
        {'ts_code': ts_code, 'trade_date': trade_date},
        {'dv_ratio': 1}
    )
    return doc.get('dv_ratio') if doc else None


def compute_sentiment_score(db, trade_date: str) -> float | None:
    """情绪评分 → 从sentiment_scores集合获取"""
    doc = db['sentiment_scores'].find_one({'date': trade_date})
    return doc.get('score') if doc else None


def precompute_factors(ts_codes: list[str] | None = None, trade_date: str | None = None):
    """批量预计算因子"""
    db = get_db()

    if not trade_date:
        # 取最近的交易日期
        latest = db['stock_daily_ak_full'].find_one(sort=[('trade_date', -1)])
        trade_date = latest['trade_date'] if latest else None
        if not trade_date:
            logger.error("无法确定交易日期")
            return

    if not ts_codes:
        # 获取有daily数据的所有股票
        ts_codes = db['stock_daily_ak_full'].distinct('ts_code', {'trade_date': trade_date})

    logger.info(f"预计算因子: date={trade_date}, stocks={len(ts_codes)}")

    # 计算情绪评分(全市场共享)
    sentiment = compute_sentiment_score(db, trade_date)

    updated = 0
    errors = 0

    for i, ts_code in enumerate(ts_codes):
        try:
            # 计算各因子
            amplitude = compute_amplitude(db, ts_code, trade_date)
            pullback_pct = compute_pullback_pct(db, ts_code, trade_date)
            vol_increase = compute_volume_increase(db, ts_code, trade_date)
            dv_ttm = compute_dv_ttm(db, ts_code, trade_date)

            # 更新到daily_basic
            update_fields = {}
            if amplitude is not None:
                update_fields['amplitude'] = amplitude
            if pullback_pct is not None:
                update_fields['pullback_pct'] = pullback_pct
            if vol_increase is not None:
                update_fields['volume_increase'] = vol_increase
            if dv_ttm is not None:
                update_fields['dv_ttm'] = dv_ttm
            if sentiment is not None:
                update_fields['sentiment_score'] = sentiment

            if update_fields:
                db['daily_basic'].update_one(
                    {'ts_code': ts_code, 'trade_date': trade_date},
                    {'$set': update_fields}
                )
                updated += 1

            if (i + 1) % 500 == 0:
                logger.info(f"进度: {i+1}/{len(ts_codes)}, 已更新: {updated}")

        except Exception as e:
            errors += 1
            if errors <= 5:
                logger.error(f"处理 {ts_code} 失败: {e}")

    logger.info(f"完成! 更新: {updated}, 错误: {errors}, 总计: {len(ts_codes)}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='因子预计算')
    parser.add_argument('--codes', nargs='*', help='股票代码列表')
    parser.add_argument('--date', help='交易日期 YYYYMMDD')
    args = parser.parse_args()

    precompute_factors(ts_codes=args.codes, trade_date=args.date)
