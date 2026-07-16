#!/usr/bin/env python3
"""
写操作持久化完整性审查 v1.0 (2026-07-16)

审查盲区: 现有审查检查数据一致性(数据存不存在), 不检查代码路径是否每个分支都调用了持久化。

近期bug:
- v2.9.124 止损订单执行但没调_sync_save_order_and_position, 订单丢失
- v2.9.109 _execute_sell兜底分支执行卖出后没return, 资金双重计算
- 多次position丢失(有买入order但无position记录)

检查项:
1. _execute_sell的所有return路径是否都调用了持久化
2. _execute_buy是否在修改状态后调用持久化
3. _execute_order_fill的所有分支是否完整
4. 兜底路径(pos不存在时)的持久化完整性
5. 拒绝路径(REJECTED)是否持久化
6. daily_settlement是否持久化状态变更
7. emergency_liquidate是否持久化
"""
import sys
import ast
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

CRITICAL = []
WARNING = []
INFO = []

def p0(msg): CRITICAL.append(msg); print(f"  ❌ P0: {msg}")
def p1(msg): WARNING.append(msg); print(f"  ⚠️  P1: {msg}")
def ok(msg): print(f"  ✅ {msg}")
def info(msg): INFO.append(msg); print(f"  ℹ️  {msg}")

BROKER = BASE / "nodes" / "market_monitor" / "broker.py"


