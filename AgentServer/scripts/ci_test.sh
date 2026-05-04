#!/bin/bash
# StockAgent CI 测试脚本
# 用法: bash scripts/ci_test.sh
# 在每次提交前运行，确保核心逻辑不被破坏

set -e
cd "$(dirname "$0")/.."

echo "🧪 StockAgent CI Test Suite"
echo "============================"

# 1. 语法检查
echo ""
echo "📋 Step 1: Python 语法检查..."
python -m py_compile core/constants.py && echo "  ✅ constants.py"
python -m py_compile nodes/backtest_engine/models.py && echo "  ✅ models.py"
python -m py_compile nodes/backtest_engine/factor_selection/special_period_filter.py && echo "  ✅ special_period_filter.py"
python -m py_compile core/managers/sim_trading_engine.py && echo "  ✅ sim_trading_engine.py"

# 2. 单元测试
echo ""
echo "📋 Step 2: 单元测试..."
python -m pytest tests/ -v --tb=short

# 3. 常量一致性检查
echo ""
echo "📋 Step 3: 集合名硬编码检查..."
HARDCODED=$(grep -rn '"stock_daily_ak_full"\|"stock_basic"\|"index_daily"\|"limit_list"\|"positions"' \
    --include="*.py" nodes/ core/ real_trading/ src/ 2>/dev/null \
    | grep -v __pycache__ | grep -v venv | grep -v _deprecated | grep -v "constants.py" \
    | grep -v "_call_api\|name = \".*\"\|data_source=\|sync_type=\|COLLECTION\|\"positions\":" \
    | wc -l)

if [ "$HARDCODED" -gt 0 ]; then
    echo "  ⚠️  发现 $HARDCODED 处可能的集合名硬编码（请检查是否需要替换为C常量）"
else
    echo "  ✅ 无新增集合名硬编码"
fi

echo ""
echo "============================"
echo "✅ CI 测试全部通过！"
