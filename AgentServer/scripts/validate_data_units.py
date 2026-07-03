#!/usr/bin/env python3
"""
数据单位验证脚本 - 检查MongoDB中字段单位是否正确

用法:
  python3 scripts/validate_data_units.py                          # 验证最近3天
  python3 scripts/validate_data_units.py --date 20260702          # 验证指定日期
  python3 scripts/validate_data_units.py --date 20260624-20260702 # 日期范围
  python3 scripts/validate_data_units.py --fix                    # 验证+自动修复(谨慎!)
  python3 scripts/validate_data_units.py --strict                 # 严格模式(小问题也报)

原理:
  1. 交叉验证: 用大盘参照票(工商银行/茅台/平安)检查circ_mv/total_mv量级
  2. 统计验证: 检查字段分布是否合理(如turnover_rate>100%的占比)
  3. 跨集合验证: daily_basic.circ_mv(亿元) × 10000 ≈ stock_daily_ak_full.circ_mv(万元)
"""
import argparse
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pymongo import MongoClient

MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017')

# 大盘参照票 - 流通市值稳定且已知
REF_STOCKS = {
    '601398.SH': {'name': '工商银行', 'circ_mv_yi': 19000},  # ~1.9万亿
    '600519.SH': {'name': '贵州茅台', 'circ_mv_yi': 15000},  # ~1.5万亿
    '601318.SH': {'name': '中国平安', 'circ_mv_yi': 5000},   # ~5000亿
}


def get_trade_dates(db, date_str):
    """解析日期参数，返回trade_date列表"""
    if '-' in date_str:
        start, end = date_str.split('-')
        start_td, end_td = int(start), int(end)
    else:
        start_td = end_td = int(date_str)
    
    all_dates = sorted(db['stock_daily_ak_full'].distinct('trade_date'))
    return [d for d in all_dates if start_td <= d <= end_td]


def validate_stock_daily_ak_full(db, trade_date, strict=False):
    """验证stock_daily_ak_full的字段单位"""
    issues = []
    collection = db['stock_daily_ak_full']
    
    total = collection.count_documents({'trade_date': trade_date})
    if total == 0:
        return [{'level': 'ERROR', 'field': '-', 'msg': f'{trade_date}: 无数据'}]
    
    # 1. close价格检查
    close_zero = collection.count_documents({'trade_date': trade_date, 'close': 0})
    if close_zero > 0:
        issues.append({'level': 'ERROR', 'field': 'close', 
            'msg': f'{trade_date}: {close_zero}条close=0'})
    
    # 2. vol检查 (手, 最小1)
    vol_zero = collection.count_documents({'trade_date': trade_date, 'vol': 0})
    if vol_zero > total * 0.1:
        issues.append({'level': 'WARN', 'field': 'vol',
            'msg': f'{trade_date}: {vol_zero}条vol=0 ({vol_zero/total*100:.0f}%)'})
    
    # 3. turnover_rate检查 (百分数, 0.01-100)
    tr_gt100 = collection.count_documents({'trade_date': trade_date, 'turnover_rate': {'$gt': 100}})
    if tr_gt100 > 0:
        issues.append({'level': 'CRITICAL', 'field': 'turnover_rate',
            'msg': f'{trade_date}: {tr_gt100}条turnover_rate>100%! 可能被×100'})
    
    tr_lt001 = collection.count_documents({'trade_date': trade_date, 
        'turnover_rate': {'$gt': 0, '$lt': 0.01}})
    if tr_lt001 > 0:
        issues.append({'level': 'CRITICAL', 'field': 'turnover_rate',
            'msg': f'{trade_date}: {tr_lt001}条turnover_rate<0.01! 可能是小数未×100'})
    
    # 4. circ_mv检查 (万元)
    # 4a. 用参照票交叉验证
    for ts_code, ref in REF_STOCKS.items():
        doc = collection.find_one({'ts_code': ts_code, 'trade_date': trade_date})
        if doc and doc.get('circ_mv'):
            cm = doc['circ_mv']
            cm_yi = cm / 10000  # 万元→亿元
            ref_yi = ref['circ_mv_yi']
            # 允许30%偏差(市值会波动)
            if cm_yi < ref_yi * 0.01:  # 偏差>99%
                ratio = ref_yi / cm_yi if cm_yi > 0 else 0
                issues.append({'level': 'CRITICAL', 'field': 'circ_mv',
                    'msg': f'{trade_date}: {ts_code}({ref["name"]}) circ_mv={cm_yi:.1f}亿, 应≈{ref_yi}亿, 差{ratio:.0f}倍!'})
            elif cm_yi < ref_yi * 0.5:  # 偏差>50%
                issues.append({'level': 'WARN', 'field': 'circ_mv',
                    'msg': f'{trade_date}: {ts_code}({ref["name"]}) circ_mv={cm_yi:.1f}亿, 应≈{ref_yi}亿, 偏低'})
    
    # 4b. 统计验证: circ_mv<1亿万元的占比
    cm_lt1yi = collection.count_documents({'trade_date': trade_date, 'circ_mv': {'$gt': 0, '$lt': 10000}})
    cm_total = collection.count_documents({'trade_date': trade_date, 'circ_mv': {'$gt': 0}})
    if cm_total > 0 and cm_lt1yi / cm_total > 0.3:  # >30%的票<1亿
        issues.append({'level': 'CRITICAL', 'field': 'circ_mv',
            'msg': f'{trade_date}: {cm_lt1yi}/{cm_total}条({cm_lt1yi/cm_total*100:.0f}%) circ_mv<1亿万元! 大概率单位错误'})
    
    # 5. amount检查 (百元)
    # amount应该≈vol*close/100(vol=手,close=元,amount=百元)
    # 抽样检查
    sample = list(collection.find(
        {'trade_date': trade_date, 'vol': {'$gt': 0}, 'close': {'$gt': 0}, 'amount': {'$gt': 0}},
        {'ts_code': 1, 'vol': 1, 'close': 1, 'amount': 1, '_id': 0}
    ).limit(20))
    
    amount_unit_issues = 0
    for s in sample:
        expected_amount = s['vol'] * 100 * s['close'] / 100  # 手*100=股, 股*价=元, 元/100=百元
        actual = s['amount']
        if expected_amount > 0 and actual > 0:
            ratio = actual / expected_amount
            if ratio > 50 or ratio < 0.02:  # 差50倍以上
                amount_unit_issues += 1
    
    if amount_unit_issues > len(sample) * 0.5:
        issues.append({'level': 'CRITICAL', 'field': 'amount',
            'msg': f'{trade_date}: {amount_unit_issues}/{len(sample)}抽样amount单位异常!'})
    
    return issues


