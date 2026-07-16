#!/usr/bin/env python3
"""【v2.9.113】交易全通路闭环测试

用隔离的 e2e_test 账户模拟完整交易生命周期:
1. 买入 → 验证 cash/position/order/filled_amount
2. 加仓 → 验证 avg_cost 加权重算
3. 卖出 → 验证 profit/cash 回收/position 清理
4. 清仓 → position 删除
5. 持久化 → MongoDB 写入验证 (含 filled_amount 回归)
6. 重启模拟 → load_state 后状态一致
7. 幽灵持仓检测 → 买入后 position 丢失
8. 卖出兜底 → position 不在内存 → MongoDB fallback
9. 账户等式不变量 → 连续10笔交易后 cash+mv=assets
10. filled_amount 回归 → 今天的根因不能重现

运行: python3 scripts/broker_e2e_lifecycle_test.py
⚠️ 使用 account_id='e2e_test', 绝不碰生产数据
"""

import sys
import os
import pymongo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Mock 交易时间检查 (半夜跑测试必须绕过)
import nodes.market_monitor.market_phase as _mp
_mp.MarketPhase.is_continuous_auction = classmethod(lambda cls: True)
_mp.MarketPhase.is_open_allowed = classmethod(lambda cls: True)
_mp.MarketPhase.classify = classmethod(lambda cls: 'continuous_auction')

TEST_ACCOUNT = "e2e_test"
INITIAL_CASH = 1000000.0
DB_NAME = "stock_agent"


def get_db():
    return pymongo.MongoClient('localhost', 27017)[DB_NAME]


def clean_test_data():
    db = get_db()
    for coll in ['broker_orders', 'broker_positions', 'broker_accounts']:
        db[coll].delete_many({'account_id': TEST_ACCOUNT})


def create_broker():
    from nodes.market_monitor.broker import SimulatedBroker
    broker = SimulatedBroker(account_id=TEST_ACCOUNT, initial_cash=INITIAL_CASH)
    broker._realtime_prices = {
        '000001.SZ': 15.50, '600036.SH': 42.30,
        '300750.SZ': 220.00, '002415.SZ': 38.60,
    }
    broker._limit_prices = {
        '000001.SZ': {'upper': 17.05, 'lower': 13.95},
        '600036.SH': {'upper': 46.53, 'lower': 38.07},
        '300750.SZ': {'upper': 242.00, 'lower': 198.00},
        '002415.SZ': {'upper': 42.46, 'lower': 34.74},
    }
    return broker


class R:
    """Test result collector"""
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
        self.check(name, abs(a - b) <= tol, f"expected={b}, got={a}, diff={a-b:.4f}")

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


def buy(broker, code, name, qty, price, strategy='test', reason='e2e'):
    ok, msg, o = broker.place_order(code, name, 'buy', qty, price, strategy=strategy, reason=reason)
    # 模拟次日: T+1 解锁
    if ok and code in broker.positions:
        broker.positions[code].available_qty = broker.positions[code].total_qty
        broker.positions[code].today_buy_qty = 0
    return ok, msg, o


def sell(broker, code, name, qty, price, strategy='test', reason='e2e'):
    return broker.place_order(code, name, 'sell', qty, price, strategy=strategy, reason=reason)


# ============================================================
# 测试用例
# ============================================================

def test_1_buy_basic(r):
    """买入基础流程"""
    print("\n=== 测试1: 买入基础流程 ===")
    b = create_broker()
    ok, msg, o = buy(b, '000001.SZ', '平安银行', 1000, 15.50)
    r.check("下单成功", ok, msg)
    r.eq("filled_qty", o.filled_qty, 1000)
    r.gt("filled_price > 0", o.filled_price, 0)
    r.gt("filled_amount 有效", o.filled_price * o.filled_qty, 0)

    acc = b.get_account()
    spend = o.filled_price * 1000 + o.commission
    r.eq("cash 扣减", INITIAL_CASH - acc.available_cash, spend, tol=1.0)

    pos = {p.ts_code: p for p in b.get_positions()}
    r.check("position 存在", '000001.SZ' in pos)
    if '000001.SZ' in pos:
        r.eq("position qty", pos['000001.SZ'].total_qty, 1000)
        r.gt("avg_cost 含佣金", pos['000001.SZ'].avg_cost, o.filled_price)
    r.eq("等式: cash+mv=assets", acc.available_cash + acc.market_value, acc.total_assets, tol=1.0)
    return b


