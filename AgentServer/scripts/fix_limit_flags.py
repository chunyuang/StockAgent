"""
重算is_limit_up/is_limit_down及衍生因子
基于pct_chg阈值而非前复权价格匹配
"""
from pymongo import MongoClient
from collections import defaultdict

db = MongoClient('localhost', 27017)['stock_agent']
col = db.stock_daily_ak_full

# ─── Step 1: 清除旧的假值 ───
print("=== Step 1: 清除旧的is_limit_up/is_limit_down ===")
# 先统计旧值分布
old_lu = col.count_documents({'is_limit_up': 1})
old_ld = col.count_documents({'is_limit_down': 1})
print(f"  旧 is_limit_up=1: {old_lu}条")
print(f"  旧 is_limit_down=1: {old_ld}条")

# 清除所有涨停/跌停相关字段
fields_to_clear = [
    'is_limit_up', 'is_limit_down',
    'limit_up_yesterday', 'limit_down_yesterday',
    'first_limit_up', 'first_limit_down',
    'limit_up_count', 'limit_down_count',
    'consecutive_limit_up_count',
]
for f in fields_to_clear:
    result = col.update_many({f: {'$exists': True}}, {'$unset': {f: ""}})
    if result.modified_count > 0:
        print(f"  清除 {f}: {result.modified_count}条")

# ─── Step 2: 按pct_chg重算is_limit_up/is_limit_down ───
print("\n=== Step 2: 按pct_chg阈值重算 ===")

# 获取所有交易日
dates = sorted(col.distinct('trade_date'))
print(f"  交易日数: {len(dates)}, 范围: {dates[0]}~{dates[-1]}")

total_updated = 0
batch = []

for i, date in enumerate(dates):
    # 主板: pct_chg >= 9.5% (含ST的5%会漏,但ST一般不是策略目标)
    # 科创板688xxx: >= 19.5%
    # 北交所8xxxxx/4xxxxx: >= 29.5%
    
    # 涨停
    # 主板(非688非北交所)
    r1 = col.update_many(
        {'trade_date': date, 'pct_chg': {'$gte': 9.5}, 
         'ts_code': {'$not': {'$regex': '^(688|8|4)'}}},
        {'$set': {'is_limit_up': 1}}
    )
    # 科创板
    r2 = col.update_many(
        {'trade_date': date, 'pct_chg': {'$gte': 19.5},
         'ts_code': {'$regex': '^688'}},
        {'$set': {'is_limit_up': 1}}
    )
    # 北交所
    r3 = col.update_many(
        {'trade_date': date, 'pct_chg': {'$gte': 29.5},
         'ts_code': {'$regex': '^(8|4)'}},
        {'$set': {'is_limit_up': 1}}
    )
    
    lu_count = r1.modified_count + r2.modified_count + r3.modified_count
    
    # 跌停 (对称)
    r4 = col.update_many(
        {'trade_date': date, 'pct_chg': {'$lte': -9.5},
         'ts_code': {'$not': {'$regex': '^(688|8|4)'}}},
        {'$set': {'is_limit_down': 1}}
    )
    r5 = col.update_many(
        {'trade_date': date, 'pct_chg': {'$lte': -19.5},
         'ts_code': {'$regex': '^688'}},
        {'$set': {'is_limit_down': 1}}
    )
    r6 = col.update_many(
        {'trade_date': date, 'pct_chg': {'$lte': -29.5},
         'ts_code': {'$regex': '^(8|4)'}},
        {'$set': {'is_limit_down': 1}}
    )
    
    ld_count = r4.modified_count + r5.modified_count + r6.modified_count
    total_updated += lu_count + ld_count
    
    # 设非涨停/跌停为0
    col.update_many(
        {'trade_date': date, 'is_limit_up': {'$exists': False}},
        {'$set': {'is_limit_up': 0}}
    )
    col.update_many(
        {'trade_date': date, 'is_limit_down': {'$exists': False}},
        {'$set': {'is_limit_down': 0}}
    )
    
    if (i+1) % 20 == 0 or i == len(dates)-1:
        print(f"  [{i+1}/{len(dates)}] {date}: 涨停+{lu_count} 跌停+{ld_count} (累计{total_updated})")

print(f"\n  总更新: {total_updated}条")

