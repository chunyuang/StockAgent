#!/usr/bin/env python3
"""
夜审数据完整性检查 + 自动补全

检查维度:
1. 今日stock_daily_ak_full因子完整性(MACD/RSI/BOLL/ATR/MA等)
2. daily_basic字段完整性(PE/PB/换手率/流通市值)
3. limit_list涨停跌停数据
4. sentiment_scores与limit_list一致性
5. broker_orders的commission/stamp_duty完整性
6. broker_positions的market_value完整性

补全策略:
- 发现缺失 -> 自动调lightweight_factor_fill.py补全
- 补全后重新验证 -> 仍缺失则记录待补
- 输出JSON报告供夜审cron使用
"""
import sys, os, time, json, subprocess, asyncio
from pathlib import Path
from datetime import datetime, timedelta

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

REPORT = {"checks": [], "fills": [], "pending": [], "summary": ""}

def check(name, passed, detail=""):
    status = "✅" if passed else "🔴"
    entry = {"name": name, "passed": passed, "detail": detail}
    REPORT["checks"].append(entry)
    print(f"  {status} {name}: {detail}")
    return passed

async def run():
    import pymongo
    db = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=5000)["stock_agent"]
    
    # 确定最近交易日
    today = datetime.now()
    today_int = int(today.strftime("%Y%m%d"))
    
    # 找最近3个有数据的交易日
    recent_dates = []
    for doc in db["stock_daily_ak_full"].find({}, {"trade_date": 1, "_id": 0}).sort("trade_date", -1).limit(100):
        td = doc.get("trade_date")
        if td and td not in recent_dates:
            recent_dates.append(td)
        if len(recent_dates) >= 3:
            break
    
    if not recent_dates:
        print("🔴 无任何交易日数据!")
        REPORT["summary"] = "无数据"
        return
    
    latest = recent_dates[0]
    print(f"═══ 夜审数据完整性检查 {datetime.now().strftime('%Y-%m-%d %H:%M')} ═══")
    print(f"最近交易日: {recent_dates[:3]}\n")
    
    # ═══ 1. stock_daily_ak_full 因子完整性 ═══
    print("═══ 1. 因子完整性 (stock_daily_ak_full) ═══")
    factor_fields = {
        'macd': 0.90, 'rsi_6': 0.90, 'boll_upper': 0.90, 'atr': 0.90,
        'ma5': 0.95, 'ma10': 0.90, 'ma20': 0.90, 'ma60': 0.80,
        'turnover_rate': 0.95, 'volume_ratio': 0.95, 'pe_ttm': 0.80, 'pb': 0.80,
        'is_limit_up': 0.01, 'opening_pct_chg': 0.80, 'intraday_max_rise_pct': 0.80,
        'pullback_pct': 0.80, 'fear_greed_index': 0.80, 'limit_up_count': 0.80,
    }
    
    need_fill_dates = []
    for td in recent_dates[:3]:
        total = db["stock_daily_ak_full"].count_documents({"trade_date": td})
        if total == 0:
            check(f"{td} 存在性", False, "无数据")
            need_fill_dates.append(td)
            continue
        
        missing_fields = []
        for field, threshold in factor_fields.items():
            if field == 'is_limit_up':
                # 只检查涨停票是否有此字段
                lu_total = db["stock_daily_ak_full"].count_documents({"trade_date": td, "is_limit_up": 1})
                lu_has = db["stock_daily_ak_full"].count_documents({"trade_date": td, "is_limit_up": 1, field: {"$exists": True}})
                if lu_total > 0 and lu_has < lu_total * 0.9:
                    missing_fields.append(f"{field}({lu_has}/{lu_total}涨停票)")
                continue
            if field == 'limit_up_count':
                # limit_up_count只给涨停票设(非涨停=0/不存在)
                lu_total = db["stock_daily_ak_full"].count_documents({"trade_date": td, "is_limit_up": 1})
                lu_has = db["stock_daily_ak_full"].count_documents({"trade_date": td, "is_limit_up": 1, field: {"$exists": True, "$ne": 0}})
                if lu_total > 0 and lu_has < lu_total * 0.9:
                    missing_fields.append(f"{field}({lu_has}/{lu_total}涨停票)")
                continue
            cnt = db["stock_daily_ak_full"].count_documents({
                "trade_date": td, field: {"$exists": True, "$ne": 0}
            })
            ratio = cnt / total if total > 0 else 0
            if ratio < threshold:
                missing_fields.append(f"{field}({ratio:.0%})")
        
        if missing_fields:
            check(f"{td} 因子完整性", False, f"缺失: {', '.join(missing_fields)}")
            need_fill_dates.append(td)
        else:
            check(f"{td} 因子完整性", True, f"{total}条全部完整")
    
    # ═══ 2. daily_basic 字段完整性 ═══
    print("\n═══ 2. daily_basic 完整性 ═══")
    for td in recent_dates[:3]:
        total = db["daily_basic"].count_documents({"trade_date": td})
        if total == 0:
            check(f"{td} daily_basic", False, "无数据")
        else:
            no_pe = db["daily_basic"].count_documents({"trade_date": td, "pe_ttm": {"$exists": False}})
            no_pb = db["daily_basic"].count_documents({"trade_date": td, "pb": {"$exists": False}})
            no_tr = db["daily_basic"].count_documents({"trade_date": td, "turnover_rate": {"$exists": False}})
            issues = []
            if no_pe > total * 0.3: issues.append(f"PE缺{no_pe}")
            if no_pb > total * 0.3: issues.append(f"PB缺{no_pb}")
            if no_tr > total * 0.3: issues.append(f"换手率缺{no_tr}")
            check(f"{td} daily_basic", len(issues) == 0, f"{total}条, {', '.join(issues) or '完整'}")
    
    # ═══ 3. limit_list 涨跌停数据 ═══
    print("\n═══ 3. limit_list 完整性 ═══")
    for td in recent_dates[:3]:
        lu = db["limit_list"].count_documents({"trade_date": td, "limit": "U"})
        ld = db["limit_list"].count_documents({"trade_date": td, "limit": "D"})
        total_ll = db["limit_list"].count_documents({"trade_date": td})
        # 交叉验证: ak_full的is_limit_up
        ak_lu = db["stock_daily_ak_full"].count_documents({"trade_date": td, "is_limit_up": 1})
        diff = abs(lu - ak_lu)
        # limit_list来源是必盈API, ak_fast来源是东方财富, 两者判定涨停的口径略有差异
        # limit_list用limit=U, ak_full用pct_chg>=9.5%/19.5%
        # 差异<=15是正常的(新股/ST/20cm涨停票在必盈API中可能缺失)
        check(f"{td} limit_list", diff <= 15, f"涨停={lu}(ak:{ak_lu}) 跌停={ld} 总={total_ll} 差异={diff}(<=15正常)")
    
    # ═══ 4. sentiment_scores 与 limit_list 一致性 ═══
    print("\n═══ 4. sentiment一致性 ═══")
    for td in recent_dates[:3]:
        sent = db["sentiment_scores"].find_one({"trade_date": td})
        if not sent:
            check(f"{td} sentiment", False, "无数据")
            continue
        
        ll_lu = db["limit_list"].count_documents({"trade_date": td, "limit": "U"})
        ll_ld = db["limit_list"].count_documents({"trade_date": td, "limit": "D"})
        sent_lu = sent.get("limit_up", 0)
        sent_ld = sent.get("limit_down", 0)
        formula = sent.get("formula", "?")
        
        lu_match = sent_lu == ll_lu
        ld_match = sent_ld == ll_ld
        is_5dim = formula == "5dim"
        
        if not is_5dim:
            check(f"{td} sentiment", False, f"formula={formula}(非5dim), lu={sent_lu}/{ll_lu} ld={sent_ld}/{ll_ld}")
        elif lu_match and ld_match:
            check(f"{td} sentiment", True, f"score={sent.get('score')} period={sent.get('period')} lu={sent_lu} ld={sent_ld}")
        else:
            check(f"{td} sentiment", False, f"lu不匹配({sent_lu}/{ll_lu}) ld不匹配({sent_ld}/{ll_ld})")
    
    # ═══ 5. broker_orders commission/stamp_duty 完整性 ═══
    print("\n═══ 5. 交易数据完整性 ═══")
    filled_orders = list(db["broker_orders"].find({"status": "filled", "account_id": "default"}))
    no_comm = sum(1 for o in filled_orders if not o.get("commission"))
    no_stamp = sum(1 for o in filled_orders if o.get("side") == "sell" and not o.get("stamp_duty"))
    no_profit = sum(1 for o in filled_orders if o.get("side") == "sell" and not o.get("profit_amount"))
    
    check("orders commission", no_comm == 0, f"{no_comm}/{len(filled_orders)}笔无commission")
    check("orders stamp_duty", no_stamp == 0, f"{no_stamp}笔sell无stamp_duty")
    check("orders profit", no_profit == 0, f"{no_profit}笔sell无profit_amount")
    
    # ═══ 6. broker_positions market_value ═══
    print("\n═══ 6. 持仓数据完整性 ═══")
    positions = list(db["broker_positions"].find({"account_id": "default", "total_qty": {"$gt": 0}}))
    no_mv = sum(1 for p in positions if not p.get("market_value") or p.get("market_value", 0) <= 0)
    no_stop = sum(1 for p in positions if not p.get("stop_loss_price") or p.get("stop_loss_price", 0) <= 0)
    check("positions market_value", no_mv == 0, f"{no_mv}/{len(positions)}只无market_value")
    check("positions stop_loss", no_stop == 0, f"{no_stop}/{len(positions)}只无stop_loss_price")
    
    # ═══ 7. cash漂移 ═══
    print("\n═══ 7. 资金闭环 ═══")
    cash = 1_000_000
    for o in filled_orders:
        qty = o.get("filled_qty", 0) or 0
        price = o.get("filled_price", 0) or 0
        comm = o.get("commission", 0) or 0
        stamp = o.get("stamp_duty", 0) or 0
        if o["side"] == "buy": cash -= qty * price + comm
        elif o["side"] == "sell": cash += qty * price - comm - stamp
    acc = db["broker_accounts"].find_one({"account_id": "default"})
    drift = acc.get("available_cash", 0) - cash if acc else 0
    check("cash闭环", abs(drift) < 5.0, f"漂移={drift:.2f}元")
    
    # ═══ 自动补全 ═══
    all_passed = all(c["passed"] for c in REPORT["checks"])
    need_fill = any(not c["passed"] and "因子" in c["name"] for c in REPORT["checks"])
    need_sentiment = any(not c["passed"] and "sentiment" in c["name"] for c in REPORT["checks"])
    
    if need_fill_dates or need_fill:
        print(f"\n═══ 自动补全因子 ═══")
        print(f"  需补全日期: {need_fill_dates}")
        try:
            result = subprocess.run(
                [sys.executable, str(BASE / "scripts" / "lightweight_factor_fill.py")],
                capture_output=True, text=True, timeout=300, cwd=str(BASE)
            )
            output = result.stdout[-500:] if result.stdout else ""
            REPORT["fills"].append({"script": "lightweight_factor_fill.py", "output": output})
            print(f"  补全完成: {output[-200:]}")
        except subprocess.TimeoutExpired:
            REPORT["fills"].append({"script": "lightweight_factor_fill.py", "error": "timeout"})
            print(f"  🔴 补全超时(300s)")
        except Exception as e:
            REPORT["fills"].append({"script": "lightweight_factor_fill.py", "error": str(e)})
            print(f"  🔴 补全失败: {e}")
    
    if need_sentiment:
        print(f"\n═══ 自动重算sentiment ═══")
        try:
            result = subprocess.run(
                [sys.executable, "-c", """
import sys; sys.path.insert(0, '.')
import pymongo
from nodes.market_monitor.emotion_cycle import EmotionCycleManager
db = pymongo.MongoClient('localhost', 27017)['stock_agent']
for td in sorted(set(doc['trade_date'] for doc in db['sentiment_scores'].find({}, {'trade_date': 1}))):
    if td < 20260701: continue
    lu = db['limit_list'].count_documents({'trade_date': td, 'limit': 'U'})
    ld = db['limit_list'].count_documents({'trade_date': td, 'limit': 'D'})
    max_lb = 0
    for doc in db['limit_list'].find({'trade_date': td, 'limit': 'U'}, {'limit_times': 1}):
        lt = doc.get('limit_times', 0) or 0
        if lt > max_lb: max_lb = lt
    up = db['stock_daily_ak_full'].count_documents({'trade_date': td, 'pct_chg': {'$gt': 0}})
    down = db['stock_daily_ak_full'].count_documents({'trade_date': td, 'pct_chg': {'$lt': 0}})
    ud_ratio = up / down if down > 0 else 0
    sent = db['sentiment_scores'].find_one({'trade_date': td})
    zt_premium = sent.get('zt_premium', 0) or 0 if sent else 0
    score, period = EmotionCycleManager._calc_sentiment_score(lu, ld, max_lb, ud_ratio, zt_premium)
    db['sentiment_scores'].update_one({'trade_date': td}, {'$set': {
        'score': round(score, 2), 'period': period,
        'limit_up': lu, 'limit_down': ld, 'max_continue': max_lb,
        'up_count': up, 'down_count': down, 'up_down_ratio': round(ud_ratio, 3),
        'zt_premium': zt_premium, 'data_source': 'limit_list+daily_xref',
        'formula': '5dim', 'missing_data': False,
    }})
    print(f'  {td}: score={score:.1f} period={period} lu={lu} ld={ld}')
"""],
                capture_output=True, text=True, timeout=60, cwd=str(BASE)
            )
            print(f"  {result.stdout.strip()}")
            REPORT["fills"].append({"script": "sentiment_recalc", "output": result.stdout[-300:]})
        except Exception as e:
            print(f"  🔴 sentiment重算失败: {e}")
            REPORT["fills"].append({"script": "sentiment_recalc", "error": str(e)})
    
    # ═══ 补全后重新验证 ═══
    if REPORT["fills"]:
        print(f"\n═══ 补全后重新验证 ═══")
        for td in recent_dates[:3]:
            total = db["stock_daily_ak_full"].count_documents({"trade_date": td})
            missing = []
            for field, threshold in factor_fields.items():
                cnt = db["stock_daily_ak_full"].count_documents({"trade_date": td, field: {"$exists": True, "$ne": 0}})
                if total > 0 and cnt / total < threshold:
                    missing.append(field)
            if missing:
                check(f"{td} 补全后", False, f"仍缺失: {', '.join(missing)}")
                REPORT["pending"].append(td)
            else:
                check(f"{td} 补全后", True, f"{total}条完整")
    
    # ═══ 汇总 ═══
    passed = sum(1 for c in REPORT["checks"] if c["passed"])
    failed = sum(1 for c in REPORT["checks"] if not c["passed"])
    REPORT["summary"] = f"检查{len(REPORT['checks'])}项: 通过{passed} 失败{failed} 补全{len(REPORT['fills'])}次 待补{len(REPORT['pending'])}天"
    
    print(f"\n{'='*60}")
    print(f"📊 {REPORT['summary']}")
    if REPORT["pending"]:
        print(f"⚠️  待补日期(需早晨审查): {REPORT['pending']}")
    print(f"{'='*60}")
    
    # 输出JSON供cron使用
    report_path = BASE / "scripts" / "data_integrity_report.json"
    with open(report_path, "w") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)
    print(f"报告已保存: {report_path}")
    
    # 退出码: 0=全通过, 1=有失败(需重试), 2=有pending(需人工)
    if REPORT["pending"]:
        sys.exit(2)
    elif failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(run())
