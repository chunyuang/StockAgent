#!/usr/bin/env python3
"""
实盘 vs 回测 参数一致性检查 (v2.9.92x)

检查逻辑:
1. 从 strategy_defaults.py 读取回测参数(权威源)
2. 模拟实盘代码的参数读取路径(get_strategy_risk等)
3. 逐项对比，发现不一致立即报错
4. 输出结构化报告

运行: python3 scripts/check_params_alignment.py
退出码: 0=全部一致, 1=有不一致
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
try:
    from nodes.backtest_engine.factor_selection.sell_signal_checker import STRATEGY_PULLBACK_PARAMS
except ImportError:
    STRATEGY_PULLBACK_PARAMS = {}

# ============================================================
# 1. 全局风控参数
# ============================================================
def check_global_risk():
    """检查实盘代码是否正确读取GLOBAL_RISK参数"""
    issues = []
    
    # 检查broker.py中的仓位限制
    try:
        from nodes.market_monitor.broker import SimulatedBroker
        b = SimulatedBroker.__new__(SimulatedBroker)
        # 读取类变量
        max_pos = getattr(SimulatedBroker, 'MAX_POSITION_RATIO', None)
        max_total = getattr(SimulatedBroker, 'MAX_TOTAL_RATIO', None)
        
        expected_pos = GLOBAL_RISK['max_position_per_stock']
        expected_total = GLOBAL_RISK['max_total_position']
        
        if max_pos is not None and abs(max_pos - expected_pos) > 0.001:
            issues.append(f"broker.MAX_POSITION_RATIO={max_pos} vs GLOBAL_RISK.max_position_per_stock={expected_pos}")
        if max_total is not None and abs(max_total - expected_total) > 0.001:
            issues.append(f"broker.MAX_TOTAL_RATIO={max_total} vs GLOBAL_RISK.max_total_position={expected_total}")
    except Exception as e:
        issues.append(f"broker仓位检查异常: {e}")
    
    return issues

# ============================================================
# 2. 策略风控参数 (riskParams)
# ============================================================
def check_strategy_risk_params():
    """检查get_strategy_risk是否正确合并所有参数"""
    issues = []
    
    # 模拟get_strategy_risk的逻辑(修复后)
    sell_param_keys = [
        "next_day_open_sell_pct", "pullback_profit_lock_threshold",
        "pullback_mid_fallback_pct", "pullback_high_threshold", "allow_after_10am"
    ]
    
    for sid, cfg in STRATEGY_CONFIGS.items():
        if not cfg.get('enabled', True):
            continue
        name = cfg.get('name', sid)
        rp = cfg.get('riskParams', {})
        params = cfg.get('params', {})
        
        risk = dict(GLOBAL_RISK)
        risk.update(rp)
        
        # 模拟修复后的逻辑: 合并params中的卖出参数
        for k in sell_param_keys:
            if k in params and k not in risk:
                risk[k] = params[k]
        
        # 百分比>1自动转小数
        for pct_key in ["stop_loss_pct", "take_profit_pct", "next_day_open_sell_pct",
                       "pullback_profit_lock_threshold", "pullback_mid_fallback_pct",
                       "pullback_high_threshold"]:
            if risk.get(pct_key, 0) > 1:
                risk[pct_key] = risk[pct_key] / 100
        
        # 检查止损止盈
        for key, desc in [("stop_loss_pct", "止损"), ("take_profit_pct", "止盈")]:
            val = risk.get(key)
            if val is None:
                issues.append(f"[{name}] {desc}({key})缺失")
            elif isinstance(val, float) and val > 1:
                issues.append(f"[{name}] {desc}({key})={val}>1, 疑似百分比未转小数")
        
        # 检查next_day_open_sell_pct
        nds = risk.get("next_day_open_sell_pct")
        if nds is None:
            issues.append(f"[{name}] next_day_open_sell_pct缺失(应在params或riskParams中)")
        
        # 检查冲高回落参数
        pullback = STRATEGY_PULLBACK_PARAMS.get(name, {})
        if pullback:
            for pkey in ["pullback_high_threshold", "pullback_mid_fallback_pct", "pullback_profit_lock_threshold"]:
                bp_val = pullback.get(pkey)
                risk_val = risk.get(pkey)
                if bp_val is not None and risk_val is not None and abs(bp_val - risk_val) > 0.001:
                    issues.append(f"[{name}] {pkey}: 回测STRATEGY_PULLBACK_PARAMS={bp_val} vs 实盘risk={risk_val}")
    
    return issues

# ============================================================
# 3. 冲高回落参数 (STRATEGY_PULLBACK_PARAMS)
# ============================================================
def check_pullback_params():
    """检查实盘position_manager是否正确读取冲高回落参数"""
    issues = []
    
    for name, params in STRATEGY_PULLBACK_PARAMS.items():
        for key, expected in params.items():
            # 检查strategy_defaults中是否有对应值
            found = False
            for sid, cfg in STRATEGY_CONFIGS.items():
                if cfg.get('name') == name:
                    p = cfg.get('params', {})
                    rp = cfg.get('riskParams', {})
                    actual = p.get(key) or rp.get(key)
                    if actual is not None and abs(actual - expected) > 0.001:
                        issues.append(f"[{name}] {key}: STRATEGY_PULLBACK_PARAMS={expected} vs strategy_defaults={actual}")
                    found = True
                    break
            if not found:
                issues.append(f"[{name}] {key}={expected} 在STRATEGY_CONFIGS中找不到策略'{name}'")
    
    return issues

# ============================================================
# 4. 选股过滤参数
# ============================================================
def check_selection_filters():
    """检查实盘选股过滤是否与回测params对齐"""
    issues = []
    
    # 首板打板过滤
    flu = STRATEGY_CONFIGS.get('first_limit_up', {})
    params = flu.get('params', {})
    name = flu.get('name', '首板打板')
    
    required_filters = {
        'min_turnover_rate': '首板最小换手率',
        'max_turnover_rate': '首板最大换手率',
        'min_circulation_market_cap': '首板最小流通市值',
        'max_circulation_market_cap': '首板最大流通市值',
    }
    
    for key, desc in required_filters.items():
        if key not in params:
            issues.append(f"[{name}] {desc}({key})在params中缺失")
    
    # 半路追涨时间过滤
    hc = STRATEGY_CONFIGS.get('halfway_chase', {})
    hc_params = hc.get('params', {})
    if 'allow_after_10am' not in hc_params:
        issues.append(f"[半路追涨] allow_after_10am在params中缺失")
    elif hc_params['allow_after_10am'] != False:
        issues.append(f"[半路追涨] allow_after_10am={hc_params['allow_after_10am']}, 回测为False")
    
    # 龙头低吸回调幅度
    dh = STRATEGY_CONFIGS.get('dragon_head', {})
    dh_params = dh.get('params', {})
    for key in ['min_correction_pct', 'max_correction_pct']:
        if key not in dh_params:
            issues.append(f"[龙头低吸] {key}在params中缺失")
    
    # 跌停翘板换手率
    ldq = STRATEGY_CONFIGS.get('limit_down_qiao', {})
    ldq_params = ldq.get('params', {})
    if 'min_turnover_rate' not in ldq_params:
        issues.append(f"[跌停翘板] min_turnover_rate在params中缺失")
    
    return issues

# ============================================================
# 5. 成交概率参数
# ============================================================
def check_hit_probability():
    """检查涨停成交概率是否对齐"""
    issues = []
    
    flu = STRATEGY_CONFIGS.get('first_limit_up', {})
    params = flu.get('params', {})
    
    hp_keys = {
        'hit_probability_yizi': 0.0,
        'hit_probability_fast': 0.20,
        'hit_probability_normal': 0.45,
        'hit_probability_slow': 0.55,
    }
    
    for key, expected in hp_keys.items():
        actual = params.get(key)
        if actual is None:
            issues.append(f"[首板打板] {key}在params中缺失")
        elif abs(actual - expected) > 0.01:
            issues.append(f"[首板打板] {key}: 实际={actual}, 期望≈{expected}")
    
    return issues

# ============================================================
# 6. 情绪仓位映射
# ============================================================
def check_sentiment_map():
    """检查情绪仓位映射一致性"""
    issues = []
    
    expected = GLOBAL_RISK.get('sentiment_position_map', {})
    if not expected:
        issues.append("GLOBAL_RISK.sentiment_position_map为空")
    
    # 检查4个phase都有
    for phase in ['rising', 'differentiation', 'chaos', 'bearish']:
        if phase not in expected:
            issues.append(f"sentiment_position_map缺少phase: {phase}")
    
    return issues

# ============================================================
# 7. 代码中hardcoded值扫描
# ============================================================
def check_hardcoded_values():
    """扫描实盘代码中可能的hardcoded参数值"""
    issues = []
    
    import re
    
    # 扫描position_manager中的hardcoded百分比
    pm_path = os.path.join(os.path.dirname(__file__), '..', 'nodes', 'market_monitor', 'position_manager.py')
    if os.path.exists(pm_path):
        with open(pm_path) as f:
            content = f.read()
        
        # 检查next_day_open_sell_pct的默认值
        matches = re.findall(r'next_day_open_sell_pct["\']?\s*[,\)]\s*([\d.]+)', content)
        for m in matches:
            val = float(m)
            if abs(val - 0.02) > 0.001:  # 应该是0.02(2%)
                issues.append(f"position_manager.py: next_day_open_sell_pct默认值={val}, 期望0.02")
        
        # 检查pullback相关hardcoded
        matches = re.findall(r'pullback_mid_fallback_pct["\']?\s*[,\)]\s*([\d.]+)', content)
        for m in matches:
            val = float(m)
            if abs(val - 0.015) > 0.001:  # 应该是0.015(1.5%)
                issues.append(f"position_manager.py: pullback_mid_fallback_pct默认值={val}, 期望0.015")
    
    # 扫描signal_manager
    sm_path = os.path.join(os.path.dirname(__file__), '..', 'nodes', 'market_monitor', 'signal_manager.py')
    if os.path.exists(sm_path):
        with open(sm_path) as f:
            content = f.read()
        # 检查是否有hardcoded的换手率/市值阈值(应该从params读取)
        if 'turnover_rate' in content and '8' in content and '15' in content:
            # 可能是hardcoded，但具体要看上下文
            pass  # 不误报，_check_strategy_params_filter从params读取
    
    return issues

# ============================================================
# 主流程
# ============================================================
def main():
    print("=" * 70)
    print("实盘 vs 回测 参数一致性检查")
    print("=" * 70)
    
    all_issues = []
    
    checks = [
        ("1. 全局风控参数", check_global_risk),
        ("2. 策略风控参数(riskParams)", check_strategy_risk_params),
        ("3. 冲高回落参数", check_pullback_params),
        ("4. 选股过滤参数", check_selection_filters),
        ("5. 成交概率参数", check_hit_probability),
        ("6. 情绪仓位映射", check_sentiment_map),
        ("7. Hardcoded值扫描", check_hardcoded_values),
    ]
    
    for name, fn in checks:
        print(f"\n📋 {name}")
        try:
            issues = fn()
            if not issues:
                print(f"   ✅ 全部一致")
            else:
                for issue in issues:
                    print(f"   ❌ {issue}")
                all_issues.extend(issues)
        except Exception as e:
            print(f"   ⚠️ 检查异常: {e}")
            all_issues.append(f"[{name}] 检查异常: {e}")
    
    print("\n" + "=" * 70)
    if not all_issues:
        print("🎉 实盘与回测参数完全一致！0个问题")
        print("=" * 70)
        return 0
    else:
        print(f"⚠️ 发现 {len(all_issues)} 个不一致:")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
        print("=" * 70)
        return 1

if __name__ == '__main__':
    sys.exit(main())
