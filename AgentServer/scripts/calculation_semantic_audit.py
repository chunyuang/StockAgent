#!/usr/bin/env python3
"""
计算逻辑语义审查 v1.0 (2026-07-16)

审查盲区: 现有审查检查"字段是否存在"和"值范围是否合理", 不检查计算公式是否语义正确。

近期bug:
- v2.9.123 gap_pct基准用avg_cost(买入成本)而非pre_close(昨收) -> 已亏损股的微跳空被误判为大跳空
- circ_mv单位混乱(万元/亿元/百万元) -> 策略过滤完全失效
- pullback_pct存负数但过滤用>=0.15

检查项:
1. 止损/止盈价格计算: 基准是avg_cost, stop_loss_pct的符号和单位
2. 跳空止损gap_pct: 基准应该是pre_close不是avg_cost
3. circ_mv单位链路: 数据源->存储->策略筛选的转换
4. pct_chg符号一致性: 正数=涨, 负数=跌
5. profit_pct计算: (current - cost) / cost * 100, 含/不含佣金
6. ATR止损: ATR14的计算输入和数据来源
7. 快速跌幅: intraday_drop_pct的计算基准
8. 策略参数单位: 回测vs实盘vs数据库
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
def info(msg): INFO.append(msg); print(f"  ℹ️  {msg}")

BROKER = BASE / "nodes" / "market_monitor" / "broker.py"
POS_MGR = BASE / "nodes" / "market_monitor" / "position_manager.py"
SIGNAL_MGR = BASE / "nodes" / "market_monitor" / "signal_manager.py"
SCANNER = BASE / "nodes" / "market_monitor" / "scanner.py"


def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def grep_patterns(source, patterns):
    """搜索多个模式, 返回匹配行列表"""
    results = []
    for i, line in enumerate(source.split('\n'), 1):
        for pat in patterns:
            if re.search(pat, line):
                results.append((i, line.strip(), pat))
                break
    return results


# ── 1. 止损价格计算语义 ──
def check_stop_loss_price_calc():
    print("\n═══ 1. 止损价格计算语义 ═══")
    source = read_file(POS_MGR)
    
    # 止损价 = avg_cost * (1 - stop_loss_pct)
    # 检查: 基准是avg_cost还是current_price? stop_loss_pct是正数还是负数?
    patterns = grep_patterns(source, [
        r'stop_loss_price.*avg_cost',
        r'avg_cost.*stop_loss',
        r'stop_loss_price.*=',
        r'stop_loss_pct.*[+\-*/]',
    ])
    info(f"止损相关代码行: {len(patterns)}处")
    
    # 检查_calc_stop_loss_price方法
    in_method = False
    method_lines = []
    for i, line in enumerate(source.split('\n'), 1):
        if 'def _calc_stop_loss_price' in line or 'def calc_stop_loss' in line:
            in_method = True
        if in_method:
            method_lines.append((i, line))
            if len(method_lines) > 30:
                break
    
    if method_lines:
        info(f"_calc_stop_loss_price 方法({len(method_lines)}行):")
        for lineno, line in method_lines[:15]:
            print(f"  L{lineno}: {line.rstrip()}")
        
        # 检查基准
        method_text = '\n'.join(l for _, l in method_lines)
        if 'avg_cost' in method_text and '1 - ' in method_text:
            ok("止损价基准=avg_cost, 公式=avg_cost*(1-stop_loss_pct) ✅")
        elif 'avg_cost' in method_text and '(1+' in method_text:
            p0("止损价公式可能有符号错误: 使用(1+stop_loss_pct)而非(1-stop_loss_pct)")
        
        # 检查ATR止损
        if 'atr' in method_text.lower():
            info("使用ATR自适应止损")
            if 'min(' in method_text and 'max(' in method_text:
                ok("ATR止损有min/max边界约束 ✅")
            else:
                p1("ATR止损缺少min/max边界约束, 可能产生极端止损价")
    else:
        info("未找到独立的_calc_stop_loss_price方法, 止损价可能在调用处计算")
    
    # 检查broker.py中的止损价计算
    broker_src = read_file(BROKER)
    broker_patterns = grep_patterns(broker_src, [
        r'stop_loss_price.*avg_cost',
        r'avg_cost.*\(1',
    ])
    for lineno, line, _ in broker_patterns[:5]:
        info(f"broker.py L{lineno}: {line}")


# ── 2. 跳空止损gap_pct基准 ──
def check_gap_pct_base():
    print("\n═══ 2. 跳空止损gap_pct基准检查 ═══")
    source = read_file(POS_MGR)
    
    # 找gap_pct的计算
    patterns = grep_patterns(source, [r'gap_pct\s*='])
    info(f"gap_pct计算: {len(patterns)}处")
    
    for lineno, line, _ in patterns:
        print(f"  L{lineno}: {line}")
        
        # 检查基准
        if 'pre_close' in line:
            ok(f"L{lineno}: gap_pct基准=pre_close(昨收) ✅ (v2.9.123已修复)")
        elif 'avg_cost' in line and 'pre_close' not in line:
            p0(f"L{lineno}: gap_pct基准=avg_cost(买入成本), 应该用pre_close(昨收)")
        elif 'pre_close' in line and 'avg_cost' in line:
            info(f"L{lineno}: gap_pct有pre_close和avg_cost的fallback逻辑")
    
    # 检查fallback路径
    fallback_patterns = grep_patterns(source, [r'fallback.*avg_cost|elif avg_cost'])
    for lineno, line, _ in fallback_patterns:
        if 'gap' in line.lower() or 'pre_close' in line:
            info(f"L{lineno}: fallback逻辑: {line}")
    
    # 检查调用点是否传了pre_close
    call_patterns = grep_patterns(source, [r'_check_gap_stop_with_tiered_observation\('])
    for lineno, line, _ in call_patterns:
        if 'pre_close' in line:
            ok(f"L{lineno}: 调用处传了pre_close参数 ✅")
        else:
            p1(f"L{lineno}: 调用处可能没传pre_close参数: {line}")


# ── 3. circ_mv单位链路 ──
def check_circ_mv_unit_chain():
    print("\n═══ 3. circ_mv单位链路检查 ═══")
    signal_src = read_file(SIGNAL_MGR)
    
    # 找circ_mv的处理
    patterns = grep_patterns(signal_src, [r'circ_mv'])
    info(f"signal_manager.py中circ_mv引用: {len(patterns)}处")
    
    for lineno, line, _ in patterns:
        print(f"  L{lineno}: {line}")
    
    # 检查转换逻辑
    if any('10000' in line for _, line, _ in patterns):
        ok("circ_mv有÷10000转换(万元->亿元) ✅")
    else:
        p0("circ_mv没有÷10000转换, 可能单位不一致")
    
    # 检查阈值判断
    if any('10000' in line and 'circ_mv' in line for _, line, _ in patterns):
        # 检查是 >= 10000 才除, 还是总是除
        for lineno, line, _ in patterns:
            if 'circ_mv_raw / 10000' in line or 'circ_mv_raw /10000' in line:
                if 'if circ_mv_raw >= 10000' in line or '>= 10000' in line:
                    ok(f"L{lineno}: circ_mv >= 10000时÷10000, 否则直接用 ✅")
                else:
                    p1(f"L{lineno}: circ_mv总是÷10000, 可能对小值(亿元)过度转换")
    
    # 检查strategy_defaults中的参数单位
    defaults_path = BASE / "nodes" / "backtest_engine" / "strategy_defaults.py"
    if defaults_path.exists():
        defaults_src = read_file(defaults_path)
        mv_patterns = grep_patterns(defaults_src, [r'circulation_market_cap'])
        info(f"strategy_defaults.py中circ_mv参数: {len(mv_patterns)}处")
        for lineno, line, _ in mv_patterns[:3]:
            print(f"  L{lineno}: {line}")
        
        # 检查注释中是否标注了单位
        if any('亿' in line for _, line, _ in mv_patterns):
            ok("策略参数单位=亿元 ✅")


# ── 4. pct_chg符号一致性 ──
def check_pct_chg_sign():
    print("\n═══ 4. pct_chg符号一致性 ═══")
    source = read_file(SIGNAL_MGR)
    
    # pct_chg应该是正数=涨, 负数=跌
    # 检查过滤逻辑是否正确处理符号
    patterns = grep_patterns(source, [r'pct_chg.*[<>]=?\s*[-\d]'])
    info(f"pct_chg过滤逻辑: {len(patterns)}处")
    
    for lineno, line, _ in patterns[:10]:
        print(f"  L{lineno}: {line}")
    
    # 检查abs(pct_chg)的使用(如果是阈值过滤, 用abs正确; 如果是方向判断, 不应用abs)
    abs_patterns = grep_patterns(source, [r'abs\(.*pct_chg'])
    for lineno, line, _ in abs_patterns:
        info(f"L{lineno}: 使用abs(pct_chg) - 如果是涨跌幅阈值过滤则正确, 如果是方向判断则错误")
    
    # 检查pullback_pct的符号
    pullback_patterns = grep_patterns(source, [r'pullback_pct'])
    for lineno, line, _ in pullback_patterns[:5]:
        print(f"  L{lineno}: {line}")


# ── 5. profit_pct计算语义 ──
def check_profit_pct_calc():
    print("\n═══ 5. profit_pct计算语义 ═══")
    source = read_file(BROKER)
    
    # profit_pct = (fill_price - avg_cost) / (avg_cost * qty) * 100
    # 检查分子是profit(含佣金)还是price差
    patterns = grep_patterns(source, [r'profit_pct\s*='])
    info(f"profit_pct计算: {len(patterns)}处")
    
    for lineno, line, _ in patterns:
        print(f"  L{lineno}: {line}")
        
        # 检查公式
        if 'fill_price - pos.avg_cost' in line or 'fill_price - avg_cost' in line:
            if 'total_cost' in line or 'commission' in line:
                ok(f"L{lineno}: profit_pct含佣金 (profit / cost * 100) ✅")
            else:
                info(f"L{lineno}: profit_pct可能是纯价格差, 需确认是否含佣金")
        
        # 检查分母
        if 'avg_cost * order.quantity' in line or 'avg_cost * qty' in line:
            ok(f"L{lineno}: profit_pct分母=avg_cost*qty ✅")
        elif 'avg_cost' in line and 'quantity' not in line and 'qty' not in line:
            p1(f"L{lineno}: profit_pct分母可能缺少qty, 检查公式")
    
    # 检查stop_loss_pct的符号(应该是负数表示亏损)
    pos_src = read_file(POS_MGR)
    sl_patterns = grep_patterns(pos_src, [r'profit_pct.*<=.*stop_loss|profit_pct.*<.*stop_loss'])
    for lineno, line, _ in sl_patterns:
        info(f"L{lineno}: 止损判断: {line}")
        # profit_pct <= stop_loss_pct (stop_loss_pct应该是负数, 如-3表示亏3%)
        # 或者 profit_pct <= -stop_loss_pct (stop_loss_pct是正数, 如3表示亏3%)
        if 'stop_loss_pct' in line:
            # 检查stop_loss_pct的符号
            sl_sign_patterns = grep_patterns(pos_src, [r'stop_loss_pct\s*=\s*[-\d]'])
            for sl_lineno, sl_line, _ in sl_sign_patterns[:3]:
                print(f"  L{sl_lineno}: {sl_line}")
                if '-' in sl_line and 'stop_loss_pct' in sl_line:
                    info("  stop_loss_pct是负数(如-3), profit_pct <= stop_loss_pct 正确")
                else:
                    info("  stop_loss_pct可能是正数(如3), 需确认比较方向")


# ── 6. ATR止损计算输入 ──
def check_atr_calculation():
    print("\n═══ 6. ATR止损计算输入 ═══")
    source = read_file(POS_MGR)
    
    # ATR14需要14天的high/low/pre_close
    # 检查数据来源: T-1日还是T日? MongoDB还是实时?
    patterns = grep_patterns(source, [r'atr|ATR'])
    info(f"ATR相关代码: {len(patterns)}处")
    
    for lineno, line, _ in patterns[:10]:
        print(f"  L{lineno}: {line}")
    
    # 检查ATR计算的输入
    atr_calc = grep_patterns(source, [r'ATR.*high|ATR.*low|atr.*high|atr.*low|true_range|tr_true'])
    if atr_calc:
        for lineno, line, _ in atr_calc[:5]:
            info(f"L{lineno}: ATR输入: {line}")
    
    # 检查数据来源
    data_source = grep_patterns(source, [r'stock_daily_ak_full.*high|daily.*high.*low'])
    for lineno, line, _ in data_source[:3]:
        info(f"L{lineno}: ATR数据来源: {line}")
    
    # 检查T-1 vs T日
    t1_patterns = grep_patterns(source, [r'T-1|prev_day|前一交易|前14天'])
    for lineno, line, _ in t1_patterns[:3]:
        info(f"L{lineno}: {line}")


# ── 7. 快速跌幅计算基准 ──
def check_rapid_drop_calc():
    print("\n═══ 7. 快速跌幅计算基准 ═══")
    source = read_file(POS_MGR)
    
    # intraday_drop_pct = (current_price / today_open - 1) * 100
    # 基准应该是today_open(今日开盘), 不是avg_cost(买入成本)
    patterns = grep_patterns(source, [r'intraday_drop_pct'])
    info(f"intraday_drop_pct计算: {len(patterns)}处")
    
    for lineno, line, _ in patterns:
        print(f"  L{lineno}: {line}")
        
        if 'today_open' in line:
            ok(f"L{lineno}: 快速跌幅基准=today_open(今日开盘) ✅")
        elif 'avg_cost' in line:
            p0(f"L{lineno}: 快速跌幅基准=avg_cost(买入成本), 应该用today_open(今日开盘)")
    
    # 检查RAPID_DROP_THRESHOLD
    threshold_patterns = grep_patterns(source, [r'RAPID_DROP_THRESHOLD'])
    for lineno, line, _ in threshold_patterns:
        print(f"  L{lineno}: {line}")
        if '-5' in line:
            ok("阈值=-5.0% (从开盘跌5%触发) ✅")
        else:
            info(f"阈值={line}, 确认是否合理")


# ── 8. 策略参数单位: 实盘vs回测 ──
def check_param_units_consistency():
    print("\n═══ 8. 策略参数单位一致性(实盘vs回测) ═══")
    signal_src = read_file(SIGNAL_MGR)
    defaults_path = BASE / "nodes" / "backtest_engine" / "strategy_defaults.py"
    
    if not defaults_path.exists():
        info("strategy_defaults.py不存在, 跳过")
        return
    
    defaults_src = read_file(defaults_path)
    
    # 检查stop_loss_pct: 实盘vs回测
    # 实盘: position_manager中stop_loss_pct是小数(0.03)还是百分比(3.0)?
    pos_src = read_file(POS_MGR)
    
    # position_manager中的stop_loss_pct
    sl_patterns = grep_patterns(pos_src, [r'stop_loss_pct.*=.*0\.\d|stop_loss_pct.*\*.*100'])
    info("position_manager stop_loss_pct:")
    for lineno, line, _ in sl_patterns[:5]:
        print(f"  L{lineno}: {line}")
        if '0.0' in line:
            info("  -> 小数形式(0.03=3%)")
        elif '* 100' in line:
            info("  -> 转为百分比(3.0=3%)")
    
    # strategy_defaults中的stop_loss_pct
    sl_defaults = grep_patterns(defaults_src, [r'stop_loss_pct.*:.*0\.\d|stop_loss_pct.*:.*\d'])
    info("strategy_defaults stop_loss_pct:")
    for lineno, line, _ in sl_defaults[:5]:
        print(f"  L{lineno}: {line}")
    
    # signal_manager中的stop_loss_pct使用
    sl_signal = grep_patterns(signal_src, [r'stop_loss_pct'])
    info("signal_manager stop_loss_pct引用:")
    for lineno, line, _ in sl_signal[:3]:
        print(f"  L{lineno}: {line}")
    
    # 回测引擎中的stop_loss_pct
    backtest_path = BASE / "nodes" / "backtest_engine" / "portfolio_backtest.py"
    if backtest_path.exists():
        bt_src = read_file(backtest_path)
        sl_bt = grep_patterns(bt_src, [r'stop_loss_pct.*\*.*10000|stop_loss_pct.*100|min_circ_mv.*10000'])
        info("回测引擎 stop_loss_pct/circ_mv转换:")
        for lineno, line, _ in sl_bt[:5]:
            print(f"  L{lineno}: {line}")
        
        # 检查回测中circ_mv的转换
        circ_bt = grep_patterns(bt_src, [r'circ_mv.*10000|circulation_market_cap.*10000|min_circ_mv.*10000'])
        for lineno, line, _ in circ_bt[:3]:
            info(f"  回测 L{lineno}: {line} (参数×10000=万元->亿元转换)")
    
    # 检查turnover_rate单位
    tr_signal = grep_patterns(signal_src, [r'turnover_rate.*[<>]=?'])
    tr_defaults = grep_patterns(defaults_src, [r'turnover_rate'])
    info(f"turnover_rate参数: signal_manager={len(tr_signal)}处, defaults={len(tr_defaults)}处")
    
    # turnover_rate应该是百分比(如15表示15%), 检查是否一致
    for lineno, line, _ in tr_defaults[:3]:
        print(f"  defaults L{lineno}: {line}")


def main():
    print("=" * 60)
    print("计算逻辑语义审查 v1.0 - 2026-07-16")
    print("=" * 60)
    
    check_stop_loss_price_calc()
    check_gap_pct_base()
    check_circ_mv_unit_chain()
    check_pct_chg_sign()
    check_profit_pct_calc()
    check_atr_calculation()
    check_rapid_drop_calc()
    check_param_units_consistency()
    
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
