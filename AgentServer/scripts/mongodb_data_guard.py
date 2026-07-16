#!/usr/bin/env python3
"""MongoDB 数据格式守卫 — 每日定时检查

检查项:
1. trade_date 类型一致性: 确保关键集合中 trade_date 全部为 int
2. 必填字段完整性: 抽样检查关键字段不为 None
3. 重复数据检测: ts_code + trade_date 不应有重复
4. 日期连续性: 对比交易日历, 检查是否有缺失交易日

退出码: 0=健康, 1=有问题
"""
import sys
from collections import Counter
from pymongo import MongoClient

# 关键集合 + 必填字段
CHECKED_COLLECTIONS = {
    "stock_daily_ak_full": ["ts_code", "trade_date", "open", "high", "low", "close"],
    "daily_basic": ["ts_code", "trade_date", "pe_ttm", "pb"],
    "limit_list": ["ts_code", "trade_date", "is_limit_up"],
    "broker_orders": ["ts_code", "trade_date", "side", "status"],
    "scanner_timeline": ["trade_date", "action"],
    "scan_traces": ["trade_date"],
    "sentiment_scores": ["trade_date", "score", "period"],
}

def main():
    c = MongoClient("localhost", 27017)
    db = c.stock_agent
    
    issues = []
    warnings = []
    
    print("=" * 60)
    print("🔍 MongoDB 数据格式守卫报告")
    print("=" * 60)
    
    # ====== 1. trade_date 类型一致性 ======
    print("\n📅 1. trade_date 类型一致性检查")
    print("-" * 40)
    
    for coll_name, _ in CHECKED_COLLECTIONS.items():
        coll = db[coll_name]
        total = coll.estimated_document_count()
        if total == 0:
            print(f"  ⚪ {coll_name}: 空集合, 跳过")
            continue
        
        # 抽样检查
        sample_size = min(total, 2000)
        type_counts = Counter()
        for doc in coll.find({}, {"trade_date": 1}).limit(sample_size):
            td = doc.get("trade_date")
            type_counts[type(td).__name__] += 1
        
        if len(type_counts) > 1:
            # 有混合类型!
            detail = ", ".join(f"{t}:{c}" for t, c in type_counts.items())
            print(f"  🔴 {coll_name}: 混合类型! ({detail})")
            issues.append(f"{coll_name}: trade_date混合类型({detail})")
            
            # 自动修复: 统计有多少string类型的
            str_count = type_counts.get("str", 0)
            if str_count > 0:
                # 提示修复命令
                print(f"     → 需修复 {str_count} 条 string 类型的 trade_date")
        elif "str" in type_counts:
            # 全部是string — 需要全量转换
            str_count = type_counts["str"]
            print(f"  🔴 {coll_name}: 全部 {total} 条为 string 类型 (应为 int)")
            issues.append(f"{coll_name}: trade_date全为string({total}条)")
        elif "int" in type_counts:
            print(f"  ✅ {coll_name}: {total:,} 条, trade_date 全部为 int")
        elif "NoneType" in type_counts:
            print(f"  ⚠️  {coll_name}: trade_date 全部为 None")
            warnings.append(f"{coll_name}: trade_date全为None")
    
    # ====== 2. 必填字段完整性 ======
    print("\n📋 2. 必填字段完整性检查 (抽样100条)")
    print("-" * 40)
    
    for coll_name, required_fields in CHECKED_COLLECTIONS.items():
        coll = db[coll_name]
        total = coll.estimated_document_count()
        if total == 0:
            continue
        
        sample = list(coll.find().limit(100))
        missing = Counter()
        for doc in sample:
            for field in required_fields:
                if field not in doc or doc[field] is None:
                    missing[field] += 1
        
        if missing:
            detail = ", ".join(f"{f}:{c}/100" for f, c in missing.items())
            print(f"  ⚠️  {coll_name}: 字段缺失 ({detail})")
            warnings.append(f"{coll_name}: 字段缺失({detail})")
        else:
            print(f"  ✅ {coll_name}: 所有必填字段完整")
    
    # ====== 3. 重复数据检测 ======
    print("\n🔄 3. 重复数据检测 (最近3天)")
    print("-" * 40)
    
    for coll_name in ["stock_daily_ak_full", "daily_basic", "limit_list"]:
        coll = db[coll_name]
        if coll.estimated_document_count() == 0:
            continue
        
        pipeline = [
            {"$sort": {"trade_date": -1}},
            {"$limit": 20000},
            {"$group": {
                "_id": {"ts_code": "$ts_code", "trade_date": "$trade_date"},
                "count": {"$sum": 1}
            }},
            {"$match": {"count": {"$gt": 1}}},
            {"$count": "duplicates"}
        ]
        try:
            result = list(coll.aggregate(pipeline))
            dup_count = result[0]["duplicates"] if result else 0
            if dup_count > 0:
                print(f"  🔴 {coll_name}: {dup_count} 组重复数据")
                issues.append(f"{coll_name}: {dup_count}组重复数据")
            else:
                print(f"  ✅ {coll_name}: 无重复数据")
        except Exception as e:
            print(f"  ⚪ {coll_name}: 检查失败 ({e})")
    
    # ====== 4. 日期连续性 ======
    print("\n📆 4. 交易日连续性检查 (最近30天)")
    print("-" * 40)
    
    try:
        # 从 trade_cal 获取最近30个交易日
        trade_cal = db["trade_cal"]
        calendar = list(trade_cal.find(
            {"is_open": 1},
            {"cal_date": 1, "_id": 0}
        ).sort("cal_date", -1).limit(30))
        
        if calendar:
            trading_dates = set(doc["cal_date"] for doc in calendar)
            coll = db["stock_daily_ak_full"]
            # 检查每个交易日有多少数据
            missing_days = []
            low_days = []
            # 只检查最近10个已经过去的交易日(不含未来)
            from datetime import datetime
            today_int = int(datetime.now().strftime('%Y%m%d'))
            past_dates = sorted([td for td in trading_dates if td <= today_int], reverse=True)[:10]
            
            for td in past_dates:
                count = coll.count_documents({"trade_date": td})
                if count == 0:
                    missing_days.append(td)
                elif count < 4000:
                    low_days.append((td, count))
            
            if missing_days:
                print(f"  🔴 缺失交易日: {missing_days}")
                issues.append(f"缺失交易日: {missing_days}")
            if low_days:
                for td, cnt in low_days:
                    print(f"  ⚠️  {td}: 仅 {cnt} 条数据 (<4000)")
                    warnings.append(f"{td}: 仅{cnt}条数据")
            if not missing_days and not low_days:
                print("  ✅ 最近10个交易日数据完整")
    except Exception as e:
        print(f"  ⚪ 交易日连续性检查失败: {e}")
    
    # ====== 总结 ======
    print("\n" + "=" * 60)
    if issues:
        print(f"🔴 发现 {len(issues)} 个问题:")
        for i, issue in enumerate(issues, 1):
            print(f"   {i}. {issue}")
    if warnings:
        print(f"⚠️  发现 {len(warnings)} 个警告:")
        for i, w in enumerate(warnings, 1):
            print(f"   {i}. {w}")
    if not issues and not warnings:
        print("✅ 全部检查通过, 数据格式健康!")
    
    # 输出 JSON 摘要(供飞书通知)
    summary = {
        "issues": issues,
        "warnings": warnings,
        "status": "unhealthy" if issues else ("warning" if warnings else "healthy")
    }
    print(f"\n📊 STATUS: {summary['status']}")
    
    return 1 if issues else 0

if __name__ == "__main__":
    sys.exit(main())
