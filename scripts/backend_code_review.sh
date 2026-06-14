#!/usr/bin/env bash
# =====================================================================
# 后端代码审查 — 夜间DAG
#
# 专门检查 scanner/broker/persistence 层的常见bug模式
# 基于 v2.9.92s 的"100万反复出现"教训
#
# 检查项:
#   1. self.positions 属性访问(应改为 self.get_positions())
#   2. broker.save_state() 无 skip_if_virtual 参数
#   3. MarketScanner.__getattr__ 拦截后的属性误访问
#   4. replay/dry_run 模式写入 MongoDB 的风险
#   5. scanner未运行时的数据回退是否完整
# =====================================================================

set -euo pipefail

BACKEND_DIR="${1:-./AgentServer}"
REPORT_FILE="${2:-/tmp/backend-code-review.md}"
ISSUES=0

echo "# 后端代码审查报告" > "$REPORT_FILE"
echo "生成时间: $(date '+%Y-%m-%d %H:%M:%S')" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

check() {
    local level="$1"  # 🔴 高风险 / 🟡 中风险 / 🟢 建议优化
    local desc="$2"
    local file="$3"
    local pattern="$4"
    
    local matches
    matches=$(grep -rn "$pattern" "$file" 2>/dev/null || true)
    
    if [ -n "$matches" ]; then
        echo "" >> "$REPORT_FILE"
        echo "## $level $desc" >> "$REPORT_FILE"
        echo "模式: \`$pattern\`" >> "$REPORT_FILE"
        echo '```' >> "$REPORT_FILE"
        echo "$matches" >> "$REPORT_FILE"
        echo '```' >> "$REPORT_FILE"
        ISSUES=$((ISSUES + 1))
    fi
}

# ============================================================
# 1. self.positions 属性访问(应改为 self.get_positions())
# ============================================================
check "🔴" \
    "self.positions 直接属性访问 — MarketScanner没有positions属性，只有get_positions()方法" \
    "$BACKEND_DIR/nodes/market_monitor/scanner.py" \
    'self\.positions[^_]'

# broker.py 中的 self.positions 是合法的(SimulatedBroker有positions属性)
# 但仍需检查是否在错误的上下文中使用

# ============================================================
# 2. broker.save_state() 无 skip_if_virtual 参数
# ============================================================
check "🔴" \
    "broker.save_state() 未传 skip_if_virtual — replay/dry_run模式可能覆盖实盘数据" \
    "$BACKEND_DIR/nodes/market_monitor" \
    'save_state([^)]*force[^)]*)' \
    | grep -v 'skip_if_virtual'

# ============================================================
# 3. scanner直接属性访问(可能被__getattr__拦截)
# ============================================================
check "🟡" \
    "scanner直接属性访问(未用hasattr保护) — __getattr__会抛AttributeError" \
    "$BACKEND_DIR/nodes/web/api/scanner_core.py" \
    'scanner\._[a-z_]+[^=]'

# ============================================================
# 4. replay/dry_run 写入 MongoDB 的风险
# ============================================================
check "🔴" \
    "replay/dry_run 模式可能的MongoDB写入 — 应加is_virtual检查" \
    "$BACKEND_DIR/nodes/market_monitor" \
    'mongo_manager\.db\|_mongo_db\.\|update_one\|insert_one\|delete_many'

# ============================================================
# 5. stop/暂停/cleanup中的异常处理
# ============================================================
check "🟡" \
    "stop/cleanup中的裸属性访问 — stop失败=前端卡死，必须try/catch" \
    "$BACKEND_DIR/nodes/market_monitor/scanner.py" \
    'async def stop\|async def _stop_cleanup\|async def _persist'

# ============================================================
# 汇总
# ============================================================
echo "" >> "$REPORT_FILE"
echo "---" >> "$REPORT_FILE"
echo "总问题数: $ISSUES" >> "$REPORT_FILE"

echo "后端审查完成: $ISSUES 个问题 → $REPORT_FILE"
cat "$REPORT_FILE"
