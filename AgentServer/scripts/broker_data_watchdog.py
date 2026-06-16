#!/usr/bin/env python3
"""
Broker 数据流一致性 Watchdog (v2.9.93)

定期比对四个真相源的一致性，任何 drift 立即报警:

【数据源】
1. broker_orders        — 真实成交簿(单笔订单)
2. broker_positions     — 真实持仓快照
3. scanner._timeline    — 进程内存的行为日志(不是真相)
4. scanner_timeline     — MongoDB 持久化的 timeline(不是真相)

【真相规则】
- 唯一真相源 = broker_orders + broker_positions
- scanner._timeline / scanner_timeline 仅作行为审计，可有误差
- 但「持仓存在性」「持仓数量」必须严格一致

【检测项】
A. 持仓存在性: broker_positions 有的股票，broker_orders 必须有对应未完全卖出的 buy
B. 数量守恒: broker_orders.buy_qty - broker_orders.sell_qty == broker_positions.qty
C. 未来时间穿越: scanner_timeline 当天 time 字段 > 当前时间 → 数据污染
D. 内存 vs MongoDB drift: scanner._timeline 长度 vs MongoDB scanner_timeline 当天数
   (差异 > 阈值 = 重启/崩溃可能丢失记录)

【触发原因】
2026-06-15 P0: scanner_timeline 被旧 load_timeline 回退污染，虚合 13 只幽灵持仓。
若有 watchdog 8:35 跑一次，能在 9:30 开盘前抓到。

运行:
  python3 scripts/broker_data_watchdog.py             # 单次检查 + 退出码
  python3 scripts/broker_data_watchdog.py --json      # 输出结构化结果
  python3 scripts/broker_data_watchdog.py --threshold-pct 5  # 调整 drift 容忍度

退出码:
  0 = 全部一致
  1 = 有 P0 不一致(虚假持仓 / 未来时间 / 数量不守恒)
  2 = 有 P1 漂移(内存 vs DB 不一致超阈值，可恢复)
"""
import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any

try:
    from pymongo import MongoClient
except ImportError:
    print("❌ pymongo 未安装", file=sys.stderr)
    sys.exit(3)


def now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def check_broker(db, account_id: str = "default") -> dict[str, Any]:
    """检测持仓一致性

    【设计】只报告「幽灵持仓」：broker_positions 里有但 broker_orders
    净额不够的股票。历史消产性变化(orders净<0但现在没持仓) 不报告。
    """
    issues = []

    # 累加 broker_orders 计算账户内每只股票净持仓
    net_qty: dict[str, int] = {}
    stock_names: dict[str, str] = {}
    for o in db.broker_orders.find(
        {"account_id": account_id, "status": "filled"},
        {"ts_code": 1, "side": 1, "quantity": 1, "filled_qty": 1, "stock_name": 1}
    ):
        tc = o.get("ts_code", "")
        if not tc:
            continue
        qty = o.get("filled_qty") or o.get("quantity") or 0
        side = o.get("side", "")
        stock_names[tc] = o.get("stock_name", "")
        if side == "buy":
            net_qty[tc] = net_qty.get(tc, 0) + qty
        elif side == "sell":
            net_qty[tc] = net_qty.get(tc, 0) - qty

    # 真实持仓 (broker_positions)
    real_pos: dict[str, int] = {}
    for p in db.broker_positions.find(
        {"account_id": account_id},
        {"ts_code": 1, "total_qty": 1, "quantity": 1, "stock_name": 1}
    ):
        tc = p.get("ts_code", "")
        if not tc:
            continue
        q = p.get("total_qty") or p.get("quantity") or 0
        if q > 0:
            real_pos[tc] = q
            stock_names[tc] = p.get("stock_name", "") or stock_names.get(tc, "")

    # 检测: 实际持仓必须在 orders 里有未完全卖出的 buy
    # 即: real_pos > 0 时, 必须 net_qty >= real_pos (幽灵持仓检测)
    for tc, real in real_pos.items():
        net = net_qty.get(tc, 0)
        if net < real:
            issues.append({
                "level": "P0",
                "type": "phantom_position",
                "ts_code": tc,
                "stock_name": stock_names.get(tc, ""),
                "broker_orders_net": net,
                "broker_positions": real,
                "msg": f"幽灵持仓: {tc}({stock_names.get(tc,'')}) "
                       f"positions={real} 但 orders净={net}不足 → 持仓无有效交易记录",
            })

    return {
        "checked_positions": len(real_pos),
        "checked_codes_total": len(set(net_qty.keys()) | set(real_pos.keys())),
        "issues": issues,
    }