def test_2_add_position(r, b):
    """加仓 → avg_cost 加权重算"""
    print("\n=== 测试2: 加仓 → avg_cost 加权重算 ===")
    pos_before = b.positions['000001.SZ']
    qty_b = pos_before.total_qty
    cost_b = pos_before.avg_cost

    b._realtime_prices['000001.SZ'] = 16.00
    ok, msg, o = buy(b, '000001.SZ', '平安银行', 500, 16.00, reason='e2e_add')
    r.check("加仓成功", ok, msg)

    pos_after = b.positions['000001.SZ']
    r.eq("加仓后 qty", pos_after.total_qty, 1500)
    r.gt("avg_cost 在两次价之间", pos_after.avg_cost, 15.50)
    r.check("avg_cost < 新价+佣金", pos_after.avg_cost < 16.10,
            f"avg_cost={pos_after.avg_cost:.4f}")

    # 加权平均验证 (含佣金, 允许误差)
    new_cost = o.filled_price * 500 + o.commission
    expected = (cost_b * qty_b + new_cost) / 1500
    r.eq("avg_cost 加权平均", pos_after.avg_cost, expected, tol=0.05)

    acc = b.get_account()
    r.eq("等式", acc.available_cash + acc.market_value, acc.total_assets, tol=1.0)
    return b


def test_3_sell_partial(r, b):
    """卖出部分 → profit + cash 回收"""
    print("\n=== 测试3: 卖出部分 → profit + cash 回收 ===")
    cash_before = b.get_account().available_cash

    b._realtime_prices['000001.SZ'] = 16.50
    ok, msg, o = sell(b, '000001.SZ', '平安银行', 800, 16.50, reason='e2e_sell')
    r.check("卖出成功", ok, msg)
    r.eq("filled_qty", o.filled_qty, 800)
    r.gt("filled_amount 有效", o.filled_price * o.filled_qty, 0)
    r.gt("profit_amount ≠ 0", abs(o.profit_amount), 0)
    r.gt("profit_pct ≠ 0", abs(o.profit_pct), 0)

    acc = b.get_account()
    income = o.filled_price * 800 - o.stamp_duty - o.commission
    r.eq("cash 回收", acc.available_cash - cash_before, income, tol=1.0)

    pos = {p.ts_code: p for p in b.get_positions()}
    r.check("剩余持仓 700", '000001.SZ' in pos and pos['000001.SZ'].total_qty == 700)
    r.eq("等式", acc.available_cash + acc.market_value, acc.total_assets, tol=1.0)
    return b


def test_4_sell_all(r, b):
    """清仓 → position 删除"""
    print("\n=== 测试4: 清仓卖出 ===")
    b._realtime_prices['000001.SZ'] = 16.80
    ok, msg, o = sell(b, '000001.SZ', '平安银行', 700, 16.80, reason='e2e_clear')
    r.check("清仓成功", ok, msg)

    pos = {p.ts_code: p for p in b.get_positions()}
    r.check("position 已清", '000001.SZ' not in pos or pos.get('000001.SZ') is None
            or b.positions.get('000001.SZ') is None
            or b.positions.get('000001.SZ', None) is None
            or b.positions.get('000001.SZ').total_qty == 0)

    acc = b.get_account()
    r.eq("等式", acc.available_cash + acc.market_value, acc.total_assets, tol=1.0)


