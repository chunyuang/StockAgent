"""分月预计算因子 - 避免2年数据一次性加载导致OOM/MongoDB超时"""
import asyncio, sys, os, types, time
import pandas as pd
import numpy as np

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

# 因子计算函数（从factor_auto_compute复用）
from nodes.backtest_engine.factor_selection.factor_auto_compute import _compute_factors_for_stock, ALL_COMPUTABLE_FIELDS

MONTHS = []
# 2024年5月~2026年5月，按月
for y in range(2024, 2027):
    for m in range(1, 13):
        if y == 2024 and m < 5:
            continue
        if y == 2026 and m > 5:
            continue
        MONTHS.append((y, m))

def month_range(y, m):
    """返回YYYYMMDD格式的月初/月末"""
    start = int(f"{y}{m:02d}01")
    if m == 12:
        end = int(f"{y+1}0101")
    else:
        end = int(f"{y}{m+1:02d}01")
    return start, end

async def precompute_month(year, month):
    """预计算一个月的因子"""
    start, end = month_range(year, month)
    # 回溯3个月用于MA60
    lookback = start - 30000  # 粗略：减3个月
    if year == 2024 and month <= 7:
        lookback = 20240101  # 不回溯太远
    
    coll = mongo_manager.db["stock_daily_ak_full"]
    
    # 加载数据
    cursor = coll.find(
        {"trade_date": {"$gte": lookback, "$lt": end}},
        {"_id": 1, "ts_code": 1, "trade_date": 1,
         "open": 1, "high": 1, "low": 1, "close": 1,
         "pct_chg": 1, "vol": 1, "amount": 1, "pre_close": 1,
         "turnover_rate": 1, "volume_ratio": 1, "circ_mv": 1}
    )
    docs = await cursor.to_list(length=None)
    if not docs:
        print(f"  {year}-{month:02d}: 无数据，跳过")
        return 0
    
    df = pd.DataFrame(docs)
    
    # 合并daily_basic
    db_coll = mongo_manager.db["daily_basic"]
    db_cursor = db_coll.find(
        {"trade_date": {"$gte": lookback, "$lt": end}},
        {"ts_code": 1, "trade_date": 1, "turnover_rate": 1, "volume_ratio": 1,
         "circ_mv": 1, "pe": 1, "pe_ttm": 1, "pb": 1, "total_mv": 1}
    )
    db_docs = await db_cursor.to_list(length=None)
    if db_docs:
        db_df = pd.DataFrame(db_docs)
        db_df = db_df.drop(columns=['_id'], errors='ignore')
        df = df.merge(db_df, on=['ts_code', 'trade_date'], how='left', suffixes=('', '_db'))
        for col in ['turnover_rate', 'volume_ratio', 'circ_mv', 'pe', 'pe_ttm', 'pb', 'total_mv']:
            db_col = f'{col}_db'
            if db_col in df.columns:
                df[col] = df[db_col].fillna(df.get(col))
                df = df.drop(columns=[db_col])
    
    # 分股票计算
    computed_groups = []
    for ts_code, group in df.groupby('ts_code'):
        group = group.sort_values('trade_date').copy()
        computed = _compute_factors_for_stock(group, ALL_COMPUTABLE_FIELDS)
        computed_groups.append(computed)
    
    if not computed_groups:
        print(f"  {year}-{month:02d}: 计算后无数据")
        return 0
    
    final_df = pd.concat(computed_groups, ignore_index=True)
    # 只保留当月
    final_df = final_df[(final_df['trade_date'] >= start) & (final_df['trade_date'] < end)]
    final_df = final_df.replace({np.nan: None})
    
    # 批量写入MongoDB（upsert因子字段）
    records_updated = 0
    batch_size = 500
    updates = []
    for _, row in final_df.iterrows():
        update_fields = {}
        for f in ALL_COMPUTABLE_FIELDS:
            if f in row and row[f] is not None:
                update_fields[f] = row[f]
        if not update_fields:
            continue
        updates.append({
            "filter": {"ts_code": row['ts_code'], "trade_date": int(row['trade_date'])},
            "update": {"$set": update_fields}
        })
        if len(updates) >= batch_size:
            for u in updates:
                try:
                    await coll.update_one(u["filter"], u["update"], upsert=False)
                except Exception as e:
                    pass
            records_updated += len(updates)
            updates = []
    
    # 剩余
    for u in updates:
        try:
            await coll.update_one(u["filter"], u["update"], upsert=False)
        except:
            pass
    records_updated += len(updates)
    
    print(f"  {year}-{month:02d}: {len(df):,}条加载 → {records_updated:,}条更新")
    return records_updated

async def main():
    await mongo_manager.initialize()
    print(f"🧮 预计算因子: {len(MONTHS)}个月, 字段数: {len(ALL_COMPUTABLE_FIELDS)}")
    
    total_updated = 0
    t0 = time.time()
    for i, (y, m) in enumerate(MONTHS):
        try:
            n = await precompute_month(y, m)
            total_updated += n
        except Exception as e:
            print(f"  {y}-{m:02d}: ❌ {e}")
        
        if (i+1) % 6 == 0:
            elapsed = time.time() - t0
            print(f"  📊 进度: {i+1}/{len(MONTHS)}月 | 累计{total_updated:,}条 | {elapsed:.0f}s")
    
    elapsed = time.time() - t0
    print(f"\n✅ 完成! 累计更新{total_updated:,}条 | 耗时{elapsed:.0f}s")

asyncio.run(main())