# ─── Step 3: 验证 ───
print("\n=== Step 3: 验证新数据 ===")
for day in [20260106, 20260107, 20260428]:
    total = col.count_documents({'trade_date': day})
    lu = col.count_documents({'trade_date': day, 'is_limit_up': 1})
    ld = col.count_documents({'trade_date': day, 'is_limit_down': 1})
    
    # 交叉验证: is_limit_up=1的pct_chg范围
    pipeline = [
        {'$match': {'trade_date': day, 'is_limit_up': 1}},
        {'$group': {'_id': None, 'min_pct': {'$min': '$pct_chg'}, 'max_pct': {'$max': '$pct_chg'}, 'count': {'$sum': 1}}}
    ]
    r = list(col.aggregate(pipeline))
    
    # 真正涨停但漏标
    missed = col.count_documents({'trade_date': day, 'pct_chg': {'$gte': 9.5}, 'is_limit_up': 0})
    real = col.count_documents({'trade_date': day, 'pct_chg': {'$gte': 9.5}})
    
    if r:
        info = r[0]
        print(f"  {day}: 涨停{lu}只(最低pct={info['min_pct']:.1f}%,最高={info['max_pct']:.1f}%) | 跌停{ld}只 | 漏标{missed}/{real}")
    else:
        print(f"  {day}: 涨停{lu}只 | 跌停{ld}只")

# ─── Step 4: 重算limit_up_yesterday / limit_down_yesterday / first_limit_up ───
print("\n=== Step 4: 重算limit_up_yesterday/first_limit_up ===")

# 需要按股票遍历，按日期排序
# 用bulk_write批量更新
from pymongo import UpdateOne

dates_int = sorted(col.distinct('trade_date'))
date_idx = {d: i for i, d in enumerate(dates_int)}

# 获取所有涨停/跌停记录
print("  加载涨停/跌停记录...")
lu_records = defaultdict(dict)  # {ts_code: {date: is_limit_up}}
ld_records = defaultdict(dict)

cursor = col.find({'$or': [{'is_limit_up': 1}, {'is_limit_down': 1}]}, 
                   {'ts_code': 1, 'trade_date': 1, 'is_limit_up': 1, 'is_limit_down': 1})
for doc in cursor:
    tc = doc['ts_code']
    d = doc['trade_date']
    if doc.get('is_limit_up') == 1:
        lu_records[tc][d] = True
    if doc.get('is_limit_down') == 1:
        ld_records[tc][d] = True

print(f"  涨停记录: {sum(len(v) for v in lu_records.values())}条, {len(lu_records)}只股票")
print(f"  跌停记录: {sum(len(v) for v in ld_records.values())}条, {len(ld_records)}只股票")

# 按股票计算yesterday和first
bulk_ops = []
for tc, dates_dict in lu_records.items():
    sorted_dates = sorted(dates_dict.keys())
    for d in sorted_dates:
        idx = date_idx.get(d)
        if idx is None:
            continue
        # 前一个交易日
        prev_date = dates_int[idx-1] if idx > 0 else None
        
        lu_yesterday = 1 if (prev_date and prev_date in dates_dict) else 0
        first_lu = 1 if lu_yesterday == 0 else 0  # 首板=今天涨停但昨天不涨停
        
        bulk_ops.append(UpdateOne(
            {'ts_code': tc, 'trade_date': d},
            {'$set': {'limit_up_yesterday': lu_yesterday, 'first_limit_up': first_lu}}
        ))

for tc, dates_dict in ld_records.items():
    sorted_dates = sorted(dates_dict.keys())
    for d in sorted_dates:
        idx = date_idx.get(d)
        if idx is None:
            continue
        prev_date = dates_int[idx-1] if idx > 0 else None
        
        ld_yesterday = 1 if (prev_date and prev_date in dates_dict) else 0
        first_ld = 1 if ld_yesterday == 0 else 0
        
        bulk_ops.append(UpdateOne(
            {'ts_code': tc, 'trade_date': d},
            {'$set': {'limit_down_yesterday': ld_yesterday, 'first_limit_down': first_ld}}
        ))

if bulk_ops:
    print(f"  执行批量更新: {len(bulk_ops)}条...")
    for i in range(0, len(bulk_ops), 5000):
        result = col.bulk_write(bulk_ops[i:i+5000])
        print(f"    [{i}~{i+5000}] matched={result.matched_count} modified={result.modified_count}")