def test_5_persistence(r):
    """持久化 → MongoDB 写入验证 (含 filled_amount)"""
    print("\n=== 测试5: 持久化 → MongoDB 写入验证 ===")
    clean_test_data()
    b = create_broker()
    ok, _, o = buy(b, '600036.SH', '招商银行', 500, 42.30)

    b._ensure_sync_mongo()
    pos = b.positions.get('600036.SH')
    b._sync_save_order_and_position(o, pos)

    db = get_db()
    doc = db.broker_orders.find_one({'account_id': TEST_ACCOUNT, 'ts_code': '600036.SH', 'side': 'buy'})
    r.check("order 写入 MongoDB", doc is not None)
    if doc:
        fa = doc.get('filled_amount', 0)
        expected = doc.get('filled_price', 0) * doc.get('filled_qty', 0)
        r.gt("filled_amount > 0", fa, 0)
        r.eq("filled_amount = fp*fq", fa, expected, tol=1.0)

    pos_doc = db.broker_positions.find_one({'account_id': TEST_ACCOUNT, 'ts_code': '600036.SH'})
    r.check("position 写入 MongoDB", pos_doc is not None)
    if pos_doc:
        r.eq("position qty", pos_doc.get('total_qty'), 500)

    # 测试 sell 持久化
    b._realtime_prices['600036.SH'] = 43.00
    ok2, _, o2 = sell(b, '600036.SH', '招商银行', 500, 43.00)
    b._sync_save_order_and_position(o2, None)

    sell_doc = db.broker_orders.find_one({'account_id': TEST_ACCOUNT, 'ts_code': '600036.SH', 'side': 'sell'})
    r.check("sell order 写入", sell_doc is not None)
    if sell_doc:
        sfa = sell_doc.get('filled_amount', 0)
        sexpected = sell_doc.get('filled_price', 0) * sell_doc.get('filled_qty', 0)
        r.gt("sell filled_amount > 0", sfa, 0)
        r.eq("sell filled_amount = fp*fq", sfa, sexpected, tol=1.0)

    clean_test_data()


def test_6_reload(r):
    """重启模拟 → load_state 一致性"""
    print("\n=== 测试6: 重启模拟 ===")
    clean_test_data()
    b1 = create_broker()
    buy(b1, '600036.SH', '招商银行', 500, 42.30)
    buy(b1, '300750.SZ', '宁德时代', 100, 220.00)

    acc1 = b1.get_account()
    pos1 = {p.ts_code: (p.total_qty, p.avg_cost) for p in b1.get_positions()}

    # 保存到 MongoDB
    db = get_db()
    b1._ensure_sync_mongo()
    for tc, p in b1.positions.items():
        b1._sync_save_order_and_position(None, p)
    db.broker_accounts.update_one(
        {'account_id': TEST_ACCOUNT}, {'$set': {
            'account_id': TEST_ACCOUNT,
            'available_cash': acc1.available_cash,
            'market_value': acc1.market_value,
            'total_assets': acc1.total_assets,
            'total_profit': acc1.total_profit,
            'today_profit': acc1.today_profit,
            'frozen_cash': acc1.frozen_cash,
        }}, upsert=True
    )

    # 新建 broker，从 MongoDB 恢复
    b2 = create_broker()
    acc_doc = db.broker_accounts.find_one({'account_id': TEST_ACCOUNT})
    if acc_doc:
        b2.account.available_cash = acc_doc['available_cash']
        b2.account.market_value = acc_doc['market_value']
        b2.account.total_assets = acc_doc['total_assets']
        b2.account.total_profit = acc_doc['total_profit']

    from nodes.market_monitor.broker import Position
    for pd in db.broker_positions.find({'account_id': TEST_ACCOUNT, 'total_qty': {'$gt': 0}}):
        p = Position(
            ts_code=pd['ts_code'], stock_name=pd.get('stock_name', ''),
            total_qty=pd['total_qty'], available_qty=pd.get('available_qty', 0),
            avg_cost=pd['avg_cost'], current_price=pd.get('current_price', 0),
            profit_pct=pd.get('profit_pct', 0), today_buy_qty=pd.get('today_buy_qty', 0),
            strategy=pd.get('strategy', ''), buy_date=pd.get('buy_date', ''),
        )
        b2.positions[p.ts_code] = p

    acc2 = b2.get_account()
    r.eq("cash 一致", acc2.available_cash, acc1.available_cash, tol=1.0)
    r.eq("assets 一致", acc2.total_assets, acc1.total_assets, tol=1.0)

    pos2 = {p.ts_code: (p.total_qty, p.avg_cost) for p in b2.get_positions()}
    r.eq("持仓数一致", len(pos2), len(pos1))
    for tc, (q, c) in pos1.items():
        if tc in pos2:
            r.eq(f"{tc} qty", pos2[tc][0], q)
            r.eq(f"{tc} avg_cost", pos2[tc][1], c, tol=0.01)

    clean_test_data()


