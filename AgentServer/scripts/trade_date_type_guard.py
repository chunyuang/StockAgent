#!/usr/bin/env python3
"""trade_date 类型一致性检查与迁移脚本

确保所有含 trade_date 字段的集合统一存储为 int。

用法:
  python3 scripts/trade_date_type_guard.py          # 检查+修复
  python3 scripts/trade_date_type_guard.py --check   # 只检查不修复

Cron: 每工作日 07:00
"""

import sys
import os
from datetime import datetime
from pymongo import MongoClient

# 含 trade_date 的集合白名单
COLLECTIONS_WITH_TRADE_DATE = [
    "scanner_signals",
    "scanner_timeline",
    "scan_traces",
    "broker_orders",
    "broker_positions",
    "premarket_snapshots",
    "sentiment_scores",
    "sentiment_live_log",
    "scanner_runtime_snapshot",
    "performance_snapshots",
    "risk_decisions",
    "scan_date_cache",
]

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "stock_agent")


def main():
    check_only = "--check" in sys.argv
    mc = MongoClient(MONGO_URI)
    db = mc[DB_NAME]
    
    issues = []
    fixed = []
    
    for coll_name in COLLECTIONS_WITH_TRADE_DATE:
        if coll_name not in db.list_collection_names():
            continue
        
        coll = db[coll_name]
        
        # 统计 string 类型的 trade_date
        string_count = coll.count_documents({"trade_date": {"$type": "string"}})
        
        if string_count > 0:
            issues.append(f"  {coll_name}: {string_count} 条 trade_date 为 string")
            
            if not check_only:
                # 迁移 string → int
                result = coll.update_many(
                    {"trade_date": {"$type": "string"}},
                    [{"$set": {"trade_date": {"$toInt": "$trade_date"}}}]
                )
                fixed.append(f"  {coll_name}: 修复 {result.modified_count} 条")
    
    # 检查是否有集合用了 date 而非 trade_date
    for coll_name in db.list_collection_names():
        if coll_name.startswith("system."):
            continue
        # 检查是否有 date 字段但无 trade_date
        sample = db[coll_name].find_one({"date": {"$exists": True}, "trade_date": {"$exists": False}})
        if sample and coll_name not in ("audit_log",):
            issues.append(f"  {coll_name}: 有 date 字段但无 trade_date (sample: {sample.get('date')})")
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if issues:
        print(f"[{now}] ⚠️ trade_date 类型问题:")
        for i in issues:
            print(i)
        if fixed:
            print(f"[{now}] ✅ 已修复:")
            for f in fixed:
                print(f)
    else:
        print(f"[{now}] ✅ 所有集合 trade_date 类型一致 (int)")
    
    # 输出各集合统计
    if check_only or not issues:
        print(f"\n各集合 trade_date 类型统计:")
        for coll_name in COLLECTIONS_WITH_TRADE_DATE:
            if coll_name not in db.list_collection_names():
                continue
            pipeline = [
                {"$group": {"_id": {"$type": "$trade_date"}, "count": {"$sum": 1}}},
            ]
            types = list(db[coll_name].aggregate(pipeline))
            type_str = ", ".join(f"{t['_id']}={t['count']}" for t in types) or "无 trade_date 字段"
            total = db[coll_name].count_documents({})
            print(f"  {coll_name} (total={total}): {type_str}")
    
    mc.close()
    return 1 if issues and check_only else 0


if __name__ == "__main__":
    sys.exit(main())
