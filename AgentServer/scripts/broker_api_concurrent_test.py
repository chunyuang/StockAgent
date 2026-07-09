#!/usr/bin/env python3
"""【v2.9.113】API契约验证 + 并发安全测试

4. API契约验证: broker内部状态 → API响应 → 字段一致性
5. 并发安全: save_state并发 → 不产生重复order/position漂移

运行: python3 scripts/broker_api_concurrent_test.py
⚠️ 只读API测试(用生产default账户), 写操作用e2e_test隔离账户
"""

import sys
import os
import json
import time
import threading
import pymongo
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Mock 交易时间
import nodes.market_monitor.market_phase as _mp
_mp.MarketPhase.is_continuous_auction = classmethod(lambda cls: True)
_mp.MarketPhase.is_open_allowed = classmethod(lambda cls: True)
_mp.MarketPhase.classify = classmethod(lambda cls: 'continuous_auction')

TEST_ACCOUNT = "e2e_api_test"
INITIAL_CASH = 1000000.0
DB_NAME = "stock_agent"
API_BASE = "http://localhost:8000/api/v1/scanner"


def get_db():
    return pymongo.MongoClient('localhost', 27017)[DB_NAME]


def clean_test_data():
    db = get_db()
    for coll in ['broker_orders', 'broker_positions', 'broker_accounts']:
        db[coll].delete_many({'account_id': TEST_ACCOUNT})


def api_get(path):
    import urllib.request
    try:
        r = urllib.request.urlopen(f'{API_BASE}{path}', timeout=5)
        return json.loads(r.read())
    except Exception as e:
        return {'success': False, 'error': str(e)}


class R:
    def __init__(self):
        self.ok = 0
        self.fail = 0
        self.errs = []

    def check(self, name, cond, detail=""):
        if cond:
            self.ok += 1
            print(f"  ✅ {name}")
        else:
            self.fail += 1
            self.errs.append((name, detail))
            print(f"  ❌ {name}: {detail}")

    def eq(self, name, a, b, tol=0.01):
        self.check(name, abs(a - b) <= tol, f"expected={b}, got={a}")

    def gt(self, name, a, b):
        self.check(name, a > b, f"{a} not > {b}")

    def summary(self):
        total = self.ok + self.fail
        print(f"\n{'='*60}")
        print(f"📊 结果: {self.ok}/{total} 通过, {self.fail} 失败")
        if self.errs:
            for n, d in self.errs:
                print(f"  ❌ {n}: {d}")
        return self.fail == 0


# ============================================================
# 测试4: API契约验证
# ============================================================

def test_4a_account_api(r):
    """4a. /account API 返回字段与MongoDB一致"""
    print("\n=== 测试4a: /account API 契约 ===")
    resp = api_get('/account')
    r.check("API成功", resp.get('success', False), str(resp.get('error', ''))[:100])

    if not resp.get('success'):
        return

    data = resp['data']
    # 验证关键字段存在
    for field in ['total_assets', 'available_cash', 'market_value', 'total_profit', 'position_count']:
        r.check(f"字段 {field} 存在", field in data, f"缺失: {list(data.keys())}")

    # 与MongoDB交叉验证
    db = get_db()
    acc = db.broker_accounts.find_one({'account_id': 'default'})
    if acc:
        r.eq("API total_assets = MongoDB", data.get('total_assets', 0), acc.get('total_assets', 0), tol=1.0)
        r.eq("API available_cash = MongoDB", data.get('available_cash', 0), acc.get('available_cash', 0), tol=1.0)
        r.eq("API market_value = MongoDB", data.get('market_value', 0), acc.get('market_value', 0), tol=1.0)

    # 账户等式
    cash = data.get('available_cash', 0)
    mv = data.get('market_value', 0)
    assets = data.get('total_assets', 0)
    r.eq("API 等式: cash+mv=assets", cash + mv, assets, tol=1.0)