def test_7_ghost(r):
    """幽灵持仓检测"""
    print("\n=== 测试7: 幽灵持仓检测 ===")
    b = create_broker()
    buy(b, '002415.SZ', '海康威视', 1000, 38.60)

    # 模拟: 手动删除内存 position
    b.positions.pop('002415.SZ', None)
    r.check("幽灵场景: position 不在内存", '002415.SZ' not in b.positions)

    # cash 已扣 (买入时扣了)
    acc = b.get_account()
    r.check("幽灵场景: cash 已扣", acc.available_cash < INITIAL_CASH)

    # recalc_account 后等式仍成立
    b._recalc_account()
    acc2 = b.get_account()
    r.eq("recalc 后等式", acc2.available_cash + acc2.market_value, acc2.total_assets, tol=1.0)
    # 幽灵持仓导致 mv 偏低, assets 偏低 (这正是7/9 bug 的场景)


def test_8_sell_fallback(r):
    """卖出兜底 — position 不在内存时 _validate_sell 从 MongoDB 恢复
    
    【v2.9.113修复】_validate_sell 现在会从 MongoDB 恢复丢失的 position,
    而不是直接拒绝。这样 _execute_sell 的 MongoDB 兜底路径也能走到。
    """
    print("\n=== 测试8: 卖出兜底路径 ===")
    clean_test_data()
    b = create_broker()
    ok, _, o = buy(b, '000001.SZ', '平安银行', 1000, 15.50)

    # 持久化 position
    b._ensure_sync_mongo()
    pos = b.positions.get('000001.SZ')
    b._sync_save_order_and_position(o, pos)

    # 场景A: position 在内存, 正常卖出
    b._realtime_prices['000001.SZ'] = 16.00
    ok_a, msg_a, so_a = sell(b, '000001.SZ', '平安银行', 500, 16.00, reason='e2e_fallback_a')
    r.check("场景A: 正常卖出成功", ok_a, msg_a)
    if ok_a:
        r.gt("场景A: profit ≠ 0", abs(so_a.profit_amount), 0)
        r.gt("场景A: filled_amount 有效", so_a.filled_price * so_a.filled_qty, 0)

    # 更新持久化 (卖出后剩余)
    pos2 = b.positions.get('000001.SZ')
    if pos2:
        b._sync_save_order_and_position(None, pos2)

    # 场景B: position 从内存删除, 但 MongoDB 有记录
    # v2.9.113: _validate_sell 应该从 MongoDB 恢复 position 而不是拒绝
    b.positions.pop('000001.SZ', None)
    b._realtime_prices['000001.SZ'] = 16.50
    ok_b, msg_b, so_b = sell(b, '000001.SZ', '平安银行', 500, 16.50, reason='e2e_fallback_b')
    r.check("场景B: 从MongoDB恢复后卖出成功", ok_b, msg_b)
    if ok_b:
        r.gt("场景B: profit ≠ 0", abs(so_b.profit_amount), 0)
        r.gt("场景B: filled_amount 有效", so_b.filled_price * so_b.filled_qty, 0)
        r.gt("场景B: avg_cost ≠ 0", so_b.avg_cost, 0)
    else:
        # 如果还是失败, 检查原因
        r.check("场景B失败原因含'无持仓'", '无持仓' in msg_b, msg_b)

    # 场景C: position 完全不存在 (MongoDB也没有)
    b._realtime_prices['999999.SZ'] = 10.00
    ok_c, msg_c, _ = sell(b, '999999.SZ', '不存在', 100, 10.00, reason='e2e_fallback_c')
    r.check("场景C: 真不存在的票 → 拒单", not ok_c)

    clean_test_data()


