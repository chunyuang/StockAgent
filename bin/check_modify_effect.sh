#!/bin/bash
echo "============================================="
# 定位项目根目录（相对于脚本位置）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "🚀 StockAgent修改生效检查工具 v1.0"
echo "============================================="
echo ""

# 1. 检查后端代码是否有未提交的修改
echo "🔍 1/4 检查后端代码修改状态："
cd "$SCRIPT_DIR/AgentServer"
git diff --stat -- nodes/web/api/backtest.py nodes/backtest_engine/factor_selection/portfolio_backtest.py
if [ $? -eq 0 ]; then
    echo "✅ 后端代码已修改保存"
else
    echo "❌ 后端代码未修改"
fi
echo ""

# 2. 检查前端代码是否已编译
echo "🔍 2/4 检查前端代码编译状态："
cd "$SCRIPT_DIR/frontend"
if [ -d dist/assets ]; then
    echo "✅ 前端代码已编译（dist目录存在）"
    dist_time=$(stat -c %Y dist/index.html)
    now=$(date +%s)
    diff=$(( (now - dist_time) / 60 ))
    if [ $diff -lt 10 ]; then
        echo "✅ 前端代码是最近10分钟内编译的，最新修改已生效"
    else
        echo "⚠️ 前端代码是$diff分钟前编译的，可能没有包含最新修改"
    fi
else
    echo "❌ 前端代码未编译（dist目录不存在），需要先运行npm run build"
fi
echo ""

# 3. 检查服务运行状态
echo "🔍 3/4 检查服务运行状态："
ps aux | grep -E "AgentServer/main.py|npm.*dev" | grep -v grep
if [ $? -eq 0 ]; then
    echo "✅ 所有服务正在运行"
else
    echo "❌ 部分服务未启动，请运行./restart_all.sh"
fi
echo ""

# 4. 检查版本标识
echo "🔍 4/4 检查当前代码版本标识："
grep -n "代码版本" /AgentServer/nodes/web/api/backtest.py
if [ $? -eq 0 ]; then
    echo "✅ 版本标识已设置，提交回测第一行会显示该版本号"
else
    echo "⚠️ 版本标识未设置，无法直观确认修改是否生效"
fi
echo ""

echo "============================================="
echo "✅ 检查完成！"
echo "👉 验证方法：提交回测看日志第一行是否显示对应版本号"
echo "👉 如果需要强制生效：运行./restart_all.sh 即可"
echo "============================================="