# 设非涨停/跌停的yesterday为0
col.update_many({'limit_up_yesterday': {'$exists': False}}, {'$set': {'limit_up_yesterday': 0}})
col.update_many({'first_limit_up': {'$exists': False}}, {'$set': {'first_limit_up': 0}})
col.update_many({'limit_down_yesterday': {'$exists': False}}, {'$set': {'limit_down_yesterday': 0}})
col.update_many({'first_limit_down': {'$exists': False}}, {'$set': {'first_limit_down': 0}})

# ─── Step 5: 重算limit_up_count/limit_down_count (5日滚动窗口) ───
print("\n=== Step 5: 重算limit_up_count/limit_down_count (5日滚动) ===")

# 对每只股票，计算最近5个交易日的涨停/跌停次数
bulk_ops2 = []
for tc in list(lu_records.keys()):
    lu_dates = sorted(lu_records[tc].keys())
    for d in lu_dates:
        idx = date_idx.get(d)
        if idx is None:
            continue
        # 最近5个交易日(含今天)
        recent_dates = dates_int[max(0, idx-4):idx+1]
        count = sum(1 for rd in recent_dates if rd in lu_records[tc])
        bulk_ops2.append(UpdateOne(
            {'ts_code': tc, 'trade_date': d},
            {'$set': {'limit_up_count': count}}
        ))

for tc in list(ld_records.keys()):
    ld_dates = sorted(ld_records[tc].keys())
    for d in ld_dates:
        idx = date_idx.get(d)
        if idx is None:
            continue
        recent_dates = dates_int[max(0, idx-4):idx+1]
        count = sum(1 for rd in recent_dates if rd in ld_records[tc])
        bulk_ops2.append(UpdateOne(
            {'ts_code': tc, 'trade_date': d},
            {'$set': {'limit_down_count': count}}
        ))

if bulk_ops2:
    print(f"  执行批量更新: {len(bulk_ops2)}条...")
    for i in range(0, len(bulk_ops2), 5000):
        result = col.bulk_write(bulk_ops2[i:i+5000])
        print(f"    [{i}~{i+5000}] matched={result.matched_count} modified={result.modified_count}")

# 设非涨停/跌停的count为0
col.update_many({'limit_up_count': {'$exists': False}}, {'$set': {'limit_up_count': 0}})
col.update_many({'limit_down_count': {'$exists': False}}, {'$set': {'limit_down_count': 0}})

# ─── Step 6: 清除假因子 ───
print("\n=== Step 6: 清除假因子(全0/全None/常量) ===")
fake_fields = ['hot_sector', 'market_leader', 'limit_up_open_count', 'limit_up_open_duration', 'vol_20d']
for f in fake_fields:
    result = col.update_many({f: {'$exists': True}}, {'$unset': {f: ""}})
    print(f"  清除 {f}: {result.modified_count}条")

# ─── Step 7: 最终验证 ───
print("\n=== Step 7: 最终验证 ===")
for day in [20260106, 20260107, 20260428]:
    lu = col.count_documents({'trade_date': day, 'is_limit_up': 1})
    ld = col.count_documents({'trade_date': day, 'is_limit_down': 1})
    first_lu = col.count_documents({'trade_date': day, 'first_limit_up': 1})
    lu_y = col.count_documents({'trade_date': day, 'limit_up_yesterday': 1})
    
    # 涨停的pct_chg范围
    pipeline = [
        {'$match': {'trade_date': day, 'is_limit_up': 1}},
        {'$group': {'_id': None, 'min_pct': {'$min': '$pct_chg'}, 'max_pct': {'$max': '$pct_chg'}}}
    ]
    r = list(col.aggregate(pipeline))
    
    # 漏标
    missed = col.count_documents({'trade_date': day, 'pct_chg': {'$gte': 9.5}, 'is_limit_up': 0})
    real = col.count_documents({'trade_date': day, 'pct_chg': {'$gte': 9.5}})
    
    if r:
        print(f"  {day}: 涨停{lu}(首板{first_lu},昨涨停{lu_y}) pct={r[0]['min_pct']:.1f}%~{r[0]['max_pct']:.1f}% | 跌停{ld} | 漏标{missed}/{real}")
    else:
        print(f"  {day}: 无涨停 | 跌停{ld}")

print("\n✅ 修复完成!")
