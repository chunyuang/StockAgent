#!/usr/bin/env python3
"""
量脉数据狙击手 — 4291间歇窗口抢槽位拉数据

核心策略:
1. 等30秒→尝试请求→4291则再等→成功则立即burst下一批
2. 每次成功后重置等待计时(抢到槽位要趁热打铁)
3. 持续运行直到完成或用户Ctrl+C
4. 失败不退出，只记日志继续等

用法:
  python3 liangmai_sniper.py [--task multi|realtime|pools|index] [--max-wait 30]
"""
import requests
import time
import json
import sys
import os
import logging
from datetime import datetime
from pymongo import MongoClient, UpdateOne

TOKEN = os.environ.get("LIANGMAI_TOKEN", "ebacbad6d64444cd037ac5504b63f25d")
GATEWAY = "http://124.220.44.71/api/gateway"
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("sniper")

# 全局统计
stats = {"success": 0, "4291": 0, "error": 0, "written": 0}
last_success_time = 0  # 上次成功时间，用于判断槽位存活


def call_api(api_name, params=None, timeout=30):
    """直接requests调用，返回(code, data)"""
    try:
        p = {"token": TOKEN, "api": api_name}
        if params:
            p.update(params)
        r = requests.get(GATEWAY, params=p, timeout=timeout)
        d = r.json()
        return d.get("code", -1), d.get("data", []), d.get("msg", "")
    except Exception as e:
        return -1, None, str(e)


def sniper_call(api_name, params=None, max_wait=30, label=""):
    """狙击手调用：等槽位→请求→4291重试→成功返回data"""
    global last_success_time
    wait = 5  # 初始等5秒
    consecutive_fail = 0

    while True:
        # 检查速率：距上次请求至少0.5秒
        time_since_last = time.time() - last_success_time
        if consecutive_fail > 0 and time_since_last < wait:
            sleep_time = wait - time_since_last
            log.info(f"  等待 {sleep_time:.0f}s (4291退避, consecutive={consecutive_fail})...")
            time.sleep(sleep_time)

        code, data, msg = call_api(api_name, params)

        if code == 0:
            stats["success"] += 1
            last_success_time = time.time()
            consecutive_fail = 0
            wait = 2  # 成功后只等2秒(趁热打铁)
            return data
        elif code == 4291:
            stats["4291"] += 1
            consecutive_fail += 1
            # 退避策略: 5s→15s→25s→30s→30s...
            wait = min(5 + consecutive_fail * 10, max_wait)
            log.debug(f"  4291 (consecutive={consecutive_fail}), next wait={wait}s - {msg[:40]}")
            continue
        elif code == -1:
            stats["error"] += 1
            log.warning(f"  请求异常: {msg[:60]}")
            time.sleep(5)
            continue
        else:
            stats["error"] += 1
            log.warning(f"  API错误 code={code}: {msg[:60]}")
            return None


def fetch_multi_to_daily_basic():
    """用stock_realtime_multi批量20只拉PE/PB/circ_mv→daily_basic"""
    db = MongoClient(MONGO_URI)[DB_NAME]
    today = int(datetime.now().strftime("%Y%m%d"))

    # 检查今天已有多少
    existing = set(
        d["ts_code"]
        for d in db.daily_basic.find({"trade_date": today, "pe": {"$ne": None}}, {"ts_code": 1})
    )
    codes = db.stock_daily_ak_full.distinct("ts_code", {"trade_date": {"$gte": 20260501}})
    need = [c for c in codes if c not in existing]

    log.info(f"=== MULTI→daily_basic: 需要{len(need)}只, 已有{len(existing)}只 ===")

    if not need:
        log.info("全部已更新")
        return

    updates = []
    total = len(need)

    for i in range(0, len(need), 20):
        batch = need[i:i+20]
        lm_codes = ",".join(
            c.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            for c in batch
        )

        data = sniper_call("stock_realtime_multi", {"stock_codes": lm_codes}, label=f"{i}/{total}")
        if data is None:
            continue

        if not isinstance(data, list):
            continue

        for r in data:
            dm = r.get("dm", "")
            code = str(dm).zfill(6)
            if code.startswith(("6", "9")):
                ts_code = f"{code}.SH"
            elif code.startswith(("8", "4")):
                ts_code = f"{code}.BJ"
            else:
                ts_code = f"{code}.SZ"

            lt = r.get("lt", 0)
            sz = r.get("sz", 0)

            doc = {
                "ts_code": ts_code,
                "trade_date": today,
                "pe": r.get("pe"),
                "pb": r.get("sjl"),
                "circ_mv": round(lt / 1e8, 4) if lt else None,
                "total_mv": round(sz / 1e8, 4) if sz else None,
                "turnover_rate": r.get("hs"),
                "volume_ratio": r.get("lb"),
                "close": r.get("p"),
                "pre_close": r.get("yc"),
            }
            updates.append(
                UpdateOne(
                    {"ts_code": ts_code, "trade_date": today},
                    {"$set": doc},
                    upsert=True,
                )
            )

        if len(updates) >= 100:
            try:
                db.daily_basic.bulk_write(updates, ordered=False)
                stats["written"] += len(updates)
            except Exception as e:
                log.error(f"bulk_write: {e}")
            log.info(f"  写入 {min(i+20, total)}/{total} ({len(updates)}条) stats={stats}")
            updates = []

    if updates:
        try:
            db.daily_basic.bulk_write(updates, ordered=False)
            stats["written"] += len(updates)
        except Exception as e:
            log.error(f"bulk_write: {e}")

    log.info(f"  完成! stats={stats}")