def test_4b_positions_api(r):
    """4b. /positions API 返回的market_value = current_price * qty"""
    print("\n=== 测试4b: /positions API 契约 ===")
    resp = api_get('/positions')
    r.check("API成功", resp.get('success', False))

    if not resp.get('success'):
        return

    positions = resp.get('data', [])
    r.check("有持仓数据", len(positions) > 0, f"position_count={len(positions)}")

    mv_total_api = 0
    for pos in positions:
        code = pos.get('ts_code', '?')
        qty = pos.get('total_qty', 0) or pos.get('shares', 0)
        price = pos.get('current_price', 0)
        api_mv = pos.get('market_value', 0)

        # market_value 应该 ≈ current_price * qty
        if qty > 0 and price > 0:
            expected_mv = price * qty
            r.eq(f"{code} mv = price*qty", api_mv, expected_mv, tol=expected_mv * 0.01)
            mv_total_api += api_mv
        elif api_mv > 0:
            # API直接返回market_value, qty可能用shares字段
            mv_total_api += api_mv

    # 与 /account 的 market_value 交叉验证
    acc_resp = api_get('/account')
    if acc_resp.get('success'):
        acc_mv = acc_resp['data'].get('market_value', 0)
        r.eq("positions总mv ≈ account.mv", mv_total_api, acc_mv, tol=max(acc_mv * 0.02, 100))


def test_4c_timeline_api(r):
    """4c. /timeline API action 字段细分正确"""
    print("\n=== 测试4c: /timeline API 契约 ===")
    resp = api_get('/timeline/history')
    r.check("API成功", resp.get('success', False))

    if not resp.get('success'):
        return

    timeline = resp.get('data', [])
    r.check("有timeline数据", len(timeline) > 0)

    # 验证 action 字段不是全 blocked
    actions = {}
    for t in timeline:
        action = t.get('action', 'unknown')
        actions[action] = actions.get(action, 0) + 1

    print(f"  action分布: {actions}")
    r.check("action不全=blocked", len(actions) > 1 or 'blocked' not in actions,
            f"全部{len(timeline)}条都是blocked")

    # 验证必要字段存在
    if timeline:
        sample = timeline[0]
        for field in ['ts_code', 'action', 'trade_date']:
            r.check(f"timeline 字段 {field}", field in sample, f"缺失, 有: {list(sample.keys())[:10]}")


def test_4d_orders_profit(r):
    """4d. sell orders 的 profit_amount/profit_pct 不全为0"""
    print("\n=== 测试4d: sell orders profit 契约 ===")
    db = get_db()
    sells = list(db.broker_orders.find({'side': 'sell', 'status': 'filled', 'account_id': 'default'}))

    r.check("有sell orders", len(sells) > 0)
    if not sells:
        return

    profit_ok = sum(1 for s in sells if (s.get('profit_amount') or 0) != 0)
    r.check("profit_amount不全=0", profit_ok > 0,
            f"全部{len(sells)}笔sell的profit_amount=0")

    filled_ok = sum(1 for s in sells if (s.get('filled_amount') or 0) > 0)
    r.check("filled_amount全>0", filled_ok == len(sells),
            f"{len(sells)-filled_ok}笔filled_amount=0")


# ============================================================
# 测试5: 并发安全
# ============================================================

