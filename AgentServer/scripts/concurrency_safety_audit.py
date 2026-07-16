#!/usr/bin/env python3
"""
并发安全审查脚本 v1.0 (2026-07-16)

审查盲区: 现有审查只检查单代码路径正确性, 不检查多路径并发访问同一资源。

近期bug:
- v2.9.122 重复卖出虚增19.4万: risk_thread/position_checker/强制空仓三线程并发卖出同一ts_code
- v2.9.121 双重卖出竞态: 强制空仓和止盈对同一股票并发执行

检查项:
1. broker所有sell path是否有锁保护
2. 共享资源(positions/cash/_today_sold)的锁审计
3. 多线程调用路径分析
4. buy path并发安全性
5. save_state并发安全性
6. 线程启动/停止一致性
"""
import sys
import ast
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

CRITICAL = []  # P0
WARNING = []   # P1
INFO = []      # P2/info

def p0(msg): CRITICAL.append(msg); print(f"  ❌ P0: {msg}")
def p1(msg): WARNING.append(msg); print(f"  ⚠️  P1: {msg}")
def ok(msg): print(f"  ✅ {msg}")
def info(msg): INFO.append(msg); print(f"  ℹ️  {msg}")

BROKER = BASE / "nodes" / "market_monitor" / "broker.py"
SCANNER = BASE / "nodes" / "market_monitor" / "scanner.py"
POS_MGR = BASE / "nodes" / "market_monitor" / "position_manager.py"
SIGNAL_MGR = BASE / "nodes" / "market_monitor" / "signal_manager.py"


def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def parse_ast(source, filename="<unknown>"):
    try:
        return ast.parse(source, filename=filename)
    except SyntaxError as e:
        print(f"  ⚠️  语法错误 {filename}: {e}")
        return None


def find_methods_calling(class_name, method_name, source):
    """找到class_name中调用method_name的所有方法"""
    tree = parse_ast(source)
    if not tree:
        return []
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for call in ast.walk(item):
                        if isinstance(call, ast.Attribute) and call.attr == method_name:
                            results.append(item.name)
    return list(set(results))


def find_attr_access(class_name, attr_name, source):
    """找到class_name中访问attr_name的所有方法"""
    tree = parse_ast(source)
    if not tree:
        return []
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for child in ast.walk(item):
                        if isinstance(child, ast.Attribute) and child.attr == attr_name:
                            results.append((item.name, child.lineno))
    return results


# ── 1. Sell Path锁保护检查 ──
def check_sell_path_locks():
    print("\n═══ 1. Sell Path锁保护检查 ═══")
    source = read_file(BROKER)
    
    # 找到所有执行卖出的方法
    sell_methods = find_methods_calling("SimulatedBroker", "_execute_sell", source)
    if not sell_methods:
        # 直接搜索
        sell_methods = ["_execute_sell"]
    
    # 检查_execute_sell是否有锁保护
    tree = parse_ast(source)
    if not tree:
        p0("无法解析broker.py AST")
        return
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SimulatedBroker":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_execute_sell":
                    # 检查方法体中是否有with self._sell_lock
                    has_lock = False
                    for child in ast.walk(item):
                        if isinstance(child, ast.With):
                            for withitem in child.items:
                                if isinstance(withitem.context_expr, ast.Attribute):
                                    if withitem.context_expr.attr == "_sell_lock":
                                        has_lock = True
                    
                    if has_lock:
                        ok("_execute_sell 有 _sell_lock 保护")
                    else:
                        p0("_execute_sell 没有 _sell_lock 保护 (v2.9.122修复了, 但需确认)")
                    
                    # 检查return路径是否在锁内
                    # 简单方法: 看return语句是否在with块内
                    returns_in_lock = 0
                    for child in ast.walk(item):
                        if isinstance(child, ast.Return):
                            # 检查是否在with _sell_lock块内
                            # AST不直接给parent, 用简单启发: 如果方法体第一个with就是锁
                            returns_in_lock += 1  # 保守估计
                    
                    info(f"_execute_sell 有 {returns_in_lock} 个return语句")
    
    # 检查place_order是否调用_execute_sell
    place_order_calls_sell = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SimulatedBroker":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "place_order":
                    for child in ast.walk(item):
                        if isinstance(child, ast.Attribute) and child.attr == "_execute_sell":
                            place_order_calls_sell = True
    if place_order_calls_sell:
        ok("place_order -> _execute_sell (有锁保护传递)")
    
    # 检查其他sell path: emergency_liquidate, execute_sell_list_from_risk等
    other_sell_paths = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SimulatedBroker":
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    method_name = item.name
                    if any(kw in method_name.lower() for kw in ['sell', 'liquidate', 'close', 'clear']):
                        # 检查是否最终调用_execute_sell或直接修改positions/cash
                        calls_execute_sell = False
                        directly_modifies_positions = False
                        directly_modifies_cash = False
                        for child in ast.walk(item):
                            if isinstance(child, ast.Attribute):
                                if child.attr == "_execute_sell":
                                    calls_execute_sell = True
                                if child.attr == "positions":
                                    directly_modifies_positions = True
                                if child.attr in ("available_cash", "today_profit"):
                                    directly_modifies_cash = True
                        
                        if method_name not in ("_execute_sell",):
                            if calls_execute_sell:
                                ok(f"{method_name} -> _execute_sell (锁保护传递)")
                            elif directly_modifies_positions or directly_modifies_cash:
                                p1(f"{method_name} 直接修改positions/cash, 未通过_execute_sell, 可能缺锁保护")
                                other_sell_paths.append(method_name)
    
    if not other_sell_paths:
        ok("所有sell path都通过_execute_sell执行, 锁保护完整")


