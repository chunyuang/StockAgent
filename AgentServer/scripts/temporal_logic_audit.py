#!/usr/bin/env python3
"""
时序逻辑审查 v1.0 (2026-07-16)

审查盲区: 现有审查不检查时间相关逻辑的正确性。

近期bug:
- gap_pct基准用错(avg_cost vs pre_close, 本质是"用T日数据还是T-1数据"的问题)
- T+1检查边界: 今日买入的股票今日不可卖
- 周五新建仓限制(时间相关交易限制)
- pre_close缺失时的fallback策略(用T日数据代替T-1会导致逻辑错误)

检查项:
1. pre_close/prev_close数据来源验证: 所有用到"昨收"的计算, 数据是否来自T-1日
2. T+1规则: today_buy_qty与available_qty的关系
3. 时间相关交易限制: 周五新建仓/尾盘禁止开仓/集合竞价
4. 数据缺失fallback: T-1数据缺失时用T日数据是否会导致逻辑错误
5. trade_date一致性: 同一批计算中trade_date是否统一
6. 实时行情vs收盘数据: 盘中用的数据和盘后用的数据是否混淆
"""
import sys
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

CRITICAL = []
WARNING = []
INFO = []

def p0(msg): CRITICAL.append(msg); print(f"  ❌ P0: {msg}")
def p1(msg): WARNING.append(msg); print(f"  ⚠️  P1: {msg}")
def ok(msg): print(f"  ✅ {msg}")
def info(msg): INFO.append(msg); print(f"  ℹ️  {info}" if False else f"  ℹ️  {msg}")

BROKER = BASE / "nodes" / "market_monitor" / "broker.py"
POS_MGR = BASE / "nodes" / "market_monitor" / "position_manager.py"
SIGNAL_MGR = BASE / "nodes" / "market_monitor" / "signal_manager.py"
SCANNER = BASE / "nodes" / "market_monitor" / "scanner.py"


def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def grep_lines(source, patterns):
    results = []
    for i, line in enumerate(source.split('\n'), 1):
        for pat in patterns:
            if re.search(pat, line):
                results.append((i, line.strip()))
                break
    return results


# ── 1. pre_close数据来源验证 ──
def check_pre_close_source():
    print("\n═══ 1. pre_close/prev_close数据来源验证 ═══")
    
    # position_manager.py中所有使用pre_close的地方
    pos_src = read_file(POS_MGR)
    patterns = grep_lines(pos_src, [r'pre_close', r'prev_close', r'previous_close'])
    info(f"position_manager.py中pre_close引用: {len(patterns)}处")
    
    for lineno, line in patterns:
        # 检查pre_close来源
        if 'rt.get' in line or 'rt[' in line:
            info(f"L{lineno}: pre_close来自实时行情(rt): {line}")
        elif 'daily' in line.lower() or 'ak_full' in line:
            info(f"L{lineno}: pre_close来自日线数据: {line}")
        elif 'fallback' in line.lower() or 'default' in line.lower():
            p1(f"L{lineno}: pre_close有fallback, 需确认fallback数据来源: {line}")
        else:
            info(f"L{lineno}: {line}")
    
    # 检查pre_close缺失时的处理
    fallback_patterns = grep_lines(pos_src, [r'pre_close.*0|pre_close.*None|pre_close.*not|if.*pre_close'])
    info("pre_close缺失处理:")
    for lineno, line in fallback_patterns[:5]:
        print(f"  L{lineno}: {line}")
    
    # 检查是否用T日数据fallback T-1
    t1_fallback = grep_lines(pos_src, [r'fallback.*avg_cost|elif avg_cost.*gap'])
    for lineno, line in t1_fallback:
        p1(f"L{lineno}: pre_close缺失时用avg_cost(可能是T日数据)fallback, 语义不正确: {line}")