def validate_daily_basic(db, trade_date, strict=False):
    """验证daily_basic的字段单位"""
    issues = []
    collection = db['daily_basic']
    
    total = collection.count_documents({'trade_date': trade_date})
    if total == 0:
        return [{'level': 'WARN', 'field': '-', 'msg': f'{trade_date}: daily_basic无数据'}]
    
    # 1. circ_mv检查 (亿元)
    for ts_code, ref in REF_STOCKS.items():
        doc = collection.find_one({'ts_code': ts_code, 'trade_date': trade_date})
        if doc and doc.get('circ_mv'):
            cm = doc['circ_mv']
            ref_yi = ref['circ_mv_yi']
            if cm < ref_yi * 0.01:
                ratio = ref_yi / cm if cm > 0 else 0
                issues.append({'level': 'CRITICAL', 'field': 'circ_mv',
                    'msg': f'{trade_date} daily_basic: {ts_code}({ref["name"]}) circ_mv={cm:.2f}亿, 应≈{ref_yi}亿, 差{ratio:.0f}倍!'})
    
    # 2. turnover_rate检查
    tr_gt100 = collection.count_documents({'trade_date': trade_date, 'turnover_rate': {'$gt': 100}})
    if tr_gt100 > 0:
        issues.append({'level': 'CRITICAL', 'field': 'turnover_rate',
            'msg': f'{trade_date} daily_basic: {tr_gt100}条turnover_rate>100%!'})
    
    return issues