# ── 2. 共享资源锁审计 ──
def check_shared_resource_locks():
    print("\n═══ 2. 共享资源锁审计 ═══")
    source = read_file(BROKER)
    tree = parse_ast(source)
    if not tree:
        return
    
    # 找到所有锁定义
    locks = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SimulatedBroker":
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Attribute) and isinstance(target.attr, str):
                            if "lock" in target.attr.lower():
                                locks.add(target.attr)
    
    info(f"broker.py中定义的锁: {locks}")
    
    # 检查self.positions的访问
    pos_access = find_attr_access("SimulatedBroker", "positions", source)
    pos_writers = []
    pos_readers = []
    for method, lineno in pos_access:
        # 简单启发: 如果方法名包含buy/sell/execute/clear/daily/settlement/emergency, 认为是写操作
        if any(kw in method.lower() for kw in ['buy', 'sell', 'execute', 'clear', 'daily', 'settlement', 'emergency', 'liquidate', 'close', 'reset']):
            pos_writers.append((method, lineno))
        else:
            pos_readers.append((method, lineno))
    
    info(f"positions写操作: {len(pos_writers)}处, 读操作: {len(pos_readers)}处")
    
    # 检查self.account.available_cash的访问
    cash_access = find_attr_access("SimulatedBroker", "available_cash", source)
    cash_writers = []
    for method, lineno in cash_access:
        if any(kw in method.lower() for kw in ['buy', 'sell', 'execute', 'settlement', 'reset', 'liquidate', 'close']):
            cash_writers.append((method, lineno))
    
    info(f"available_cash写操作: {len(cash_writers)}处")
    
    # 检查_today_sold的访问
    today_sold_access = find_attr_access("SimulatedBroker", "_today_sold", source)
    today_sold_methods = set(m for m, _ in today_sold_access)
    info(f"_today_sold访问方法: {today_sold_methods}")
    
    # 检查_today_sold.add()是否只在_sell_lock内
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SimulatedBroker":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_execute_sell":
                    # 检查_today_sold.add是否在with _sell_lock块内
                    in_lock = False
                    for child in ast.walk(item):
                        if isinstance(child, ast.With):
                            for withitem in child.items:
                                if isinstance(withitem.context_expr, ast.Attribute) and \
                                   withitem.context_expr.attr == "_sell_lock":
                                    in_lock = True
                        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                            if child.func.attr == "add" and isinstance(child.func.value, ast.Attribute):
                                if child.func.value.attr == "_today_sold":
                                    if in_lock:
                                        ok("_today_sold.add() 在 _sell_lock 内")
                                    else:
                                        p0(f"_today_sold.add() 在 _execute_sell 中但不在 _sell_lock 内 (line {child.lineno})")
    
    # 检查_today_sold.clear()是否在daily_settlement中
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SimulatedBroker":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "daily_settlement":
                    has_clear = False
                    for child in ast.walk(item):
                        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                            if child.func.attr == "clear" and isinstance(child.func.value, ast.Attribute):
                                if child.func.value.attr == "_today_sold":
                                    has_clear = True
                    if has_clear:
                        ok("daily_settlement 重置 _today_sold")
                    else:
                        p1("daily_settlement 未重置 _today_sold, 跨日重复卖出防护失效")