# ── 2. T+1规则验证 ──
def check_t_plus_1():
    print("\n═══ 2. T+1规则验证 ═══")
    broker_src = read_file(BROKER)
    
    # T+1: 今日买入的股票今日不可卖
    # 实现方式: available_qty = total_qty - today_buy_qty
    # 卖出时检查: order.quantity <= pos.available_qty
    
    # 检查available_qty的设置
    avail_patterns = grep_lines(broker_src, [r'available_qty'])
    info(f"broker.py中available_qty引用: {len(avail_patterns)}处")
    
    # 检查新建仓时available_qty=0
    new_pos_patterns = grep_lines(broker_src, [r'Position\(', r'available_qty=0'])
    for lineno, line in new_pos_patterns:
        if 'Position(' in line:
            info(f"L{lineno}: 新建Position: {line[:80]}")
        elif 'available_qty=0' in line or 'available_qty = 0' in line:
            ok(f"L{lineno}: 新仓available_qty=0 (T+1锁定) ✅")
    
    # 检查买入时today_buy_qty的增加
    buy_patterns = grep_lines(broker_src, [r'today_buy_qty.*\+'])
    for lineno, line in buy_patterns:
        info(f"L{lineno}: 买入时today_buy_qty增加: {line}")
    
    # 检查卖出时是否校验available_qty
    sell_check = grep_lines(broker_src, [r'available_qty.*<|available_qty.*-=|available_qty.*order.quantity'])
    for lineno, line in sell_check[:5]:
        print(f"  L{lineno}: {line}")
    
    # 检查daily_settlement重置available_qty
    settlement_patterns = grep_lines(broker_src, [r'available_qty.*=.*total_qty|available_qty.*total_qty'])
    for lineno, line in settlement_patterns:
        ok(f"L{lineno}: daily_settlement重置available_qty=total_qty (T+1解锁) ✅")
    
    # 检查_validate_sell中的T+1检查
    validate_patterns = grep_lines(broker_src, [r'available_qty.*<.*quantity|T\+1|today_buy'])
    for lineno, line in validate_patterns:
        if 'T+1' in line or 'available_qty' in line:
            info(f"L{lineno}: {line}")


# ── 3. 时间相关交易限制 ──
def check_time_based_restrictions():
    print("\n═══ 3. 时间相关交易限制 ═══")
    broker_src = read_file(BROKER)
    signal_src = read_file(SIGNAL_MGR)
    
    # 3.1 尾盘禁止新开仓
    tail_patterns = grep_lines(broker_src, [r'14:30|14:50|尾盘|禁止新开仓|forbid.*new|no_new_position'])
    info("尾盘禁止开仓:")
    for lineno, line in tail_patterns:
        print(f"  L{lineno}: {line}")
    
    # 3.2 周五新建仓限制
    friday_patterns = grep_lines(signal_src, [r'friday|周五|weekday.*4|weekday.*==.*4'])
    info("周五新建仓限制:")
    for lineno, line in friday_patterns:
        print(f"  L{lineno}: {line}")
        if 'friday' in line.lower() or '周五' in line:
            ok(f"L{lineno}: 有周五新建仓限制 ✅")
    
    # 3.3 集合竞价/连续竞价门控
    phase_patterns = grep_lines(broker_src, [r'is_continuous_auction|MarketPhase|is_auction|is_trading'])
    info("交易时段门控:")
    for lineno, line in phase_patterns[:5]:
        print(f"  L{lineno}: {line}")
    
    # 检查sell path是否都有MarketPhase检查
    sell_paths = grep_lines(broker_src, [r'def.*sell|def.*liquidate|def.*close'])
    for lineno, line in sell_paths:
        # 检查这个方法体中是否有MarketPhase检查(简单启发: 往下看10行)
        lines = broker_src.split('\n')
        has_phase_check = False
        for j in range(lineno, min(lineno + 15, len(lines))):
            if 'is_continuous_auction' in lines[j-1] or 'MarketPhase' in lines[j-1]:
                has_phase_check = True
                break
        if has_phase_check:
            ok(f"L{lineno}: {line.split('(')[0]} 有MarketPhase门控 ✅")
        else:
            p1(f"L{lineno}: {line.split('(')[0]} 可能缺少MarketPhase门控")


# ── 4. 数据缺失fallback安全性 ──
def check_fallback_safety():
    print("\n═══ 4. 数据缺失fallback安全性 ═══")
    pos_src = read_file(POS_MGR)
    
    # 检查所有fallback逻辑: 关键数据缺失时用什么替代
    fallback_patterns = grep_lines(pos_src, [r'fallback|if not.*or.*0|if.*<= 0.*else'])
    info(f"fallback逻辑: {len(fallback_patterns)}处")
    
    dangerous_fallbacks = []
    for lineno, line in fallback_patterns:
        # 危险fallback: 用T日数据代替T-1, 用avg_cost代替市场价, 用0代替关键参数
        if 'avg_cost' in line and ('pre_close' in line or 'open' in line):
            dangerous_fallbacks.append((lineno, line, "用avg_cost代替pre_close/open"))
        elif '0' in line and ('pre_close' in line or 'open' in line or 'high' in line or 'low' in line):
            dangerous_fallbacks.append((lineno, line, "关键数据缺失时用0"))
    
    if dangerous_fallbacks:
        for lineno, line, issue in dangerous_fallbacks:
            p1(f"L{lineno}: {issue}: {line}")
    else:
        ok("未发现危险的fallback逻辑")


