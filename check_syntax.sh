#!/bin/bash
echo "============================================="
echo "🔍 强制Python语法&缩进检查"
echo "============================================="

# 检查所有Python文件（不需要git依赖）
modified_files=$(find AgentServer -name "*.py" 2>/dev/null)

if [ -z "$modified_files" ]; then
    echo "✅ 没有检测到修改的Python文件，跳过检查"
    exit 0
fi

echo "📝 待检查文件："
echo "$modified_files" | awk '{print "  - " $0}'
echo ""

# 逐个检查语法
error_count=0
for file in $modified_files; do
    if [ ! -f "$file" ]; then
        continue
    fi
    echo -n "  检查 $file ... "
    python -m py_compile "$file" >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "✅ 通过"
    else
        echo "❌ 失败"
        echo "    错误信息：$(python -m py_compile "$file" 2>&1 | head -3)"
        error_count=$((error_count + 1))
    fi
done

echo ""
if [ $error_count -gt 0 ]; then
    echo "============================================="
    echo "❌ 发现 $error_count 个语法/缩进错误，请修复后再执行！"
    echo "============================================="
    exit 1
else
    echo "============================================="
    echo "✅ 所有文件语法&缩进检查通过！"
    echo "============================================="
    exit 0
fi
