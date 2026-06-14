#!/usr/bin/env bash
# =====================================================================
# 前端代码静态审查 — 夜间DAG Phase 16
#
# 检查项:
#   1. 注释占位符 (如 if(xxx) { /* 触发xxx */ } 没有实际代码)
#   2. TODO/HACK/FIXME/XXX 残留
#   3. console.log 遗留 (非error/warn)
#   4. 死代码: debugger / if(false)
#   5. 硬编码URL/IP (非localhost/cdn)
#   6. ref声明但可能未使用
# =====================================================================

set -euo pipefail

FRONTEND_DIR="${1:-./frontend/src}"
REPORT_FILE="${2:-/tmp/frontend-code-review.md}"
ISSUES=0

echo "# 前端代码静态审查报告" > "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "扫描目录: \`$FRONTEND_DIR\`" >> "$REPORT_FILE"
echo "扫描时间: $(date '+%Y-%m-%d %H:%M:%S')" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# =====================================================================
# 1. 注释占位符 — 真正的空实现
#     排除合法的: catch { /* ignore */ } / CSS注释 / watch回调
# =====================================================================
echo "## 1. 注释占位符 (空实现)" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

count=0
# 找 if/else/=> { /* xxx */ } 但不含 .value = / return / await / emit / .push / router
while IFS= read -r line; do
    file=$(echo "$line" | cut -d: -f1)
    lineno=$(echo "$line" | cut -d: -f2)
    content=$(echo "$line" | cut -d: -f3-)
    # 排除合法模式
    if echo "$content" | grep -qE '\.value\s*=|return\s|await\s|emit\(|\.push\(|router\.|ElMessage|\.post\(|\.get\('; then
        continue
    fi
    # 排除catch块(ignore/fallback是合法的)
    if echo "$content" | grep -qE 'catch.*\{.*(/\* ignore \*/|/\* fallback \*/|/\* cancelled \*/|/\* poll errors \*/)'; then
        continue
    fi
    # 排除CSS注释
    if echo "$content" | grep -qE '\{ /\*.*\*/ \}$' && echo "$content" | grep -qE '^\s*\.'; then
        continue
    fi
    # 排除watch回调中的CSS变量传播注释
    if echo "$content" | grep -qE 'watch\(.*\{ /\*.*propagat'; then
        continue
    fi
    echo "- \`${file##*/}:${lineno}\` — ⚠️ ${content}" >> "$REPORT_FILE"
    ((count++)) || true
done < <(grep -rn '{ /\*.*\*/ }' "$FRONTEND_DIR" --include="*.ts" --include="*.vue" 2>/dev/null || true)

# 额外检查: 箭头函数体只有注释
while IFS= read -r line; do
    file=$(echo "$line" | cut -d: -f1)
    lineno=$(echo "$line" | cut -d: -f2)
    content=$(echo "$line" | cut -d: -f3-)
    # 必须是 const xxx = () => { /* 注释 */ } 模式
    if echo "$content" | grep -qE 'const \w+ = \(\) => \{ /\*.*\*/ \}'; then
        if ! echo "$content" | grep -qE '由.*实现|delegate|forward'; then
            echo "- \`${file##*/}:${lineno}\` — ⚠️ 空箭头函数: ${content}" >> "$REPORT_FILE"
            ((count++)) || true
        fi
    fi
done < <(grep -rn 'const \w\+ = () => { /\*.*\*/ }' "$FRONTEND_DIR" --include="*.ts" --include="*.vue" 2>/dev/null || true)

if [ "$count" -eq 0 ]; then
    echo "✅ 无注释占位符/空实现" >> "$REPORT_FILE"
else
    echo "" >> "$REPORT_FILE"
    echo "**发现 ${count} 处需确认**" >> "$REPORT_FILE"
    ISSUES=$((ISSUES + count))
fi
echo "" >> "$REPORT_FILE"

# =====================================================================
# 2. TODO/HACK/FIXME/XXX 残留
# =====================================================================
echo "## 2. TODO/HACK/FIXME/XXX 残留" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

count=0
while IFS= read -r line; do
    file=$(echo "$line" | cut -d: -f1)
    lineno=$(echo "$line" | cut -d: -f2)
    content=$(echo "$line" | cut -d: -f3-)
    echo "- \`${file##*/}:${lineno}\` — ${content}" >> "$REPORT_FILE"
    ((count++)) || true
done < <(grep -rn 'TODO\|HACK\|FIXME\|XXX' "$FRONTEND_DIR" --include="*.ts" --include="*.vue" 2>/dev/null | grep -v node_modules | grep -v '.d.ts' || true)

if [ "$count" -eq 0 ]; then
    echo "✅ 无TODO/FIXME残留" >> "$REPORT_FILE"
else
    echo "" >> "$REPORT_FILE"
    echo "**发现 ${count} 处**" >> "$REPORT_FILE"
fi
echo "" >> "$REPORT_FILE"

# =====================================================================
# 3. console.log 遗留
# =====================================================================
echo "## 3. console.log 遗留" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

count=0
while IFS= read -r line; do
    file=$(echo "$line" | cut -d: -f1)
    lineno=$(echo "$line" | cut -d: -f2)
    content=$(echo "$line" | cut -d: -f3-)
    echo "- \`${file##*/}:${lineno}\` — ${content}" >> "$REPORT_FILE"
    ((count++)) || true
done < <(grep -rn 'console\.log(' "$FRONTEND_DIR" --include="*.ts" --include="*.vue" 2>/dev/null | grep -v '// console' || true)

if [ "$count" -eq 0 ]; then
    echo "✅ 无console.log遗留" >> "$REPORT_FILE"
else
    echo "" >> "$REPORT_FILE"
    echo "**发现 ${count} 处** (建议替换为条件日志)" >> "$REPORT_FILE"
fi
echo "" >> "$REPORT_FILE"

# =====================================================================
# 4. 死代码
# =====================================================================
echo "## 4. 死代码 (debugger / if(false))" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

count=0
while IFS= read -r line; do
    file=$(echo "$line" | cut -d: -f1)
    lineno=$(echo "$line" | cut -d: -f2)
    content=$(echo "$line" | cut -d: -f3-)
    echo "- \`${file##*/}:${lineno}\` — ${content}" >> "$REPORT_FILE"
    ((count++)) || true
done < <(grep -rn '^\s*debugger\b\|if\s*(\s*false\s*)' "$FRONTEND_DIR" --include="*.ts" --include="*.vue" 2>/dev/null || true)

if [ "$count" -eq 0 ]; then
    echo "✅ 无死代码" >> "$REPORT_FILE"
else
    echo "" >> "$REPORT_FILE"
    echo "**发现 ${count} 处**" >> "$REPORT_FILE"
    ISSUES=$((ISSUES + count))
fi
echo "" >> "$REPORT_FILE"

# =====================================================================
# 5. 硬编码URL/IP
# =====================================================================
echo "## 5. 硬编码URL/IP" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

count=0
while IFS= read -r line; do
    file=$(echo "$line" | cut -d: -f1)
    lineno=$(echo "$line" | cut -d: -f2)
    content=$(echo "$line" | cut -d: -f3-)
    if ! echo "$content" | grep -qE 'localhost|127\.0\.0\.1|0\.0\.0\.0|import\.meta'; then
        echo "- \`${file##*/}:${lineno}\` — ${content}" >> "$REPORT_FILE"
        ((count++)) || true
    fi
done < <(grep -rn 'http://\|https://' "$FRONTEND_DIR" --include="*.ts" --include="*.vue" 2>/dev/null | grep -vE 'node_modules|\.d\.ts|github\.com|discord\.com|feishu\.cn|openclaw\.ai|cdn\.|unpkg\.|jsdelivr\.' || true)

if [ "$count" -eq 0 ]; then
    echo "✅ 无硬编码URL" >> "$REPORT_FILE"
else
    echo "" >> "$REPORT_FILE"
    echo "**发现 ${count} 处** (需确认)" >> "$REPORT_FILE"
fi
echo "" >> "$REPORT_FILE"

# =====================================================================
# 6. ref声明但可能未使用
# =====================================================================
echo "## 6. ref/computed 声明但可能未使用" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "注意: 假阳性较高，仅供参考" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

count=0
for f in $(find "$FRONTEND_DIR" -name "*.ts" -not -name "*.d.ts" -not -path "*/node_modules/*"); do
    while IFS= read -r decl; do
        varname=$(echo "$decl" | grep -oP 'const\s+\K\w+' | head -1)
        if [ -n "$varname" ]; then
            usage_count=$(grep -c "\b${varname}\b" "$f" 2>/dev/null || echo "0")
            if [ "$usage_count" -le 1 ]; then
                lineno=$(grep -n "const ${varname}" "$f" | head -1 | cut -d: -f1)
                echo "- \`${f##*/}:${lineno}\` — \`${varname}\` 只引用${usage_count}次" >> "$REPORT_FILE"
                ((count++)) || true
            fi
        fi
    done < <(grep -n 'const \w\+ = ref(' "$f" 2>/dev/null | head -5 || true)
done

if [ "$count" -eq 0 ]; then
    echo "✅ 无明显未使用ref" >> "$REPORT_FILE"
else
    echo "" >> "$REPORT_FILE"
    echo "**发现 ${count} 处疑似**" >> "$REPORT_FILE"
fi
echo "" >> "$REPORT_FILE"

# =====================================================================
# 总结
# =====================================================================
echo "---" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "## 总结" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

if [ "$ISSUES" -eq 0 ]; then
    echo "✅ 前端代码静态审查通过" >> "$REPORT_FILE"
    echo "PASSED"
    exit 0
else
    echo "⚠️ 发现 **${ISSUES}** 个需关注问题" >> "$REPORT_FILE"
    echo "FAILED"
    exit 1
fi
