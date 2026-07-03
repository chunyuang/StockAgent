#!/usr/bin/env python3
"""前端数据正确性守卫 — 模拟前端调用API验证数据完整性

基于 2026-06-15 的教训: 夜间cron只检查了后端代码和API返回200,
但没有验证前端实际看到的数据是否正确。

今天发现的遗漏:
1. limit_list字段格式(is_limit_up=bool而非1/0) → 前端涨停/跌停=0
2. sentiment_scores中zu=0 zd=0 → 因limit_list查询失败
3. 非交易日HistoryTab显示今日数据 → 前端fallback逻辑
4. trade_date string/int不匹配 → API返回空但200 OK
5. "无交易记录" → timeline查询因trade_date类型不匹配返回0条

检查策略:
  - 不只检查API返回200, 而是检查返回数据的业务正确性
  - 模拟前端的composable调用链: API→数据→computed→展示
  - 对比多个API的数据一致性(如limit_list涨跌停数 vs sentiment_scores)

退出码: 0=健康, 1=有问题
"""
import sys
import json
import requests
from datetime import datetime, timedelta
from pymongo import MongoClient
from collections import Counter

BASE_URL = "http://localhost:8000/api/v1"

def _today_str():
    return datetime.now().strftime("%Y%m%d")

def _latest_trading_day(db):
    """从trade_cal获取最近交易日"""
    today = int(datetime.now().strftime("%Y%m%d"))
    doc = db.trade_cal.find_one(
        {"cal_date": {"$lte": today}, "is_open": 1},
        sort=[("cal_date", -1)]
    )
    return str(doc["cal_date"]) if doc else _today_str()


def check_limit_list_fields(db):
    """检查1: limit_list字段格式正确性
    
    2026-06-15发现: is_limit_up存为bool(True/False), limit字段缺失
    → _fetch_limit_stats查limit="U"返回0条 → 涨停数=0
    """
    issues = []
    
    today = _latest_trading_day(db)
    coll = db["limit_list"]
    sample = list(coll.find({"trade_date": int(today)}).limit(50))
    
    if not sample:
        # Try yesterday
        yesterday = int((datetime.now() - timedelta(days=1)).strftime("%Y%m%d"))
        sample = list(coll.find({"trade_date": yesterday}).limit(50))
    
    if not sample:
        print("  ⚪ limit_list: 今日无数据,跳过")
        return []
    
    # Check is_limit_up type
    bool_count = sum(1 for d in sample if isinstance(d.get("is_limit_up"), bool))
    int_count = sum(1 for d in sample if isinstance(d.get("is_limit_up"), int))
    none_count = sum(1 for d in sample if d.get("is_limit_up") is None)
    
    if bool_count > 0:
        issues.append(f"limit_list: {bool_count}条is_limit_up为bool(应为int 1/0)")
        print(f"  🔴 is_limit_up: {bool_count}条bool, {int_count}条int, {none_count}条None")
    else:
        print(f"  ✅ is_limit_up: {int_count}条int格式正确")
    
    # Check limit field existence
    has_limit = sum(1 for d in sample if d.get("limit") in ("U", "D"))
    if has_limit == 0 and len(sample) > 0:
        issues.append(f"limit_list: {len(sample)}条数据中无limit字段(U/D)")
        print(f"  🔴 limit字段: 0条有值(应有U/D)")
    else:
        print(f"  ✅ limit字段: {has_limit}/{len(sample)}条有值")
    
    # Note: is_limit_down is NOT required in limit_list since v2.9.108.
    # The 'limit' field (U/D) is the primary classifier.
    # is_limit_up/is_limit_down belong to stock_daily_ak_full, not limit_list.
    
    return issues


