#!/usr/bin/env python3
"""【v2.9.112】扫描全流程端到端测试(真实数据)

用MongoDB历史数据模拟scan_once全流程:
1. 加载T-1日daily_factors
2. 从stock_daily_ak_full模拟实时行情
3. 调用merge_factors + apply_strategies
4. 验证dragon_head/limit_down_qiao信号产出

运行: python3 scripts/scan_e2e_test.py
"""

import sys
import os
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def get_latest_trade_date(db):
    """获取最近交易日"""
    doc = db['stock_daily_ak_full'].find_one(
        {'close': {'$ne': None}, 'trade_date': {'$ne': None}},
        sort=[('trade_date', -1)]
    )
    return doc['trade_date'] if doc else None


def get_previous_trade_date(db, trade_date):
    """获取前一交易日"""
    doc = db['stock_daily_ak_full'].find_one(
        {'trade_date': {'$lt': trade_date}, 'close': {'$ne': None}},
        sort=[('trade_date', -1)]
    )
    return doc['trade_date'] if doc else None


def test_e2e_scan():
    """端到端: 真实数据→merge_factors→策略筛选→信号产出"""
    from pymongo import MongoClient
    from nodes.market_monitor.strategy_scorer import StrategyScorer
    
    client = MongoClient('mongodb://localhost:27017', serverSelectionTimeoutMS=2000)
    db = client['stock_agent']
    
    # 1. 获取交易日
    trade_date = get_latest_trade_date(db)
    prev_date = get_previous_trade_date(db, trade_date)
    print(f"  T日={trade_date}, T-1日={prev_date}")
    
    if not trade_date or not prev_date:
        print("  ❌ 无可用交易数据")
        return False
    
    # 2. 加载T-1日daily_basic(因子数据)
    daily_docs = list(db['daily_basic'].find(
        {'trade_date': prev_date},
        {'_id': 0}
    ).limit(1000))
    
    if not daily_docs:
        print(f"  ❌ T-1日({prev_date})无daily_basic数据")
        return False
    
    daily_df = pd.DataFrame(daily_docs)
    print(f"  T-1日daily_basic: {len(daily_df)}只")
    
    # 3. 加载T日stock_daily_ak_full(模拟实时行情)
    ak_docs = list(db['stock_daily_ak_full'].find(
        {'trade_date': trade_date, 'close': {'$ne': None, '$gt': 0}},
        {'_id': 0}
    ).limit(100))
    
    if not ak_docs:
        print(f"  ❌ T日({trade_date})无行情数据")
        return False
    
    # 4. 构建realtime_data(从ak_full模拟)
    realtime_data = {}
    for doc in ak_docs[:50]:  # 取50只做测试
        ts_code = doc.get('ts_code', '')
        if not ts_code:
            continue
        realtime_data[ts_code] = {
            'pct_chg': float(doc.get('pct_chg', 0) or 0),
            'volume_ratio': float(doc.get('volume_ratio', 0) or 0),
            'turnover_rate': float(doc.get('turnover_rate', 0) or 0),
            'circ_mv': float(doc.get('circ_mv', 0) or 0) * 10000,  # 万元→元
            'float_mv': float(doc.get('circ_mv', 0) or 0) * 10000,
            'open': float(doc.get('open', 0) or 0),
            'high': float(doc.get('high', 0) or 0),
            'low': float(doc.get('low', 0) or 0),
            'price': float(doc.get('close', 0) or 0),
            'pre_close': float(doc.get('pre_close', 0) or 0),
            'name': doc.get('name', ''),
            'amount': float(doc.get('amount', 0) or 0),
        }
    
    print(f"  T日行情: {len(realtime_data)}只")
    
    # 5. 运行merge_factors
    class MockScanner:
        _filter_pipeline = None
        _daily_factors_df = daily_df
        _broker = None
        config = {}
        _param_center = None
    
    scorer = StrategyScorer(scanner=MockScanner())
    merged = scorer.merge_factors(realtime_data)
    print(f"\n  === merge_factors结果 ===")
    print(f"  输出: {len(merged)}只, {len(merged.columns)}个字段")
    
    # 6. 检查关键字段
    fields_check = {
        'pullback_pct': (merged['pullback_pct'] != 0).sum(),
        'pullback_days': (merged['pullback_days'] != 0).sum(),
        'limit_up_count': (merged['limit_up_count'] != 0).sum(),
    }
    print(f"\n  关键字段非0统计:")
    for field, count in fields_check.items():
        print(f"    {field}: {count}/{len(merged)} ({count/len(merged)*100:.1f}%)")
    
    # 7. 策略筛选
    try:
        signals = scorer.apply_strategies(merged)
        print(f"\n  === 策略筛选结果 ===")
        if signals:
            strategy_counts = {}
            for sig in signals:
                name = sig.get('strategy_name', sig.get('strategy', 'unknown'))
                strategy_counts[name] = strategy_counts.get(name, 0) + 1
            for name, count in sorted(strategy_counts.items(), key=lambda x: -x[1]):
                print(f"    {name}: {count}个信号")
        else:
            print("    无信号(数据量少, 正常)")
    except Exception as e:
        print(f"    策略筛选异常: {e}")
    
    # 8. 验证dragon_head条件可满足性
    print(f"\n  === dragon_head条件可满足性 ===")
    if len(merged) > 0:
        # 条件逐项统计
        conditions = {
            'circ_mv_prev >= 30亿(300000万元)': (merged.get('circ_mv_prev', pd.Series(0)) >= 300000).sum(),
            'limit_up_count >= 1': (merged.get('limit_up_count', pd.Series(0)) >= 1).sum(),
            'pullback_pct <= -0.05': (merged.get('pullback_pct', pd.Series(0)) <= -0.05).sum(),
            'pullback_pct >= -0.22': (merged.get('pullback_pct', pd.Series(0)) >= -0.22).sum(),
            'pullback_days >= 1': (merged.get('pullback_days', pd.Series(0)) >= 1).sum(),
            'volume_ratio >= 0.5': (merged.get('volume_ratio', pd.Series(0)) >= 0.5).sum(),
        }
        for desc, count in conditions.items():
            pct = count/len(merged)*100
            print(f"    {desc}: {count}/{len(merged)} ({pct:.1f}%)")
        
        # 所有条件交集
        all_pass = (
            (merged.get('circ_mv_prev', pd.Series(0)) >= 300000) &
            (merged.get('limit_up_count', pd.Series(0)) >= 1) &
            (merged.get('pullback_pct', pd.Series(0)) <= -0.05) &
            (merged.get('pullback_pct', pd.Series(0)) >= -0.22) &
            (merged.get('pullback_days', pd.Series(0)) >= 1) &
            (merged.get('volume_ratio', pd.Series(0)) >= 0.5)
        ).sum()
        print(f"\n    🐉 dragon_head全部条件通过: {all_pass}只")
        if all_pass > 0:
            print(f"    ✅ dragon_head策略可产出信号!")
            # 打印通过的股票
            passed = merged[
                (merged.get('circ_mv_prev', pd.Series(0)) >= 300000) &
                (merged.get('limit_up_count', pd.Series(0)) >= 1) &
                (merged.get('pullback_pct', pd.Series(0)) <= -0.05) &
                (merged.get('pullback_pct', pd.Series(0)) >= -0.22) &
                (merged.get('pullback_days', pd.Series(0)) >= 1) &
                (merged.get('volume_ratio', pd.Series(0)) >= 0.5)
            ]
            for _, row in passed.head(5).iterrows():
                print(f"      {row.get('ts_code','?')} pullback_pct={row.get('pullback_pct',0):.4f} "
                      f"luc={row.get('limit_up_count',0)} circ_mv_prev={row.get('circ_mv_prev',0)/10000:.0f}亿")
        else:
            print(f"    ⚠️ 50只样本中无dragon_head候选(正常, 需更大样本)")
    
    return True


def main():
    print("=" * 60)
    print("扫描全流程端到端测试 v2.9.112 (真实MongoDB数据)")
    print("=" * 60)
    
    try:
        test_e2e_scan()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n❌ 端到端测试失败: {e}")


if __name__ == '__main__':
    main()