# ── 3. 多线程调用路径分析 ──
def check_thread_call_paths():
    print("\n═══ 3. 多线程调用路径分析 ═══")
    scanner_src = read_file(SCANNER)
    read_file(BROKER)
    
    # 找到scanner.py中所有Thread启动
    tree = parse_ast(scanner_src)
    if tree:
        threads = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "Thread":
                    # 提取target
                    for kw in node.keywords:
                        if kw.arg == "target":
                            if isinstance(kw.value, ast.Attribute):
                                threads.append(kw.value.attr)
                            elif isinstance(kw.value, ast.Name):
                                threads.append(kw.value.id)
        
        info(f"scanner.py启动的线程: {threads}")
        
        # 对每个线程target, 检查它调用了哪些broker方法
        for thread_target in threads:
            # 搜索scanner.py中thread_target方法的调用链
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name == thread_target:
                            broker_calls = set()
                            for child in ast.walk(item):
                                if isinstance(child, ast.Attribute) and child.attr in (
                                    "place_order", "_execute_sell", "_execute_buy",
                                    "execute_sell_list_from_risk", "emergency_liquidate",
                                    "check_stop_loss_only", "save_state"
                                ):
                                    broker_calls.add(child.attr)
                            
                            if broker_calls:
                                info(f"线程 {thread_target} 调用broker方法: {broker_calls}")
                                
                                # 检查是否有锁保护的调用
                                if "place_order" in broker_calls or "_execute_sell" in broker_calls:
                                    ok(f"线程 {thread_target} 通过place_order/_execute_sell访问(有锁保护)")
                                if "emergency_liquidate" in broker_calls:
                                    # emergency_liquidate是否通过_execute_sell?
                                    info(f"线程 {thread_target} 调用emergency_liquidate, 需确认是否通过_execute_sell")
                                if "execute_sell_list_from_risk" in broker_calls:
                                    info(f"线程 {thread_target} 调用execute_sell_list_from_risk, 需确认是否通过_execute_sell")
    
    # 检查position_manager的调用路径
    pos_src = read_file(POS_MGR)
    pos_tree = parse_ast(pos_src)
    if pos_tree:
        # 找check_stop_loss_only方法调用了哪些broker方法
        for node in ast.walk(pos_tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "check_stop_loss_only":
                        calls = set()
                        for child in ast.walk(item):
                            if isinstance(child, ast.Attribute) and child.attr in (
                                "place_order", "_execute_sell", "execute_sell_list_from_risk"
                            ):
                                calls.add(child.attr)
                        if calls:
                            info(f"position_manager.check_stop_loss_only 调用: {calls}")


# ── 4. Buy Path并发安全性 ──
def check_buy_path_safety():
    print("\n═══ 4. Buy Path并发安全性 ═══")
    source = read_file(BROKER)
    tree = parse_ast(source)
    if not tree:
        return
    
    # _execute_buy是否需要锁?
    # buy操作: 修改available_cash, positions
    # 如果buy和sell并发: buy扣cash + sell加cash, 不会产生负数? 可能会
    # 如果两个buy并发: 同一ts_code加仓, positions竞争
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SimulatedBroker":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_execute_buy":
                    has_lock = False
                    for child in ast.walk(item):
                        if isinstance(child, ast.With):
                            for withitem in child.items:
                                if isinstance(withitem.context_expr, ast.Attribute):
                                    if "lock" in (withitem.context_expr.attr or "").lower():
                                        has_lock = True
                    
                    if has_lock:
                        ok("_execute_buy 有锁保护")
                    else:
                        p1("_execute_buy 没有锁保护 (buy和sell并发可能导致positions竞争)")
                        info("  当前: buy在主线程(scan_loop)执行, sell在risk_thread执行, 存在并发风险")
                        info("  建议: 考虑给_execute_buy也加锁, 或用全局_state_lock")


# ── 5. save_state并发安全性 ──
def check_save_state_concurrency():
    print("\n═══ 5. save_state并发安全性 ═══")
    source = read_file(BROKER)
    tree = parse_ast(source)
    if not tree:
        return
    
    # save_state是async方法, _sync_save_order_and_position是sync方法
    # 如果两者并发: save_state可能读到半更新状态
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SimulatedBroker":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "save_state":
                    has_lock = False
                    for child in ast.walk(item):
                        if isinstance(child, ast.With):
                            for withitem in child.items:
                                if isinstance(withitem.context_expr, ast.Attribute):
                                    if "lock" in (withitem.context_expr.attr or "").lower():
                                        has_lock = True
                    if not has_lock:
                        info("save_state(async) 无锁, 与_sync_save_order_and_position(sync)可能并发")
                        info("  风险: save_state可能读到半更新状态, 但因async/sync分属不同上下文, 实际并发概率低")
                    else:
                        ok("save_state 有锁保护")
    
    # 检查_sync_save_order_and_position是否有重入保护
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SimulatedBroker":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_sync_save_order_and_position":
                    # 检查是否在_sell_lock内调用(如果从_execute_sell调用, 已经在锁内)
                    info("_sync_save_order_and_position 被 _execute_sell(sell_lock内) 和 _execute_order_fill 调用")
                    info("  如果 _execute_order_fill 也有锁保护, 则安全")
                    
                    # 检查_execute_order_fill是否有锁
                    for item2 in node.body:
                        if isinstance(item2, ast.FunctionDef) and item2.name == "_execute_order_fill":
                            has_lock = False
                            for child in ast.walk(item2):
                                if isinstance(child, ast.With):
                                    for withitem in child.items:
                                        if isinstance(withitem.context_expr, ast.Attribute):
                                            if "lock" in (withitem.context_expr.attr or "").lower():
                                                has_lock = True
                            if has_lock:
                                ok("_execute_order_fill 有锁保护")
                            else:
                                p1("_execute_order_fill 无锁保护, 调用_sync_save_order_and_position可能与sell并发")


# ── 6. 线程启动/停止一致性 ──
def check_thread_lifecycle():
    print("\n═══ 6. 线程启动/停止一致性 ═══")
    source = read_file(SCANNER)
    tree = parse_ast(source)
    if not tree:
        return
    
    # 找到start方法中启动的线程
    started_threads = []
    stopped_threads = []
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    method_name = item.name
                    for child in ast.walk(item):
                        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                            if child.func.attr == "Thread":
                                started_threads.append((method_name, child.lineno))
                            if child.func.attr in ("join", "stop"):
                                stopped_threads.append((method_name, child.func.attr, child.lineno))
    
    info(f"线程启动: {started_threads}")
    info(f"线程停止: {stopped_threads}")
    
    # 检查stop()是否join所有线程
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "stop":
                    joins = 0
                    for child in ast.walk(item):
                        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                            if child.func.attr == "join":
                                joins += 1
                    if joins >= 2:
                        ok(f"stop() join了{joins}个线程")
                    elif joins == 1:
                        p1("stop() 只join了1个线程, 可能有线程未被正确停止")
                    else:
                        p0("stop() 没有join任何线程, 线程可能继续运行导致并发问题")
    
    # 检查_is_running是否在stop()中被清除
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "stop":
                    clears_running = False
                    for child in ast.walk(item):
                        if isinstance(child, ast.Assign):
                            for target in child.targets:
                                if isinstance(target, ast.Attribute) and target.attr == "_is_running":
                                    clears_running = True
                    if clears_running:
                        ok("stop() 清除 _is_running")
                    else:
                        p0("stop() 未清除 _is_running (7/15假运行故障根因)")


# ── 7. 检查position_manager的state_lock使用 ──
def check_position_manager_locks():
    print("\n═══ 7. PositionManager锁使用检查 ═══")
    source = read_file(POS_MGR)
    tree = parse_ast(source)
    if not tree:
        return
    
    # 找到state_lock属性
    has_state_lock = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "state_lock":
                    has_state_lock = True
    
    if has_state_lock:
        ok("PositionManager 有 state_lock 属性")
    else:
        info("PositionManager 无 state_lock (可能不需要)")
    
    # 检查哪些方法访问self._positions (PositionManager内部持仓)
    pos_access = find_attr_access("PositionManager", "_positions", source)
    if pos_access:
        info(f"PositionManager._positions 访问: {len(pos_access)}处")
        # 检查写操作是否有锁
        for method, lineno in pos_access:
            if any(kw in method.lower() for kw in ['update', 'set', 'add', 'remove', 'clear', 'delete']):
                info(f"  写操作: {method} (line {lineno})")
    
    # 检查check_stop_loss_only是否线程安全
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "check_stop_loss_only":
                    # 这个方法被risk_thread调用, 检查是否修改了共享状态
                    modifies_positions = False
                    for child in ast.walk(item):
                        if isinstance(child, ast.Attribute) and child.attr in ("_positions", "positions"):
                            # 检查是否是赋值/删除
                            modifies_positions = True  # 保守判断
                    if modifies_positions:
                        info("check_stop_loss_only 访问positions (risk_thread调用)")
                        info("  需确认: 是否只读访问, 还是也修改positions")


def main():
    print("=" * 60)
    print("并发安全审查 v1.0 - 2026-07-16")
    print("=" * 60)
    
    check_sell_path_locks()
    check_shared_resource_locks()
    check_thread_call_paths()
    check_buy_path_safety()
    check_save_state_concurrency()
    check_thread_lifecycle()
    check_position_manager_locks()
    
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
