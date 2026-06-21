#!/bin/bash
# ================================================================
# Frontend Preflight Check - 防御性检查脚本
# 
# 在 vite build 之前运行, 拦截三类已知问题:
# 1. 未定义变量引用 (ReferenceError)
# 2. 静默catch (catch {} / catch { /* ignore */ })
# 3. 时区不一致 (new Date().getHours() 而非 china.getHours())
#
# 使用: bash scripts/preflight-check.sh
# ================================================================

set -euo pipefail
SRC_DIR="src"
ERRORS=0

echo "🔍 Frontend Preflight Check"
echo "============================"

# ---------------------------------------------------------------
# Check 1: 静默catch - catch块内没有任何语句
# ---------------------------------------------------------------
echo ""
echo "📋 Check 1: 静默catch (catch {} / catch { /* ignore */ })"
SILENT_CATCHES=$(grep -rn 'catch\s*{\s*\(/\*.*\*/\)\?\s*}' "$SRC_DIR" --include="*.ts" --include="*.vue" 2>/dev/null || true)
if [ -n "$SILENT_CATCHES" ]; then
    COUNT=$(echo "$SILENT_CATCHES" | wc -l)
    echo "   ❌ 发现 $COUNT 处静默catch (应改为 console.error/warn):"
    echo "$SILENT_CATCHES" | head -10 | sed 's/^/      /'
    if [ "$COUNT" -gt 10 ]; then echo "      ... (仅显示前10条)"; fi
    ERRORS=$((ERRORS + COUNT))
else
    echo "   ✅ 无静默catch"
fi

# ---------------------------------------------------------------
# Check 2: 时区风险 - 直接用 new Date().getHours() 等
# ---------------------------------------------------------------
echo ""
echo "📋 Check 2: 时区风险 (未使用中国时区的 getHours/getMinutes/getDay)"
# 匹配: now.getHours() 或 n.getHours() 等，但不匹配 china.getHours() 或 now2.getHours()
TZ_RISKS=$(grep -rn '\.\(getHours\|getMinutes\|getDay\|getMonth\|getDate\)()' "$SRC_DIR" --include="*.ts" --include="*.vue" 2>/dev/null \
    | grep -v 'china\.\|now2\.\|china2\.\|d2\.\|date2\.\|toLocaleString\|getHours() >\|// .*timezone\|// .*时区' \
    || true)
if [ -n "$TZ_RISKS" ]; then
    COUNT=$(echo "$TZ_RISKS" | wc -l)
    echo "   ⚠️  发现 $COUNT 处可能未使用中国时区:"
    echo "$TZ_RISKS" | head -10 | sed 's/^/      /'
    if [ "$COUNT" -gt 10 ]; then echo "      ... (仅显示前10条)"; fi
    ERRORS=$((ERRORS + COUNT))
else
    echo "   ✅ 无时区风险"
fi

# ---------------------------------------------------------------
# Check 3: toISOString() 用于日期格式化 (UTC偏移风险)
# ---------------------------------------------------------------
echo ""
echo "📋 Check 3: toISOString() 时区偏移风险"
ISO_RISKS=$(grep -rn '\.toISOString()\.slice\|\.toISOString()\.substring' "$SRC_DIR" --include="*.ts" --include="*.vue" 2>/dev/null \
    | grep -v '// .*UTC\|// .*timezone\|// .*时区' \
    || true)
if [ -n "$ISO_RISKS" ]; then
    COUNT=$(echo "$ISO_RISKS" | wc -l)
    echo "   ⚠️  发现 $COUNT 处 toISOString() 用于日期格式化 (UTC+8凌晨会偏移一天):"
    echo "$ISO_RISKS" | head -10 | sed 's/^/      /'
    ERRORS=$((ERRORS + COUNT))
else
    echo "   ✅ 无toISOString()风险"
fi

# ---------------------------------------------------------------
# Check 4: 变量重命名遗漏 (heuristic: find variable used but not declared in same function)
# ---------------------------------------------------------------
echo ""
echo "📋 Check 4: TypeScript编译检查"
COMPILE_RESULT=$(npx vue-tsc --noEmit 2>&1 || true)
if echo "$COMPILE_RESULT" | grep -q "error TS"; then
    ERROR_COUNT=$(echo "$COMPILE_RESULT" | grep -c "error TS" || true)
    echo "   ❌ TypeScript编译发现 $ERROR_COUNT 个错误:"
    echo "$COMPILE_RESULT" | grep "error TS" | head -10 | sed 's/^/      /'
    ERRORS=$((ERRORS + ERROR_COUNT))
else
    echo "   ✅ TypeScript编译无错误"
fi

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
echo ""
echo "============================"
if [ "$ERRORS" -gt 0 ]; then
    echo "❌ Preflight check 发现 $ERRORS 个问题, 请修复后再构建"
    exit 1
else
    echo "✅ Preflight check 全部通过"
    exit 0
fi