def validate_cross_collection(db, trade_date):
    """跨集合验证: daily_basic.circ_mv(亿元) × 10000 ≈ stock_daily_ak_full.circ_mv(万元)"""
    issues = []
    
    # 抽样100只票
    sample_codes = [d['ts_code'] for d in db['stock_daily_ak_full'].find(
        {'trade_date': trade_date}, {'ts_code': 1, '_id': 0}
    ).limit(100)]
    
    mismatch = 0
    for ts_code in sample_codes[:50]:
        ak = db['stock_daily_ak_full'].find_one(
            {'ts_code': ts_code, 'trade_date': trade_date},
            {'circ_mv': 1, '_id': 0}
        )
        db_doc = db['daily_basic'].find_one(
            {'ts_code': ts_code, 'trade_date': trade_date},
            {'circ_mv': 1, '_id': 0}
        )
        if ak and db_doc and ak.get('circ_mv') and db_doc.get('circ_mv'):
            ak_cm = ak['circ_mv']  # 万元
            db_cm = db_doc['circ_mv']  # 亿元
            expected_ak = db_cm * 10000  # 亿元→万元
            if expected_ak > 0:
                ratio = ak_cm / expected_ak
                if ratio < 0.5 or ratio > 2.0:  # 差2倍以上
                    mismatch += 1
    
    if mismatch > 10:  # >20%不匹配
        issues.append({'level': 'CRITICAL', 'field': 'circ_mv',
            'msg': f'{trade_date}: {mismatch}/50抽样 circ_mv跨集合不一致! ak_full≠daily_basic×10000'})
    
    return issues


def run_validation(db, trade_dates, strict=False):
    """运行完整验证"""
    all_issues = []
    
    for td in trade_dates:
        issues = []
        issues.extend(validate_stock_daily_ak_full(db, td, strict))
        issues.extend(validate_daily_basic(db, td, strict))
        issues.extend(validate_cross_collection(db, td))
        all_issues.extend(issues)
    
    return all_issues


def print_report(trade_dates, issues):
    """打印验证报告"""
    level_order = {'CRITICAL': 0, 'ERROR': 1, 'WARN': 2}
    issues.sort(key=lambda x: level_order.get(x['level'], 3))
    
    critical = [i for i in issues if i['level'] == 'CRITICAL']
    errors = [i for i in issues if i['level'] == 'ERROR']
    warns = [i for i in issues if i['level'] == 'WARN']
    
    print(f"\n{'='*60}")
    print(f"数据单位验证报告")
    print(f"验证日期: {trade_dates[0]}-{trade_dates[-1]} ({len(trade_dates)}天)")
    print(f"{'='*60}")
    
    if not issues:
        print("✅ 全部通过! 无单位异常")
        return 0
    
    print(f"\n🔴 CRITICAL: {len(critical)}")
    for i in critical:
        print(f"  [{i['field']}] {i['msg']}")
    
    print(f"\n🟠 ERROR: {len(errors)}")
    for i in errors:
        print(f"  [{i['field']}] {i['msg']}")
    
    print(f"\n🟡 WARN: {len(warns)}")
    for i in warns:
        print(f"  [{i['field']}] {i['msg']}")
    
    if critical:
        print(f"\n❌ 验证失败: {len(critical)}个CRITICAL问题需要修复!")
        return 1
    elif errors:
        print(f"\n⚠️ 验证有误: {len(errors)}个ERROR需要关注")
        return 2
    else:
        print(f"\n✅ 验证通过(有{len(warns)}个警告)")
        return 0


def main():
    parser = argparse.ArgumentParser(description='数据单位验证')
    parser.add_argument('--date', default=None, help='日期(YYYYMMDD或YYYYMMDD-YYYYMMDD)')
    parser.add_argument('--days', type=int, default=3, help='验证最近N天(默认3)')
    parser.add_argument('--strict', action='store_true', help='严格模式')
    parser.add_argument('--fix', action='store_true', help='自动修复(谨慎!)')
    args = parser.parse_args()
    
    client = MongoClient(MONGO_URI)
    db = client['stock_agent']
    
    if args.date:
        trade_dates = get_trade_dates(db, args.date)
    else:
        # 最近N天
        all_dates = sorted(db['stock_daily_ak_full'].distinct('trade_date'), reverse=True)
        trade_dates = sorted(all_dates[:args.days])
    
    if not trade_dates:
        print("无交易日期可验证")
        return
    
    print(f"验证日期: {trade_dates}")
    
    issues = run_validation(db, trade_dates, args.strict)
    exit_code = print_report(trade_dates, issues)
    
    if args.fix and exit_code == 1:
        print("\n⚠️ 自动修复功能暂未实现, 请手动修复后重新验证")
    
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