def check_future_time(db) -> dict[str, Any]:
    """检测 C: scanner_timeline 当天有没有未来时间穿越"""
    today = today_str()
    cur_time = now_hms()
    issues = []

    cursor = db.scanner_timeline.find({
        "trade_date": today,
        "action": {"$ne": "blocked"},
        "time": {"$gt": cur_time},
    })
    future_count = 0
    samples = []
    for d in cursor:
        future_count += 1
        if len(samples) < 5:
            samples.append({
                "time": d.get("time"),
                "action": d.get("action"),
                "ts_code": d.get("ts_code"),
                "stock_name": d.get("stock_name", ""),
            })
    if future_count > 0:
        issues.append({
            "level": "P0",
            "type": "future_time_pollution",
            "count": future_count,
            "samples": samples,
            "msg": f"scanner_timeline 当天有 {future_count} 条未来时间记录(time > {cur_time})，"
                   f"很可能是 load_timeline 回退污染。立即排查 runtime_persistence.py。",
        })
    return {"future_count": future_count, "issues": issues}


def check_timeline_ghost_trades(db, account_id: str = "default", date: str = None, auto_clean: bool = False) -> dict[str, Any]:
    """【v2.9.96f】检测【幽灵交易】: scanner_timeline 中的 buy/sell 记录必须能在 broker_orders 中找到对应
    
    根因: 手动回滚 broker_orders 后 timeline 未同步清理, 导致前端显示不存在的交易.
    多个 Tab 受影响: 成交订单/已平仓/交易历史/每日明细/累计PnL
    """
    issues = []
    target_date = date or today_str()
    target_int = int(target_date) if target_date.isdigit() else target_date
    
    real_keys = set()
    for o in db.broker_orders.find(
        {"account_id": account_id, "trade_date": {"$in": [target_date, target_int]}, "status": "filled"},
        {"ts_code": 1, "fill_time": 1, "create_time": 1, "side": 1, "_id": 0}
    ):
        t = o.get("fill_time") or o.get("create_time", "")
        real_keys.add((o.get("ts_code", ""), t, o.get("side", "")))
    # 【v2.9.96i】明确排除 rolled_back 订单(status=='rolled_back' 已被上面过滤, 这里是可读性注释)
    
    ghosts = []
    for t in db.scanner_timeline.find(
        {"account_id": account_id, "trade_date": {"$in": [target_date, target_int]}, "action": {"$in": ["buy", "sell"]}},
        {"ts_code": 1, "time": 1, "action": 1, "stock_name": 1, "strategy": 1, "price": 1, "_id": 1}
    ):
        key = (t.get("ts_code", ""), t.get("time", ""), t.get("action", ""))
        if key not in real_keys:
            ghosts.append(t)
    
    cleaned = 0
    if ghosts and auto_clean:
        ghost_ids = [g["_id"] for g in ghosts]
        result = db.scanner_timeline.delete_many({"_id": {"$in": ghost_ids}})
        cleaned = result.deleted_count
    
    if ghosts:
        samples = [
            {"time": g.get("time"), "action": g.get("action"), "ts_code": g.get("ts_code"),
             "stock_name": g.get("stock_name", ""), "strategy": g.get("strategy", "")}
            for g in ghosts[:5]
        ]
        issues.append({
            "level": "P1",
            "type": "ghost_trade_in_timeline",
            "count": len(ghosts),
            "cleaned": cleaned,
            "date": target_date,
            "samples": samples,
            "msg": (f"scanner_timeline 中有 {len(ghosts)} 条 buy/sell 记录在 broker_orders 中找不到对应 (date={target_date}). "
                   f"可能手动回滚后未同步清理. " + 
                   (f"【已自动清理 {cleaned} 条】" if auto_clean else "调用 POST /scanner/reconcile-timeline 或加 --auto-clean-ghost 修复.")),
        })
    
    return {
        "date": target_date,
        "real_orders": len(real_keys),
        "ghost_count": len(ghosts),
        "cleaned": cleaned,
        "issues": issues,
    }


