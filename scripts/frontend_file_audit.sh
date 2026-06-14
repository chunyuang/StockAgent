#!/usr/bin/env bash
# =====================================================================
# 前端逐文件代码审计 — Phase 17
#
# 对每个前端文件进行深度审计:
#   - 函数/方法是否都有实际实现
#   - 事件处理是否绑定了实际函数
#   - 条件分支是否都有执行体
#   - API调用是否有错误处理
#   - ref/reactive是否在模板中使用
#
# 输出: 每个文件的审计报告
# =====================================================================

set -euo pipefail

FRONTEND_DIR="${1:-./frontend/src}"
REPORT_FILE="${2:-/tmp/frontend-code-audit.md}"

echo "# 前端逐文件代码审计报告" > "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "审计时间: $(date '+%Y-%m-%d %H:%M:%S')" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

TOTAL_FILES=0
TOTAL_ISSUES=0

# =====================================================================
# 审计单个文件
# =====================================================================
audit_file() {
    local file="$1"
    local basename="${file##*/}"
    local issues=0
    local file_report=""

    # 1. 检查事件处理空实现: @click="xxx" 对应的函数是否存在
    if echo "$basename" | grep -qE '\.vue$'; then
        # 提取模板中引用的函数名
        local template_fns
        template_fns=$(grep -oP '@\w+="(\w+)' "$file" 2>/dev/null | grep -oP '"\K\w+' | sort -u || true)
        
        for fn in $template_fns; do
            # 在script中查找函数定义
            if ! grep -qE "(function\s+${fn}|const\s+${fn}\s*=|${fn}\s*\()" "$file" 2>/dev/null; then
                # 可能在composable中定义
                if ! grep -rqE "(function\s+${fn}|const\s+${fn}\s*=)" "${FRONTEND_DIR}/views/monitor/composables/" --include="*.ts" 2>/dev/null; then
                    if ! grep -rqE "(function\s+${fn}|const\s+${fn}\s*=)" "${FRONTEND_DIR}/views/monitor/useScannerMonitor.ts" 2>/dev/null; then
                        file_report="${file_report}\n- ⚠️ 模板引用 \`@...=\"${fn}\"\` 但函数未定义"
                        ((issues++)) || true
                    fi
                fi
            fi
        done
    fi

    # 2. 检查空箭头函数/空方法体
    local empty_impls
    empty_impls=$(grep -nP '(const \w+ = \(\).*=> \{ *\}|function \w+\(.*\) \{ *\})' "$file" 2>/dev/null || true)
    if [ -n "$empty_impls" ]; then
        while IFS= read -r line; do
            local lineno=$(echo "$line" | cut -d: -f1)
            local content=$(echo "$line" | cut -d: -f3-)
            file_report="${file_report}\n- ⚠️ L${lineno}: 空函数体: \`${content}\`"
            ((issues++)) || true
        done <<< "$empty_impls"
    fi

    # 3. 检查if/else分支只有注释
    local comment_only_branches
    comment_only_branches=$(grep -nP '(if|else if|else)\s*\(.*\)\s*\{\s*/\*' "$file" 2>/dev/null | grep -v 'catch' || true)
    if [ -n "$comment_only_branches" ]; then
        while IFS= read -r line; do
            local lineno=$(echo "$line" | cut -d: -f1)
            local content=$(echo "$line" | cut -d: -f3-)
            # 排除有实际代码的行
            if ! echo "$content" | grep -qE '\.value\s*=|return |await |\.post\(|\.get\('; then
                file_report="${file_report}\n- ⚠️ L${lineno}: 条件分支空实现: \`${content:0:80}\`"
                ((issues++)) || true
            fi
        done <<< "$comment_only_branches"
    fi

    # 4. 检查API调用缺少错误处理(try/catch)
    local api_calls_no_catch
    api_calls_no_catch=$(grep -nP 'await\s+api\.(get|post|put|delete)' "$file" 2>/dev/null | while IFS= read -r line; do
        local lineno=$(echo "$line" | cut -d: -f1)
        # 检查上下文是否有try
        local context
        context=$(sed -n "$((lineno-5)),$((lineno+5))p" "$file" 2>/dev/null || true)
        if ! echo "$context" | grep -q 'try\s*{' && ! echo "$context" | grep -q 'catch'; then
            echo "$line"
        fi
    done || true)
    
    if [ -n "$api_calls_no_catch" ]; then
        while IFS= read -r line; do
            local lineno=$(echo "$line" | cut -d: -f1)
            local content=$(echo "$line" | cut -d: -f3-)
            file_report="${file_report}\n- 💡 L${lineno}: API调用无try/catch: \`${content:0:60}\`"
        done <<< "$api_calls_no_catch"
    fi

    # 5. Vue文件: 检查v-model绑定的ref是否存在
    if echo "$basename" | grep -qE '\.vue$'; then
        local vmodels
        vmodels=$(grep -oP 'v-model="(\w+)' "$file" 2>/dev/null | grep -oP '"\K\w+' | sort -u || true)
        for vm in $vmodels; do
            if ! grep -qE "(const\s+${vm}\s*=|ref.*${vm}|reactive.*${vm})" "$file" 2>/dev/null; then
                if ! grep -rqE "(const\s+${vm}\s*=|ref.*${vm})" "${FRONTEND_DIR}/views/monitor/composables/" --include="*.ts" 2>/dev/null; then
                    file_report="${file_report}\n- ⚠️ v-model=\"${vm}\" 但ref未定义"
                    ((issues++)) || true
                fi
            fi
        done
    fi

    # 输出该文件报告
    if [ -n "$file_report" ] || [ "$issues" -gt 0 ]; then
        echo "### ${basename}" >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"
        echo -e "$file_report" >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"
        if [ "$issues" -gt 0 ]; then
            echo "**${issues} 个问题**" >> "$REPORT_FILE"
        else
            echo "💡 建议优化项(非阻断)" >> "$REPORT_FILE"
        fi
        echo "" >> "$REPORT_FILE"
    else
        echo "### ${basename}" >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"
        echo "✅ 无问题" >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"
    fi

    TOTAL_ISSUES=$((TOTAL_ISSUES + issues))
}