def fetch_pools(start_date, end_date):
    """拉涨停池/跌停池/开板池"""
    db = MongoClient(MONGO_URI)[DB_NAME]

    tasks = [
        ("pool_limit_up", "limit_pool_up", "涨停池"),
        ("pool_limit_down", "limit_pool_down", "跌停池"),
        ("pool_broken_board", "limit_pool_broken", "开板池"),
    ]

    trade_dates = db.stock_daily_ak_full.distinct(
        "trade_date", {"trade_date": {"$gte": start_date, "$lte": end_date}}
    )
    trade_dates.sort()
    log.info(f"=== 涨停池任务: {start_date}~{end_date}, {len(trade_dates)}天 ===")

    for api, coll, name in tasks:
        existing_dates = set(db[coll].distinct("trade_date"))
        need_dates = [d for d in trade_dates if d not in existing_dates]

        if not need_dates:
            log.info(f"  {name}: 全部已有")
            continue

        log.info(f"  {name}: 需要{len(need_dates)}天")
        for td in need_dates:
            date_str = f"{str(td)[:4]}-{str(td)[4:6]}-{str(td)[6:8]}"
            data = sniper_call(api, {"date": date_str}, label=f"{name} {date_str}")

            if data and len(data) > 0:
                for r in data:
                    r["trade_date"] = td
                try:
                    db[coll].insert_many(data, ordered=False)
                    log.info(f"  {date_str} {name}: {len(data)}只 ✅")
                except Exception as e:
                    if "duplicate" not in str(e).lower():
                        log.error(f"  insert: {e}")
            elif data is not None:
                log.info(f"  {date_str} {name}: 空")

            time.sleep(0.5)


def fetch_index_daily():
    """拉指数日K"""
    db = MongoClient(MONGO_URI)[DB_NAME]
    index_codes = ["000001.SH", "399001.SZ", "399006.SZ", "000016.SH", "000300.SH", "000905.SH"]
    log.info(f"=== 指数日K: {index_codes} ===")

    for code in index_codes:
        lm_code = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        data = sniper_call("index_kline", {"ts_code": lm_code, "klt": "101", "ktype": "1"})

        if not data or not isinstance(data, list):
            continue

        updates = []
        for r in data:
            td = r.get("d", "")
            if not td:
                continue
            td_int = int(td.replace("-", ""))
            doc = {
                "ts_code": code,
                "trade_date": td_int,
                "open": r.get("o"),
                "high": r.get("h"),
                "low": r.get("l"),
                "close": r.get("p"),
                "vol": r.get("v"),
                "amount": r.get("a"),
            }
            updates.append(UpdateOne({"ts_code": code, "trade_date": td_int}, {"$set": doc}, upsert=True))

        if updates:
            try:
                db.index_daily.bulk_write(updates, ordered=False)
                log.info(f"  {code}: {len(updates)}条 ✅")
            except Exception as e:
                log.error(f"  {code}: {e}")

        time.sleep(0.5)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["multi", "pools", "index", "all"], default="all")
    parser.add_argument("--start-date", type=int, default=20260501)
    parser.add_argument("--end-date", type=int, default=20260507)
    parser.add_argument("--max-wait", type=int, default=30, help="4291最大退避秒数")
    args = parser.parse_args()

    try:
        if args.task in ("pools", "all"):
            fetch_pools(args.start_date, args.end_date)
        if args.task in ("multi", "all"):
            fetch_multi_to_daily_basic()
        if args.task in ("index", "all"):
            fetch_index_daily()
    except KeyboardInterrupt:
        log.info(f"用户中断 stats={stats}")
