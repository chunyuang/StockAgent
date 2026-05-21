#!/bin/bash
# ============================================================
# 回测代码提交前检查脚本
# 用法: bash pre_commit_check.sh [--quick]
# --quick: 只跑语法检查+参数一致性,不跑回测
#
# 解决的问题:
# - V10-V28中语法错误/参数遗漏/elif链bug等多次上线后才发现
# - 每次修改后必须跑的检查自动化,防止审查引入新bug
#
# 版本: V29
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="$SCRIPT_DIR/factor_selection"
SHARED_DIR="$SCRIPT_DIR"
PYTHON_PATH="$ENGINE_DIR:$SHARED_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

echo "📁 引擎目录: $ENGINE_DIR"
echo "📁 共享目录: $SHARED_DIR"

# ============================================================
# 1. 语法检查
# ============================================================
echo ""
echo "=========================================="
echo "1️⃣  语法检查"
echo "=========================================="

check_file="$SHARED_DIR/factor_selection/portfolio_backtest.py"
if [ -f "$check_file" ]; then
    if python3 -m py_compile "$check_file" 2>/dev/null; then
        echo -e "  ${GREEN}✅${NC} portfolio_backtest.py"
    else
        echo -e "  ${RED}❌${NC} portfolio_backtest.py — 语法错误!"
        python3 -m py_compile "$check_file" 2>&1 | head -5
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "  ${YELLOW}⚠️${NC} portfolio_backtest.py — 文件不存在"
fi

for fname in ultra_short.py strategy_defaults.py; do
    check_file="$SHARED_DIR/$fname"
    if [ -f "$check_file" ]; then
        if python3 -m py_compile "$check_file" 2>/dev/null; then
            echo -e "  ${GREEN}✅${NC} $fname"
        else
            echo -e "  ${RED}❌${NC} $fname — 语法错误!"
            python3 -m py_compile "$check_file" 2>&1 | head -5
            ERRORS=$((ERRORS + 1))
        fi
    else
        echo -e "  ${YELLOW}⚠️${NC} $fname — 文件不存在"
    fi
done

for fname in factor_engine.py sell_signal_checker.py; do
    check_file="$ENGINE_DIR/$fname"
    if [ -f "$check_file" ]; then
        if python3 -m py_compile "$check_file" 2>/dev/null; then
            echo -e "  ${GREEN}✅${NC} $fname"
        else
            echo -e "  ${RED}❌${NC} $fname — 语法错误!"
            python3 -m py_compile "$check_file" 2>&1 | head -5
            ERRORS=$((ERRORS + 1))
        fi
    else
        echo -e "  ${YELLOW}⚠️${NC} $fname — 文件不存在"
    fi
done

if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}语法检查失败,修复后再继续${NC}"
    exit 1
fi

# ============================================================
# 2. 策略参数一致性检查
# ============================================================
echo ""
echo "=========================================="
echo "2️⃣  策略参数一致性检查"
echo "=========================================="

python3 -c "
import sys
sys.path.insert(0, '$ENGINE_DIR')
sys.path.insert(0, '$SHARED_DIR')
from strategy_defaults import STRATEGY_CONFIGS, ALL_STRATEGIES, GLOBAL_RISK

errors = []

# 检查1: 每个enabled策略必须有完整的riskParams
required_risk_keys = ['stop_loss_pct', 'take_profit_pct', 'max_hold_days', 'slippage_pct']
for sid, cfg in STRATEGY_CONFIGS.items():
    if not cfg.get('enabled', True):
        continue
    rp = cfg.get('riskParams', {})
    for key in required_risk_keys:
        if key not in rp:
            errors.append(f'{sid} 缺少 riskParams.{key}')

# 检查2: 每个enabled策略必须有next_day_open_sell_pct(冲高回落参数)
for sid, cfg in STRATEGY_CONFIGS.items():
    if not cfg.get('enabled', True):
        continue
    params = cfg.get('params', {})
    # 龙头低吸/半路追涨/跌停翘板都需要冲高回落参数
    if sid in ['halfway_chase', 'dragon_head', 'limit_down_qiao']:
        if 'next_day_open_sell_pct' not in params:
            errors.append(f'{sid} 缺少 next_day_open_sell_pct (冲高回落必需)')

# 检查3: ALL_STRATEGIES只包含enabled的策略
enabled_ids = {sid for sid, cfg in STRATEGY_CONFIGS.items() if cfg.get('enabled', True)}
all_ids = {s['id'] for s in ALL_STRATEGIES}
if enabled_ids != all_ids:
    errors.append(f'ALL_STRATEGIES与enabled策略不一致: 缺少={enabled_ids-all_ids}, 多余={all_ids-enabled_ids}')

# 检查4: 止损比例合理性
for sid, cfg in STRATEGY_CONFIGS.items():
    rp = cfg.get('riskParams', {})
    sl = rp.get('stop_loss_pct', 0)
    tp = rp.get('take_profit_pct', 0)
    if sl <= 0 or sl > 0.15:
        errors.append(f'{sid} 止损比例异常: {sl*100:.1f}%')
    if tp <= 0 or tp > 0.50:
        errors.append(f'{sid} 止盈比例异常: {tp*100:.1f}%')
    if tp <= sl:
        errors.append(f'{sid} 止盈≤止损: SL={sl*100:.1f}% TP={tp*100:.1f}%')