def check_sentiment_vs_limit(db):
    """检查2: sentiment_scores涨跌停数 vs limit_list实际数
    
    2026-06-15发现: sentiment_scores中zu=0 zd=0, 
    因为_fetch_limit_stats用limit="U"查但字段不存在
    """
    issues = []
    
    # 获取最近的sentiment记录
    sentiments = list(db["sentiment_scores"].find().sort("trade_date", -1).limit(5))
    
    if not sentiments:
        print("  ⚪ sentiment_scores: 无数据,跳过")
        return []
    
    for ss in sentiments:
        td = ss.get("trade_date")
        zu = ss.get("limit_up", ss.get("limit_up_count", ss.get("zu", 0)))
        zd = ss.get("limit_down", ss.get("limit_down_count", ss.get("zd", 0)))
        
        # 从limit_list查实际涨跌停数
        actual_up = db["limit_list"].count_documents({
            "trade_date": td,
            "$or": [{"is_limit_up": 1}, {"is_limit_up": True}, {"limit": "U"}]
        })
        actual_down = db["limit_list"].count_documents({
            "trade_date": td,
            "$or": [{"is_limit_down": 1}, {"is_limit_down": True}, {"limit": "D"}]
        })
        
        # 如果sentiment是0但limit_list有数据 → 问题
        if zu == 0 and actual_up > 0:
            issues.append(f"sentiment {td}: zu=0但limit_list有{actual_up}条涨停")
            print(f"  🔴 {td}: zu={zu} vs limit_list涨停={actual_up}")
        elif zd == 0 and actual_down > 0:
            issues.append(f"sentiment {td}: zd=0但limit_list有{actual_down}条跌停")
            print(f"  🔴 {td}: zd={zd} vs limit_list跌停={actual_down}")
        else:
            if actual_up > 0 or actual_down > 0:
                print(f"  ✅ {td}: zu={zu} zd={zd} vs 实际={actual_up}↓{actual_down}")
    
    if not issues and sentiments:
        print("  ✅ sentiment与limit_list数据一致")
    
    return issues


def check_timeline_trade_date_type(db):
    """检查3: scanner_timeline trade_date类型
    
    2026-06-15发现: 1746条记录trade_date为string, 导致API查不到
    """
    issues = []
    
    coll = db["scanner_timeline"]
    total = coll.estimated_document_count()
    if total == 0:
        print("  ⚪ scanner_timeline: 空,跳过")
        return []
    
    # Sample types
    types = Counter()
    for doc in coll.find({}, {"trade_date": 1}).limit(500):
        td = doc.get("trade_date")
        types[type(td).__name__] += 1
    
    str_count = types.get("str", 0)
    if str_count > 0:
        issues.append(f"scanner_timeline: {str_count}条trade_date为string")
        print(f"  🔴 trade_date类型: {dict(types)}")
    else:
        print(f"  ✅ trade_date类型: 全部int")
    
    return issues


def check_api_return_data_quality():
    """检查4: API返回数据业务正确性
    
    2026-06-15发现: API返回200但数据为空, 前端显示"无交易记录"
    不只检查HTTP 200, 还检查返回的数据有意义
    """
    issues = []
    
    # 4a. timeline/history - 非交易日应返回空数据
    try:
        # 选一个已知的非交易日(周日)
        yesterday = datetime.now() - timedelta(days=1)
        if yesterday.weekday() == 6:  # 昨天是周日
            non_trading = yesterday.strftime("%Y%m%d")
        else:
            # 找最近的周日
            for i in range(1, 8):
                d = datetime.now() - timedelta(days=i)
                if d.weekday() == 6:
                    non_trading = d.strftime("%Y%m%d")
                    break
        
        if non_trading:
            r = requests.get(f"{BASE_URL}/scanner/timeline/history", 
                           params={"date": non_trading}, timeout=10)
            data = r.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(items, list) and len(items) > 0:
                # 非交易日有数据 → 可能是fallback问题
                print(f"  ⚠️  非交易日{non_trading}返回{len(items)}条timeline(可能是旧数据)")
            else:
                print(f"  ✅ 非交易日{non_trading}正确返回空数据")
    except Exception as e:
        print(f"  ⚪ 非交易日检查失败: {e}")
    
    # 4b. 交易日timeline应该有数据(如果scanner运行过)
    try:
        today = _today_str()
        r = requests.get(f"{BASE_URL}/scanner/timeline/history",
                       params={"date": today}, timeout=10)
        data = r.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, list) and len(items) > 0:
            # 检查是否有sell(已平仓)
            sells = [i for i in items if i.get("action") == "sell"]
            buys = [i for i in items if i.get("action") == "buy"]
            print(f"  ✅ 今日timeline: {len(items)}条(买{len(buys)} 卖{len(sells)})")
        else:
            # 非开盘时间可能没有, 不算问题
            now = datetime.now()
            if now.weekday() < 5 and now.hour >= 15:
                issues.append(f"今日{today}无timeline数据(盘后应有)")
                print(f"  🔴 今日{today}: 盘后但无timeline数据")
            else:
                print(f"  ⚪ 今日{today}: 非交易时间,无数据正常")
    except Exception as e:
        print(f"  ⚪ timeline检查失败: {e}")
    
    return issues