# ── 5. trade_date一致性 ──
def check_trade_date_consistency():
    print("\n═══ 5. trade_date一致性 ═══")
    broker_src = read_file(BROKER)
    scanner_src = read_file(SCANNER)
    
    # 检查broker.py中trade_date的来源
    td_patterns = grep_lines(broker_src, [r'trade_date\s*='])
    info(f"broker.py中trade_date赋值: {len(td_patterns)}处")
    
    for lineno, line in td_patterns[:5]:
        print(f"  L{lineno}: {line}")
        if 'datetime' in line or 'now' in line:
            info("  -> trade_date来自当前时间")
        elif 'order' in line:
            info("  -> trade_date来自order")
    
    # 检查scanner.py中trade_date的传递
    td_scanner = grep_lines(scanner_src, [r'trade_date\s*='])
    info(f"scanner.py中trade_date赋值: {len(td_scanner)}处")
    
    for lineno, line in td_scanner[:3]:
        print(f"  L{lineno}: {line}")
    
    # 检查是否存在多处trade_date来源不一致的风险
    if td_patterns:
        sources = set()
        for _, line in td_patterns:
            if 'datetime' in line or 'now' in line:
                sources.add("datetime")
            elif 'order' in line:
                sources.add("order")
            elif 'param' in line or 'arg' in line:
                sources.add("param")
        if len(sources) > 1:
            p1(f"trade_date有{len(sources)}种来源: {sources}, 可能存在不一致风险")
        else:
            ok(f"trade_date来源统一: {sources}")


# ── 6. 实时行情vs收盘数据混淆 ──
def check_realtime_vs_close():
    print("\n═══ 6. 实时行情vs收盘数据混淆 ═══")
    pos_src = read_file(POS_MGR)
    
    # 盘中: 用realtime_data的current_price
    # 盘后: 用MongoDB的close价格
    # 如果盘中用了close价格 -> 逻辑错误
    # 如果盘后用了realtime价格 -> 可能过期
    
    rt_patterns = grep_lines(pos_src, [r'realtime_data|rt\.get|rt\['])
    close_patterns = grep_lines(pos_src, [r'\.get\("close"|\.get\(.*close|daily.*close'])
    
    info(f"实时行情引用: {len(rt_patterns)}处, 收盘价引用: {len(close_patterns)}处")
    
    # 检查current_price的来源
    cp_patterns = grep_lines(pos_src, [r'current_price\s*='])
    info("current_price赋值:")
    for lineno, line in cp_patterns[:5]:
        print(f"  L{lineno}: {line}")
        if 'rt' in line or 'realtime' in line:
            info("  -> 来自实时行情")
        elif 'close' in line:
            info("  -> 来自收盘价")
    
    # 检查是否有混用
    for lineno, line in cp_patterns:
        if 'rt' in line and 'close' in line:
            p1(f"L{lineno}: 同一行同时引用实时行情和收盘价, 可能混淆: {line}")
    
    # 检查broker.py中current_price的更新
    broker_src = read_file(BROKER)
    cp_broker = grep_lines(broker_src, [r'current_price\s*='])
    info("broker.py中current_price赋值:")
    for lineno, line in cp_broker[:3]:
        print(f"  L{lineno}: {line}")


# ── 7. 开盘价数据来源 ──
def check_open_price_source():
    print("\n═══ 7. 开盘价数据来源 ═══")
    pos_src = read_file(POS_MGR)
    
    # 开盘价用于跳空止损和快速跌幅计算
    # 来源应该是实时行情的open字段, 不是daily的open
    open_patterns = grep_lines(pos_src, [r'today_open\s*=|open_price\s*='])
    info("开盘价赋值:")
    for lineno, line in open_patterns:
        print(f"  L{lineno}: {line}")
        if 'rt.get' in line or 'rt[' in line:
            ok(f"L{lineno}: 开盘价来自实时行情 ✅")
        elif 'daily' in line or 'ak_full' in line:
            p1(f"L{lineno}: 开盘价来自日线数据, 盘中可能不准确")
    
    # 检查_get_open_price方法
    get_open = grep_lines(pos_src, [r'def _get_open_price'])
    for lineno, line in get_open:
        info(f"L{lineno}: {line}")
        # 读下面几行看实现
        lines = pos_src.split('\n')
        for j in range(lineno, min(lineno + 10, len(lines))):
            print(f"  L{j+1}: {lines[j]}")
            if 'return' in lines[j]:
                break


def main():
    print("=" * 60)
    print("时序逻辑审查 v1.0 - 2026-07-16")
    print("=" * 60)
    
    check_pre_close_source()
    check_t_plus_1()
    check_time_based_restrictions()
    check_fallback_safety()
    check_trade_date_consistency()
    check_realtime_vs_close()
    check_open_price_source()
    
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