# 检查5: max_hold_days合理性
for sid, cfg in STRATEGY_CONFIGS.items():
    rp = cfg.get('riskParams', {})
    mhd = rp.get('max_hold_days', 0)
    if mhd <= 0 or mhd > 30:
        errors.append(f'{sid} max_hold_days异常: {mhd}')

if errors:
    for e in errors:
        print(f'  ❌ {e}')
    sys.exit(1)
else:
    print('  ✅ 所有enabled策略参数完整且合理')
" || {
    echo -e "  ${RED}策略参数一致性检查失败${NC}"
    ERRORS=$((ERRORS + 1))
}

# ============================================================
# 3. 卖出信号完整性检查
# ============================================================
echo ""
echo "=========================================="
echo "3️⃣  卖出信号完整性检查"
echo "=========================================="

python3 -c "
import sys
sys.path.insert(0, '$ENGINE_DIR')
sys.path.insert(0, '$SHARED_DIR')
from strategy_defaults import STRATEGY_CONFIGS
from sell_signal_checker import STRATEGY_SELL_SIGNALS, SLIPPAGE_RULES, should_apply_slippage

errors = []

# 检查1: 每个enabled策略必须在STRATEGY_SELL_SIGNALS中注册
for sid, cfg in STRATEGY_CONFIGS.items():
    name = cfg.get('name', sid)
    if not cfg.get('enabled', True):
        continue
    if name not in STRATEGY_SELL_SIGNALS:
        errors.append(f'策略 \"{name}\" 未在STRATEGY_SELL_SIGNALS中注册')

# 检查2: 有冲高回落信号的策略必须在STRATEGY_PULLBACK_PARAMS中
from sell_signal_checker import STRATEGY_PULLBACK_PARAMS, SellSignal
for name, signals in STRATEGY_SELL_SIGNALS.items():
    has_pullback = any(s.name == '冲高回落' for s in signals)
    if has_pullback and name not in STRATEGY_PULLBACK_PARAMS:
        errors.append(f'策略 \"{name}\" 有冲高回落信号但未在STRATEGY_PULLBACK_PARAMS中注册')

# 检查3: 滑点规则覆盖所有已知卖出原因
known_reasons = ['冲高回落', '利润保护', '高开即卖', '止损', '跳空止损', '止盈', '超时', '强制空仓', '停牌超时强卖', '调仓卖出', '减仓']
for reason in known_reasons:
    result = should_apply_slippage(reason)
    if reason not in SLIPPAGE_RULES:
        errors.append(f'卖出原因 \"{reason}\" 未在SLIPPAGE_RULES中定义')

# 检查4: 止损不扣滑点,止盈扣滑点(核心规则)
if should_apply_slippage('止损') != False:
    errors.append('核心规则违反: 止损应该不扣滑点')
if should_apply_slippage('跳空止损') != False:
    errors.append('核心规则违反: 跳空止损应该不扣滑点')
if should_apply_slippage('超时') != False:
    errors.append('核心规则违反: 超时应该不扣滑点')
if should_apply_slippage('冲高回落') != True:
    errors.append('核心规则违反: 冲高回落应该扣滑点')
if should_apply_slippage('利润保护') != True:
    errors.append('核心规则违反: 利润保护应该扣滑点')
if should_apply_slippage('止盈') != True:
    errors.append('核心规则违反: 止盈应该扣滑点')

# 检查5: 带参数的reason也能正确匹配
if should_apply_slippage('止损(5%)') != False:
    errors.append('前缀匹配失败: 止损(5%)应该不扣滑点')
if should_apply_slippage('超时(3交易日>2交易日)') != False:
    errors.append('前缀匹配失败: 超时(3交易日>2交易日)应该不扣滑点')
if should_apply_slippage('止盈(12%)') != True:
    errors.append('前缀匹配失败: 止盈(12%)应该扣滑点')

if errors:
    for e in errors:
        print(f'  ❌ {e}')
    sys.exit(1)
else:
    print('  ✅ 卖出信号和滑点规则完整且正确')
" || {
    echo -e "  ${RED}卖出信号完整性检查失败${NC}"
    ERRORS=$((ERRORS + 1))
}

# ============================================================
# 4. 危险代码模式检测
# ============================================================
echo ""
echo "=========================================="
echo "4️⃣  危险代码模式检测"
echo "=========================================="

PB_FILE="$ENGINE_DIR/portfolio_backtest.py"