def test_5a_concurrent_save(r):
    """5a. 并发 save_state 不产生重复 order"""
    print("\n=== 测试5a: 并发 save_state ===")
    clean_test_data()

    from nodes.market_monitor.broker import SimulatedBroker
    b = SimulatedBroker(account_id=TEST_ACCOUNT, initial_cash=INITIAL_CASH)
    b._realtime_prices = {'000001.SZ': 15.50}
    b._limit_prices = {'000001.SZ': {'upper': 17.05, 'lower': 13.95}}

    ok, _, o = b.place_order('000001.SZ', '平安银行', 'buy', 1000, 15.50)
    r.check("下单成功", ok)

    # 并发调用 _sync_save_order_and_position 5次
    b._ensure_sync_mongo()
    pos = b.positions.get('000001.SZ')

    errors = []
    def save_once(i):
        try:
            b._sync_save_order_and_position(o, pos)
        except Exception as e:
            errors.append(f"thread-{i}: {e}")

    threads = [threading.Thread(target=save_once, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    r.check("无并发异常", len(errors) == 0, f"errors: {errors}")

    # 验证 MongoDB 不产生重复 order
    db = get_db()
    count = db.broker_orders.count_documents({
        'account_id': TEST_ACCOUNT, 'ts_code': '000001.SZ', 'side': 'buy'
    })
    r.check("无重复order", count <= 1, f"发现{count}条重复order (应≤1)")

    # 验证 position 不漂移
    pos_docs = list(db.broker_positions.find({'account_id': TEST_ACCOUNT, 'ts_code': '000001.SZ'}))
    r.check("无重复position", len(pos_docs) <= 1, f"发现{len(pos_docs)}条position (应≤1)")
    if pos_docs:
        r.eq("position qty不漂移", pos_docs[0].get('total_qty'), 1000)

    clean_test_data()


def test_5b_order_id_unique(r):
    """5b. order_id 唯一索引防重复"""
    print("\n=== 测试5b: order_id 唯一性 ===")
    db = get_db()

    # 检查 default 账户的 order_id 是否有重复
    pipeline = [
        {'$group': {'_id': '$order_id', 'count': {'$sum': 1}}},
        {'$match': {'count': {'$gt': 1}}}
    ]
    dupes = list(db.broker_orders.aggregate(pipeline))
    r.check("default账户无重复order_id", len(dupes) == 0,
            f"重复order_id: {[(d['_id'], d['count']) for d in dupes[:5]]}")

    # 检查 e2e_test 账户 (应已清理)
    dupes2 = list(db.broker_orders.aggregate([
        {'$match': {'account_id': TEST_ACCOUNT}},
        {'$group': {'_id': '$order_id', 'count': {'$sum': 1}}},
        {'$match': {'count': {'$gt': 1}}}
    ]))
    r.check("test账户无重复order_id", len(dupes2) == 0)


def test_5c_position_integrity(r):
    """5c. 同一ts_code不应有多条active position"""
    print("\n=== 测试5c: position 唯一性 ===")
    db = get_db()

    # default账户: 同ts_code不应有多条qty>0的position
    pipeline = [
        {'$match': {'account_id': 'default', 'total_qty': {'$gt': 0}}},
        {'$group': {'_id': '$ts_code', 'count': {'$sum': 1}}},
        {'$match': {'count': {'$gt': 1}}}
    ]
    dupes = list(db.broker_positions.aggregate(pipeline))
    r.check("default无重复active position", len(dupes) == 0,
            f"重复: {[(d['_id'], d['count']) for d in dupes]}")

    # 7/9 发现的 test_account 幽灵
    test_dupes = list(db.broker_positions.aggregate([
        {'$match': {'account_id': 'test_account', 'total_qty': {'$gt': 0}}},
        {'$group': {'_id': '$ts_code', 'count': {'$sum': 1}}},
        {'$match': {'count': {'$gt': 1}}}
    ]))
    if test_dupes:
        r.check("test_account无重复position", False,
                f"test_account重复: {[(d['_id'], d['count']) for d in test_dupes]}")
    else:
        r.check("test_account无重复position", True)


# ============================================================
# main
# ============================================================

def main():
    print("=" * 60)
    print("🔬 API契约 + 并发安全测试")
    print("=" * 60)

    r = R()
    try:
        # 4. API契约
        test_4a_account_api(r)
        test_4b_positions_api(r)
        test_4c_timeline_api(r)
        test_4d_orders_profit(r)

        # 5. 并发安全
        test_5a_concurrent_save(r)
        test_5b_order_id_unique(r)
        test_5c_position_integrity(r)
    finally:
        clean_test_data()

    success = r.summary()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