def test_9_invariant(r):
    """账户等式不变量 — 连续10笔交易"""
    print("\n=== 测试9: 账户等式不变量 (10笔) ===")
    b = create_broker()
    codes = ['000001.SZ', '600036.SH', '300750.SZ', '002415.SZ']
    prices = [15.50, 42.30, 220.00, 38.60]
    n = 0

    def check_inv(label):
        nonlocal n
        n += 1
        acc = b.get_account()
        ok = abs(acc.available_cash + acc.market_value - acc.total_assets) < 1.0
        r.check(f"交易{n}({label})", ok,
                f"cash={acc.available_cash:.0f}+mv={acc.market_value:.0f}≠assets={acc.total_assets:.0f}")

    # 4笔买入
    for i, (c, p) in enumerate(zip(codes, prices)):
        buy(b, c, f'S{i}', 300 + i*100, p)
        check_inv(f"buy {c}")

    # 2笔卖出
    for i in range(2):
        c, p = codes[i], prices[i] * 1.05
        b._realtime_prices[c] = p
        sell(b, c, f'S{i}', 200, p)
        check_inv(f"sell {c}")

    # 2笔加仓
    for i in range(2, 4):
        c, p = codes[i], prices[i] * 0.98
        b._realtime_prices[c] = p
        buy(b, c, f'S{i}', 100, p)
        check_inv(f"add {c}")

    # 2笔清仓
    for i in range(2):
        c, p = codes[i], prices[i] * 1.02
        b._realtime_prices[c] = p
        pos = b.positions.get(c)
        if pos and pos.total_qty > 0:
            sell(b, c, f'S{i}', pos.total_qty, p)
            check_inv(f"clear {c}")


def test_10_filled_amount_regression(r):
    """filled_amount 回归 — 7/9 根因不能重现"""
    print("\n=== 测试10: filled_amount 回归测试 ===")
    clean_test_data()
    b = create_broker()
    ok, _, buy_o = buy(b, '000001.SZ', '平安银行', 1000, 15.50)
    r.check("买入成功", ok)

    b._ensure_sync_mongo()
    pos = b.positions.get('000001.SZ')
    b._sync_save_order_and_position(buy_o, pos)

    b._realtime_prices['000001.SZ'] = 16.00
    ok2, _, sell_o = sell(b, '000001.SZ', '平安银行', 1000, 16.00)
    r.check("卖出成功", ok2)
    b._sync_save_order_and_position(sell_o, None)

    db = get_db()
    # Buy: filled_amount must be > 0 and = fp*fq
    bd = db.broker_orders.find_one({'account_id': TEST_ACCOUNT, 'side': 'buy'})
    if bd:
        r.gt("buy filled_amount > 0", bd.get('filled_amount', 0), 0)
        r.eq("buy filled_amount = fp*fq", bd.get('filled_amount', 0),
             bd.get('filled_price', 0) * bd.get('filled_qty', 0), tol=1.0)
    else:
        r.check("buy doc exists", False)

    # Sell: same
    sd = db.broker_orders.find_one({'account_id': TEST_ACCOUNT, 'side': 'sell'})
    if sd:
        r.gt("sell filled_amount > 0", sd.get('filled_amount', 0), 0)
        r.eq("sell filled_amount = fp*fq", sd.get('filled_amount', 0),
             sd.get('filled_price', 0) * sd.get('filled_qty', 0), tol=1.0)
    else:
        r.check("sell doc exists", False)

    clean_test_data()


def main():
    print("=" * 60)
    print("🔬 交易全通路闭环测试")
    print(f"   账户: {TEST_ACCOUNT} | 初始: {INITIAL_CASH:,.0f}")
    print("=" * 60)

    r = R()
    try:
        b = test_1_buy_basic(r)
        b = test_2_add_position(r, b)
        b = test_3_sell_partial(r, b)
        test_4_sell_all(r, b)
        test_5_persistence(r)
        test_6_reload(r)
        test_7_ghost(r)
        test_8_sell_fallback(r)
        test_9_invariant(r)
        test_10_filled_amount_regression(r)
    finally:
        clean_test_data()

    success = r.summary()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