# 4.1 检查elif链(卖出信号中不应使用elif)
# 排除: 注释行、reason分支(elif xxx.startswith)
echo "  🔍 检查卖出信号中的elif链..."
if [ -f "$PB_FILE" ]; then
    # 检查_check_early_sell_signals方法内是否有策略名elif链(即elif sname ==)
    ELIF_ISSUES=$(grep -n "elif sname ==" "$PB_FILE" 2>/dev/null | head -5)
    if [ -n "$ELIF_ISSUES" ]; then
        echo -e "  ${RED}❌ 发现策略elif链! 应改为数据驱动检查${NC}"
        echo "$ELIF_ISSUES"
        ERRORS=$((ERRORS + 1))
    else
        echo -e "  ${GREEN}✅${NC} 未发现策略elif链"
    fi
else
    echo -e "  ${YELLOW}⚠️${NC} portfolio_backtest.py不存在,跳过"
fi

# 4.2 检查硬编码卖出参数
echo "  🔍 检查硬编码卖出参数..."
if [ -f "$PB_FILE" ]; then
    if grep -n "0\.03.*冲高回落\|0\.05.*冲高回落" "$PB_FILE" 2>/dev/null | grep -v "params\|sp\.\|_open_sell_pct\|config\|#\|注释\|默认" | head -5; then
        echo -e "  ${YELLOW}⚠️${NC} 发现可能的硬编码冲高回落参数,建议从strategy_defaults读取"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "  ${GREEN}✅${NC} 未发现硬编码卖出参数"
    fi
fi

# 4.3 检查sell_codes后是否有target_shares移除
echo "  🔍 检查卖出后target_shares移除..."
if [ -f "$PB_FILE" ]; then
    if grep -q "sell_code_reasons" "$PB_FILE" 2>/dev/null; then
        if ! grep -q "del target_shares\[" "$PB_FILE" 2>/dev/null; then
            echo -e "  ${RED}❌ sell_code_reasons存在但未找到 del target_shares — 可能存在震荡bug${NC}"
            ERRORS=$((ERRORS + 1))
        else
            echo -e "  ${GREEN}✅${NC} 卖出后有target_shares移除"
        fi
    else
        echo -e "  ${GREEN}✅${NC} (无需检查:未使用sell_code_reasons)"
    fi
fi

# 4.4 检查pct_chg未来函数
echo "  🔍 检查pct_chg使用..."
if [ -f "$PB_FILE" ]; then
    if grep -n "pct_chg" "$PB_FILE" 2>/dev/null | grep -v "#\|注释\|_prev\|未来函数\|known_future\|close_rise" | head -3; then
        echo -e "  ${YELLOW}⚠️${NC} 发现pct_chg使用 — 确认是否有_prev降级方案(V18已知未来函数)${NC}"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "  ${GREEN}✅${NC} 未发现新的pct_chg使用"
    fi
fi

# 4.5 检查滑点判断是否统一
echo "  🔍 检查滑点判断散落..."
if [ -f "$PB_FILE" ]; then
    SLIPPAGE_COUNT=$(grep -c "slippage_pct = 0" "$PB_FILE" 2>/dev/null || echo 0)
    if [ "$SLIPPAGE_COUNT" -gt 3 ]; then
        echo -e "  ${YELLOW}⚠️${NC} 发现${SLIPPAGE_COUNT}处 slippage_pct=0 硬编码 — 建议统一用sell_signal_checker.apply_slippage()${NC}"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "  ${GREEN}✅${NC} 滑点判断处数合理(${SLIPPAGE_COUNT}处)"
    fi
fi

# ============================================================
# 5. 代码行数统计(变化监控)
# ============================================================
echo ""
echo "=========================================="
echo "5️⃣  代码行数统计"
echo "=========================================="

for file_desc in "portfolio_backtest.py:$ENGINE_DIR/portfolio_backtest.py" "ultra_short.py:$SHARED_DIR/ultra_short.py" "factor_engine.py:$ENGINE_DIR/factor_engine.py" "strategy_defaults.py:$SHARED_DIR/strategy_defaults.py" "sell_signal_checker.py:$ENGINE_DIR/sell_signal_checker.py"; do
    fname="${file_desc%%:*}"
    fpath="${file_desc##*:}"
    if [ -f "$fpath" ]; then
        lines=$(wc -l < "$fpath")
        printf "  %-30s %5d 行\n" "$fname" "$lines"
    fi
done

# ============================================================
# 结果汇总
# ============================================================
echo ""
echo "=========================================="
echo "📊 检查结果汇总"
echo "=========================================="

if [ $ERRORS -gt 0 ]; then
    echo -e "  ${RED}❌ 错误: ${ERRORS}${NC}"
    echo -e "  ${YELLOW}⚠️  警告: ${WARNINGS}${NC}"
    echo ""
    echo -e "${RED}🚫 检查未通过! 修复错误后再提交${NC}"
    exit 1
else
    echo -e "  ${GREEN}✅ 错误: 0${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "  ${YELLOW}⚠️  警告: ${WARNINGS}${NC}"
        echo ""
        echo -e "${YELLOW}⚠️  检查通过但有警告,请确认后提交${NC}"
    else
        echo -e "  ${GREEN}✅ 警告: 0${NC}"
        echo ""
        echo -e "${GREEN}🎉 全部检查通过!${NC}"
    fi
fi