def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def get_method_ast(class_name, method_name, source):
    """获取指定类中指定方法的AST"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                    return item, tree
    return None, tree


def find_return_statements(func_node):
    """找到函数中所有return语句"""
    returns = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Return):
            returns.append(node)
    return returns


def find_calls_in_node(func_node, method_name):
    """检查函数中是否调用了某个方法"""
    calls = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == method_name:
                calls.append(node)
    return calls


def find_assignments_to(func_node, attr_name):
    """找到对self.attr_name的赋值"""
    assignments = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == attr_name:
                    assignments.append((node, target.attr, node.lineno))
    return assignments


def find_deletes(func_node, attr_name):
    """找到del self.attr[key]操作"""
    deletes = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    if isinstance(target.value, ast.Attribute) and target.value.attr == attr_name:
                        deletes.append((node, node.lineno))
    return deletes


# ── 1. _execute_sell的return路径持久化检查 ──
def check_execute_sell_returns():
    print("\n═══ 1. _execute_sell return路径持久化检查 ═══")
    source = read_file(BROKER)
    func, tree = get_method_ast("SimulatedBroker", "_execute_sell", source)
    if not func:
        p0("找不到 _execute_sell 方法")
        return
    
    returns = find_return_statements(func)
    sync_calls = find_calls_in_node(func, "_sync_save_order_and_position")
    today_sold_adds = find_calls_in_node(func, "add")  # _today_sold.add
    
    info(f"_execute_sell: {len(returns)}个return, {len(sync_calls)}个_sync_save调用")
    
    # 分析每个return路径
    # 由于AST不直接给parent信息, 用行号范围粗略判断
    return_lines = sorted([r.lineno for r in returns])
    sync_lines = sorted([c.lineno for c in sync_calls])
    
    # 检查: 在每个修改了positions/cash的return之前, 是否有_sync_save调用
    # 修改positions: del self.positions[ts_code], pos.total_qty -=, pos.available_qty -=
    # 修改cash: self.account.available_cash += / -=
    
    cash_mods = find_assignments_to(func, "available_cash")
    today_profit_mods = find_assignments_to(func, "today_profit")
    pos_deletes = find_deletes(func, "positions")
    
    info(f"  available_cash修改: {len(cash_mods)}处")
    info(f"  today_profit修改: {len(today_profit_mods)}处")
    info(f"  positions删除: {len(pos_deletes)}处")
    info(f"  _sync_save调用: 行号 {sync_lines}")
    info(f"  return语句: 行号 {return_lines}")
    
    # 检查每个return前是否有_sync_save
    for ret_line in return_lines:
        has_sync_before = any(sl < ret_line for sl in sync_lines)
        if has_sync_before:
            # 检查这个return之前的最近_sync_save
            preceding_syncs = [sl for sl in sync_lines if sl < ret_line]
            if preceding_syncs:
                nearest = max(preceding_syncs)
                # 检查nearest和ret_line之间是否修改了cash/positions
                cash_between = [c for c, _, l in cash_mods if nearest < l < ret_line]
                pos_del_between = [(n, l) for n, l in pos_deletes if nearest < l < ret_line]
                today_profit_between = [c for c, _, l in today_profit_mods if nearest < l < ret_line]
                
                if cash_between or pos_del_between or today_profit_between:
                    p0(f"_execute_sell line {ret_line}: return前修改了状态但_sync_save在修改之前, 数据可能丢失")
                else:
                    ok(f"_execute_sell line {ret_line}: return前有_sync_save, 状态已持久化")
        else:
            # 检查这个return之前是否修改了任何状态
            cash_before = [c for c, _, l in cash_mods if l < ret_line]
            pos_del_before = [(n, l) for n, l in pos_deletes if l < ret_line]
            today_profit_before = [c for c, _, l in today_profit_mods if l < ret_line]
            
            if cash_before or pos_del_before or today_profit_before:
                # 可能是REJECTED路径(不修改cash, 只标记order.status)
                p1(f"_execute_sell line {ret_line}: return前修改了状态但无_sync_save调用")
            else:
                info(f"_execute_sell line {ret_line}: return前未修改关键状态(可能是REJECTED/拦截路径)")
    
    # 检查_today_sold.add是否在每个卖出路径都有
    info(f"_today_sold.add 调用: {len(today_sold_adds)}处")
    if len(today_sold_adds) < len(return_lines) - 1:
        # 减1因为最后一个return可能是方法结束(隐式return)
        p1(f"_today_sold.add({len(today_sold_adds)}处) 少于return路径({len(return_lines)}处), 可能有路径遗漏标记")


# ── 2. _execute_buy持久化检查 ──
def check_execute_buy_persistence():
    print("\n═══ 2. _execute_buy持久化检查 ═══")
    source = read_file(BROKER)
    func, _ = get_method_ast("SimulatedBroker", "_execute_buy", source)
    if not func:
        p0("找不到 _execute_buy 方法")
        return
    
    sync_calls = find_calls_in_node(func, "_sync_save_order_and_position")
    returns = find_return_statements(func)
    cash_mods = find_assignments_to(func, "available_cash")
    
    info(f"_execute_buy: {len(returns)}个return, {len(sync_calls)}个_sync_save调用, {len(cash_mods)}个cash修改")
    
    if not sync_calls:
        # _execute_buy可能不直接调用_sync_save, 而是由调用者(_execute_order_fill)调用
        info("_execute_buy 内部无 _sync_save 调用")
        info("  -> 检查调用者 _execute_order_fill 是否在调用_execute_buy后调用了_sync_save")
    else:
        ok(f"_execute_buy 内部有 {len(sync_calls)} 个 _sync_save 调用")
    
    # _execute_buy修改了positions和cash, 如果不持久化, 崩溃时数据丢失
    if not sync_calls and cash_mods:
        info("  _execute_buy 修改了cash/positions但不直接持久化, 由调用者负责")


# ── 3. _execute_order_fill分支完整性 ──
def check_execute_order_fill_branches():
    print("\n═══ 3. _execute_order_fill分支完整性 ═══")
    source = read_file(BROKER)
    func, _ = get_method_ast("SimulatedBroker", "_execute_order_fill", source)
    if not func:
        p0("找不到 _execute_order_fill 方法")
        return
    
    returns = find_return_statements(func)
    reject_calls = find_calls_in_node(func, "_reject_order")
    sync_calls = find_calls_in_node(func, "_sync_save_order_and_position")
    execute_buy_calls = find_calls_in_node(func, "_execute_buy")
    execute_sell_calls = find_calls_in_node(func, "_execute_sell")
    
    info(f"_execute_order_fill: {len(returns)}个return, {len(reject_calls)}个_reject_order, "
         f"{len(sync_calls)}个_sync_save, {len(execute_buy_calls)}个_execute_buy, "
         f"{len(execute_sell_calls)}个_execute_sell")
    
    # 分析每个return路径
    for ret in returns:
        ret_line = ret.lineno
        
        # 检查return前是否有_sync_save或_reject_order
        preceding_sync = [c.lineno for c in sync_calls if c.lineno < ret_line]
        preceding_reject = [c.lineno for c in reject_calls if c.lineno < ret_line]
        preceding_buy = [c.lineno for c in execute_buy_calls if c.lineno < ret_line]
        preceding_sell = [c.lineno for c in execute_sell_calls if c.lineno < ret_line]
        
        # 找到最近的分支标识
        last_sync = max(preceding_sync) if preceding_sync else 0
        last_reject = max(preceding_reject) if preceding_reject else 0
        last_buy = max(preceding_buy) if preceding_buy else 0
        last_sell = max(preceding_sell) if preceding_sell else 0
        last_action = max(last_sync, last_reject, last_buy, last_sell)
        
        if last_sync == last_action and last_sync > 0:
            ok(f"line {ret_line}: return前有_sync_save (状态已持久化)")
        elif last_reject == last_action and last_reject > 0:
            # reject路径: 检查_reject_order内部是否持久化
            info(f"line {ret_line}: return前是_reject_order (需确认_reject_order是否持久化)")
        elif last_buy == last_action and last_buy > 0:
            # buy路径: _execute_buy不持久化, 需要调用者持久化
            if preceding_sync and max(preceding_sync) > last_buy:
                ok(f"line {ret_line}: _execute_buy后有_sync_save")
            else:
                p0(f"line {ret_line}: _execute_buy后无_sync_save, 买入数据可能丢失")
        elif last_sell == last_action and last_sell > 0:
            # sell路径: _execute_sell内部有_sync_save(v2.9.124修复)
            info(f"line {ret_line}: return前是_execute_sell (v2.9.124已修复内部_sync_save)")
        else:
            info(f"line {ret_line}: return前无关键操作 (可能是early return)")


# ── 4. 兜底路径(pos不存在)持久化完整性 ──
def check_fallback_path_persistence():
    print("\n═══ 4. 兜底路径(pos不存在)持久化完整性 ═══")
    source = read_file(BROKER)
    func, _ = get_method_ast("SimulatedBroker", "_execute_sell", source)
    if not func:
        return
    
    # 搜索"position不在内存"或"兜底"相关的注释和代码
    lines = source.split('\n')
    in_execute_sell = False
    fallback_section = False
    
    for i, line in enumerate(lines, 1):
        if 'def _execute_sell' in line:
            in_execute_sell = True
            continue
        if in_execute_sell and line.strip().startswith('def ') and not line.startswith(' '):
            break
        if in_execute_sell:
            if '兜底' in line or 'position不在内存' in line or 'not pos' in line or 'if not pos' in line:
                fallback_section = True
            if fallback_section:
                if '_sync_save_order_and_position' in line:
                    ok(f"兜底路径 line {i}: 有_sync_save_order_and_position调用")
                if 'order.status = OrderStatus.FILLED' in line:
                    ok(f"兜底路径 line {i}: 标记为FILLED")
                if 'order.status = OrderStatus.REJECTED' in line:
                    info(f"兜底路径 line {i}: 标记为REJECTED (不收回资金)")
                if 'self.account.available_cash +=' in line:
                    info(f"兜底路径 line {i}: 修改available_cash")
                if 'self.account.today_profit +=' in line:
                    info(f"兜底路径 line {i}: 修改today_profit")
                if '_today_sold.add' in line:
                    ok(f"兜底路径 line {i}: 标记_today_sold")
                if 'return' in line and 'return ' not in line:
                    # 检查return前是否有_sync_save
                    # 往上找最近的_sync_save
                    has_sync = False
                    for j in range(i-1, max(0, i-30), -1):
                        if '_sync_save_order_and_position' in lines[j-1]:
                            has_sync = True
                            break
                    if has_sync:
                        ok(f"兜底路径 line {i}: return前有_sync_save")
                    else:
                        p0(f"兜底路径 line {i}: return前无_sync_save, 订单可能丢失 (v2.9.124 bug根因)")


# ── 5. REJECTED路径持久化 ──
def check_rejected_path_persistence():
    print("\n═══ 5. REJECTED路径持久化检查 ═══")
    source = read_file(BROKER)
    func, _ = get_method_ast("SimulatedBroker", "_reject_order", source)
    if not func:
        info("找不到 _reject_order 方法 (可能是内联REJECTED)")
        return
    
    # 检查_reject_order是否将REJECTED订单持久化
    sync_calls = find_calls_in_node(func, "_sync_save_order_and_position")
    
    if sync_calls:
        ok("_reject_order 调用 _sync_save_order_and_position (REJECTED订单被持久化)")
    else:
        # 检查是否append到self.orders
        append_calls = find_calls_in_node(func, "append")
        if append_calls:
            info("_reject_order 将订单append到self.orders (由save_state异步持久化)")
            info("  风险: 如果save_state未执行(节流/崩溃), REJECTED订单丢失")
            p1("_reject_order 不调用_sync_save, REJECTED订单靠异步save_state, 崩溃时可能丢失")
        else:
            p0("_reject_order 既不调用_sync_save也不append到orders, REJECTED订单完全丢失")


# ── 6. daily_settlement持久化 ──
def check_daily_settlement_persistence():
    print("\n═══ 6. daily_settlement持久化检查 ═══")
    source = read_file(BROKER)
    func, _ = get_method_ast("SimulatedBroker", "daily_settlement", source)
    if not func:
        info("找不到 daily_settlement 方法")
        return
    
    sync_calls = find_calls_in_node(func, "_sync_save_order_and_position")
    save_state_calls = find_calls_in_node(func, "save_state")
    
    # daily_settlement修改了available_qty, today_buy_qty, _today_sold, _today_rejected
    # 这些修改需要持久化
    
    if sync_calls or save_state_calls:
        ok(f"daily_settlement 有持久化调用 (sync={len(sync_calls)}, save_state={len(save_state_calls)})")
    else:
        p1("daily_settlement 修改了持仓状态但未调用持久化, 需确认调用者是否负责持久化")


# ── 7. emergency_liquidate持久化 ──
def check_emergency_liquidate_persistence():
    print("\n═══ 7. emergency_liquidate持久化检查 ═══")
    source = read_file(BROKER)
    
    # 搜索emergency_liquidate或类似方法
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SimulatedBroker":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and 'liquidate' in item.name.lower():
                    method_name = item.name
                    sync_calls = find_calls_in_node(item, "_sync_save_order_and_position")
                    sell_calls = find_calls_in_node(item, "_execute_sell")
                    place_order_calls = find_calls_in_node(item, "place_order")
                    
                    info(f"{method_name}: _sync_save={len(sync_calls)}, "
                         f"_execute_sell={len(sell_calls)}, place_order={len(place_order_calls)}")
                    
                    if sell_calls or place_order_calls:
                        ok(f"{method_name} 通过_execute_sell/place_order执行 (有持久化传递)")
                    else:
                        p1(f"{method_name} 不通过_execute_sell/place_order, 可能缺少持久化")
                    
                    if not sync_calls and not sell_calls and not place_order_calls:
                        p0(f"{method_name} 无任何持久化路径, 紧急平仓数据可能丢失")


# ── 8. 所有修改self.positions的方法是否都持久化 ──
def check_all_position_modifiers():
    print("\n═══ 8. 所有positions修改方法的持久化检查 ═══")
    source = read_file(BROKER)
    tree = ast.parse(source)
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SimulatedBroker":
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    # 检查是否修改了self.positions
                    modifies_positions = False
                    for child in ast.walk(item):
                        # del self.positions[xxx]
                        if isinstance(child, ast.Delete):
                            for target in child.targets:
                                if isinstance(target, ast.Subscript) and \
                                   isinstance(target.value, ast.Attribute) and \
                                   target.value.attr == "positions":
                                    modifies_positions = True
                        # self.positions[xxx] = xxx
                        if isinstance(child, ast.Assign):
                            for target in child.targets:
                                if isinstance(target, ast.Subscript) and \
                                   isinstance(target.value, ast.Attribute) and \
                                   target.value.attr == "positions":
                                    modifies_positions = True
                    
                    if modifies_positions:
                        sync_calls = find_calls_in_node(item, "_sync_save_order_and_position")
                        save_calls = find_calls_in_node(item, "save_state")
                        sell_calls = find_calls_in_node(item, "_execute_sell")
                        buy_calls = find_calls_in_node(item, "_execute_buy")
                        
                        has_persistence = bool(sync_calls or save_calls or sell_calls or buy_calls)
                        
                        if has_persistence:
                            ok(f"{item.name}: 修改positions后有持久化调用")
                        else:
                            p1(f"{item.name}: 修改positions但无持久化调用, 崩溃时持仓可能丢失")


def main():
    print("=" * 60)
    print("写操作持久化完整性审查 v1.0 - 2026-07-16")
    print("=" * 60)
    
    check_execute_sell_returns()
    check_execute_buy_persistence()
    check_execute_order_fill_branches()
    check_fallback_path_persistence()
    check_rejected_path_persistence()
    check_daily_settlement_persistence()
    check_emergency_liquidate_persistence()
    check_all_position_modifiers()
    
    print("\n" + "=" * 60)
    print(f"汇总: P0={len(CRITICAL)}, P1={len(WARNING)}, Info={len(INFO)}")
    if CRITICAL:
        print("\n❌ P0问题:")
        for c in CRITICAL:
            print(f"  - {c}")
    if WARNING:
        print("\n⚠️  P1问题:")
        for w in WARNING:
            print(f"  - {w}")
    print("=" * 60)
    
    return 1 if CRITICAL else (2 if WARNING else 0)


if __name__ == "__main__":
    sys.exit(main())