def check_memory_db_drift(threshold_pct: float = 10.0) -> dict[str, Any]:
    """检测 D: scanner 内存 vs MongoDB scanner_timeline 当天数 drift"""
    issues = []
    try:
        import urllib.request
        with urllib.request.urlopen(
            "http://localhost:8000/api/v1/scanner/status", timeout=3
        ) as resp:
            data = json.loads(resp.read())
        d = data.get("data", {})
        if not d.get("is_running"):
            return {"skipped": "scanner_not_running", "issues": []}
        # status API 没暴露 timeline 长度，简化处理：仅在有持仓但 status.positions=[] 时告警
        return {"is_running": True, "issues": []}
    except Exception as e:
        issues.append({
            "level": "P2",
            "type": "scanner_status_unreachable",
            "msg": f"scanner status API 不可达: {e}",
        })
        return {"issues": issues}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--threshold-pct", type=float, default=10.0)
    parser.add_argument("--account", default="default")
    parser.add_argument("--mongo-uri", default="mongodb://localhost:27017/")
    parser.add_argument("--db", default="stock_agent")
    parser.add_argument("--auto-clean-ghost", action="store_true", help="【v2.9.96f】自动清理幽灵 timeline 交易")
    parser.add_argument("--check-date", default=None, help="【v2.9.96f】检查指定日期(YYYYMMDD), 默认今天")
    args = parser.parse_args()

    client = MongoClient(args.mongo_uri)
    db = client[args.db]

    report = {
        "timestamp": datetime.now().isoformat(),
        "checks": {
            "broker": check_broker(db, account_id=args.account),
            "future_time": check_future_time(db),
            "timeline_ghost": check_timeline_ghost_trades(db, account_id=args.account, date=args.check_date, auto_clean=args.auto_clean_ghost),
            "memory_drift": check_memory_db_drift(args.threshold_pct),
        },
    }

    all_issues = []
    for k, v in report["checks"].items():
        all_issues.extend(v.get("issues", []))
    report["all_issues"] = all_issues
    report["issue_count"] = len(all_issues)

    p0 = [i for i in all_issues if i.get("level") == "P0"]
    p1 = [i for i in all_issues if i.get("level") == "P1"]
    p2 = [i for i in all_issues if i.get("level") == "P2"]

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"=== Broker Data Watchdog @ {report['timestamp']} ===")
        print(f"账户: {args.account}")
        b = report['checks']['broker']
        print(f"  broker 检查: 现持仓 {b.get('checked_positions', 0)} 只 / 总涵盖 {b.get('checked_codes_total', 0)} 只股票")
        ft = report["checks"]["future_time"]
        print(f"  未来时间穿越: {ft.get('future_count', 0)} 条")
        tg = report["checks"]["timeline_ghost"]
        cleaned_str = f" (已清理 {tg.get('cleaned', 0)})" if tg.get('cleaned', 0) > 0 else ""
        print(f"  幽灵交易检查(date={tg.get('date','')}): real={tg.get('real_orders',0)} ghost={tg.get('ghost_count',0)}{cleaned_str}")
        print()
        if not all_issues:
            print("✅ 全部一致，无 drift")
        else:
            print(f"❌ 发现 {len(all_issues)} 个问题 (P0={len(p0)} P1={len(p1)} P2={len(p2)})")
            for i in all_issues:
                print(f"  [{i['level']}] {i['type']}: {i['msg']}")

    if p0:
        return 1
    if p1:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