# =====================================================================
# 按目录审计
# =====================================================================

echo "## Monitor视图 (核心)" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

for f in $(find "$FRONTEND_DIR/views/monitor" -name "*.vue" -o -name "*.ts" | sort); do
    audit_file "$f"
    TOTAL_FILES=$((TOTAL_FILES + 1))
done

echo "## API模块" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

for f in $(find "$FRONTEND_DIR/api/modules" -name "*.ts" | sort); do
    audit_file "$f"
    TOTAL_FILES=$((TOTAL_FILES + 1))
done

echo "## Stores" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

for f in $(find "$FRONTEND_DIR/stores" -name "*.ts" | sort); do
    audit_file "$f"
    TOTAL_FILES=$((TOTAL_FILES + 1))
done

echo "## 工具函数" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

for f in $(find "$FRONTEND_DIR/utils" -name "*.ts" -not -name "*.d.ts" | sort); do
    audit_file "$f"
    TOTAL_FILES=$((TOTAL_FILES + 1))
done

echo "## 其他页面" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

for f in $(find "$FRONTEND_DIR/views" -name "*.vue" -not -path "*/monitor/*" | sort); do
    audit_file "$f"
    TOTAL_FILES=$((TOTAL_FILES + 1))
done

# =====================================================================
# 总结
# =====================================================================
echo "---" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "## 总结" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "- 审计文件数: ${TOTAL_FILES}" >> "$REPORT_FILE"
echo "- 发现问题数: ${TOTAL_ISSUES}" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

if [ "$TOTAL_ISSUES" -eq 0 ]; then
    echo "✅ 全部文件审计通过" >> "$REPORT_FILE"
else
    echo "⚠️ 有 ${TOTAL_ISSUES} 个问题需确认" >> "$REPORT_FILE"
fi