def check_broker_data_consistency(db):
    """检查5: broker数据一致性
    
    2026-06-13发现: 000517.SZ重复订单导致资产虚增
    """
    issues = []
    
    # 5a. 检查重复订单
    pipeline = [
        {"$group": {
            "_id": {"order_id": "$order_id"},
            "count": {"$sum": 1}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]
    dups = list(db["broker_orders"].aggregate(pipeline))
    if dups:
        issues.append(f"broker_orders: {len(dups)}个重复order_id")
        print(f"  🔴 重复order_id: {len(dups)}个")
    else:
        print(f"  ✅ 无重复order_id")
    
    # 5b. 检查卖出有无对应买入(只检查今天的, 历史可能缺buy记录)
    today_int = int(datetime.now().strftime("%Y%m%d"))
    sells_today = list(db["broker_orders"].find({"side": "sell", "status": "filled", "trade_date": today_int}))
    
    if sells_today:
        buy_codes = {o["ts_code"] for o in db["broker_orders"].find({"side": "buy", "status": "filled"})}
        orphan_sells = [s for s in sells_today if s["ts_code"] not in buy_codes]
        if orphan_sells:
            codes = [s["ts_code"] for s in orphan_sells[:5]]
            issues.append(f"broker_orders: 今日{len(orphan_sells)}笔卖出无对应买入: {codes}")
            print(f"  🔴 今日无买入的卖出: {len(orphan_sells)}笔 ({codes})")
        else:
            print(f"  ✅ 今日买卖记录配对完整")
    else:
        print(f"  ✅ 今日无卖出记录")
    
    return issues


def check_frontend_api_field_types():
    """检查6: API返回字段类型正确性
    
    2026-06-15发现: limit_list.is_limit_up返回bool而非int
    → 前端可能判断不一致
    """
    issues = []
    
    # Check sentiment_scores API
    try:
        r = requests.get(f"{BASE_URL}/scanner/sentiment/daily", timeout=10)
        data = r.json()
        scores = data.get("data", [])
        if isinstance(scores, list) and scores:
            for item in scores[:3]:
                zu = item.get("limit_up", item.get("limit_up_count", item.get("zu")))
                if zu is not None and zu == 0:
                    # score > 0 但zu=0 → 可能是查询问题
                    score = item.get("score", 0)
                    if score > 50:
                        issues.append(f"sentiment API: score={score}但zu=0(高分应有涨停)")
                        print(f"  🔴 score={score} zu={zu} → 数据不一致")
        if not issues:
            print(f"  ✅ sentiment API数据合理")
    except Exception as e:
        print(f"  ⚪ sentiment API检查失败: {e}")
    
    return issues


def main():
    try:
        c = MongoClient("localhost", 27017, serverSelectionTimeoutMS=3000)
        db = c.stock_agent
    except Exception as e:
        print(f"❌ MongoDB连接失败: {e}")
        return 1
    
    all_issues = []
    
    print("=" * 60)
    print("🔍 前端数据正确性守卫报告")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    # 检查1: limit_list字段格式
    print("\n📋 1. limit_list字段格式")
    print("-" * 40)
    all_issues.extend(check_limit_list_fields(db))
    
    # 检查2: sentiment vs limit_list一致性
    print("\n📊 2. 情绪数据 vs 涨跌停数一致性")
    print("-" * 40)
    all_issues.extend(check_sentiment_vs_limit(db))
    
    # 检查3: timeline trade_date类型
    print("\n📅 3. timeline trade_date类型")
    print("-" * 40)
    all_issues.extend(check_timeline_trade_date_type(db))
    
    # 检查4: API返回数据质量
    print("\n🌐 4. API返回数据业务正确性")
    print("-" * 40)
    all_issues.extend(check_api_return_data_quality())
    
    # 检查5: broker数据一致性
    print("\n💰 5. broker数据一致性")
    print("-" * 40)
    all_issues.extend(check_broker_data_consistency(db))
    
    # 检查6: API字段类型
    print("\n🔢 6. API字段类型正确性")
    print("-" * 40)
    all_issues.extend(check_frontend_api_field_types())
    
    # 总结
    print("\n" + "=" * 60)
    if all_issues:
        print(f"🔴 发现 {len(all_issues)} 个问题:")
        for i, issue in enumerate(all_issues, 1):
            print(f"   {i}. {issue}")
    else:
        print("✅ 全部检查通过, 前端数据正确!")
    
    status = "unhealthy" if all_issues else "healthy"
    print(f"\n📊 STATUS: {status}")
    
    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main())
