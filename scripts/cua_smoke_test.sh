#!/bin/bash
# ============================================================
# CUA Visual Smoke Test - 真实浏览器视觉烟测
#
# 用 CUA(Computer Use Agent)操作真实 Chrome 浏览器,逐 Tab 抓:
#   1) F12 Console 是否有红色 ReferenceError/TypeError
#   2) 每个 Tab 是否渲染(非白屏/非"暂无数据")
#   3) 数据是否与后端 API 一致
#
# 拦截 Playwright 抓不到的运行时 bug:
#   - production bundle 中 __DEV__/__APP_VERSION__ 等 vite define 缺失
#   - watch 缺 immediate 导致首次 fetch 不触发
#   - composable spread 覆盖导致 ref 失效
#   - element-plus 拆 chunk 后的 ESM 循环依赖白屏
#
# 使用: bash cua_smoke_test.sh
# Exit: 0=全 ✅ / 1=有 P0 错误 / 2=CUA 自身故障
# ============================================================

set -uo pipefail

URL="${MONITOR_URL:-http://localhost:8000/monitor}"
OUT_DIR="${OUT_DIR:-/root/.openclaw/workspace/StockAgent/logs/cua_smoke}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$OUT_DIR/smoke_${TIMESTAMP}.log"

mkdir -p "$OUT_DIR"

echo "🔥 CUA Visual Smoke Test" | tee "$LOG_FILE"
echo "========================" | tee -a "$LOG_FILE"
echo "Target: $URL" | tee -a "$LOG_FILE"
echo "Start:  $(date '+%F %T')" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Step 1: 杀掉残留 CUA 进程(否则新 run 预检阻塞)
STALE=$(pgrep -af '/root/.cua/cua' | grep -v "pgrep" | wc -l)
if [ "$STALE" -gt 0 ]; then
    echo "🧹 清理残留 CUA 进程 ($STALE 个)..." | tee -a "$LOG_FILE"
    pkill -f '/root/.cua/cua' 2>/dev/null || true
    sleep 2
fi

# Step 2: 检查关键依赖
if [ ! -x ~/.agents/skills/computer-use/scripts/cua.sh ]; then
    echo "❌ CUA 脚本不存在或不可执行" | tee -a "$LOG_FILE"
    exit 2
fi

if ! curl -sf -m 5 -o /dev/null "$URL"; then
    echo "❌ 目标 URL 不可访问: $URL" | tee -a "$LOG_FILE"
    exit 2
fi

# Step 3: 启动 CUA 任务
TASK="打开浏览器访问 $URL 并按 Ctrl+Shift+R 强制刷新。等 4 秒页面加载完毕。
然后逐个点击以下 8 个 Tab,每个 Tab 切换后等 3 秒让数据加载:
  1) 📈 实盘交易(trading) - 检查是否显示 KPI/持仓/信号
  2) 📅 盘前竞价(premarket) - 检查涨跌停统计/候选股票
  3) 🔍 扫描追踪(scan-trace) - 检查 9 层漏斗数据
  4) 📊 数据分析(analysis) - 检查每日明细(应该有多行历史数据)
  5) 💼 实盘(account) - 切到 🛡️ 风控状态子标签,检查扫描器实例/扫描循环/风控线程是否都显示 ✅
  6) 📜 历史记录(history)
  7) 🌡️ 情绪周期(sentiment)
  8) ⚙️ 系统运维(ops) - 检查自动交易操作流是否有今日记录

对每个 Tab 截图,记录:
  a) Tab 是否成功渲染(不是空白页/不是 loading)
  b) 浏览器 F12 Console 是否有红色 Error(尤其是 ReferenceError / TypeError / Cannot read properties)
  c) 数据是否合理(非 NaN/undefined/null/all-zero)

最终在 records/cua_smoke_report.md 输出结构化报告,格式:
## 烟测结论
- 总检查项: 8 个 Tab
- ✅ 通过: <N>
- ⚠️ 警告: <列出 Tab + 问题>
- ❌ 失败: <列出 Tab + 错误>

## Console 错误清单
(列出所有 ReferenceError / TypeError, 标注来源文件)

## 各 Tab 数据快照
(每 Tab 一句话描述看到的内容)"

echo "🚀 启动 CUA 浏览器烟测..." | tee -a "$LOG_FILE"
nohup bash ~/.agents/skills/computer-use/scripts/cua.sh run "$TASK" > "$OUT_DIR/cua_run_${TIMESTAMP}.out" 2>&1 &
CUA_PID=$!
echo "   CUA PID: $CUA_PID" | tee -a "$LOG_FILE"

# Step 4: 等待 CUA 完成(最多 12 分钟)
MAX_WAIT=720
WAITED=0
RUN_DIR=""

while [ $WAITED -lt $MAX_WAIT ]; do
    sleep 15
    WAITED=$((WAITED + 15))

    # 找出本次 run 的目录(创建时间在脚本启动后)
    if [ -z "$RUN_DIR" ]; then
        RUN_DIR=$(find /root/.cua/runs -maxdepth 1 -type d -newer "$LOG_FILE" 2>/dev/null | head -1)
    fi

    if [ -n "$RUN_DIR" ] && [ -f "$RUN_DIR/steps.json" ]; then
        echo "✅ CUA 完成 (用时 ${WAITED}s)" | tee -a "$LOG_FILE"
        break
    fi

    if [ $((WAITED % 60)) -eq 0 ]; then
        echo "   ...等待中 ${WAITED}s / ${MAX_WAIT}s" | tee -a "$LOG_FILE"
    fi
done

# Step 5: 收集结果
if [ -z "$RUN_DIR" ] || [ ! -f "$RUN_DIR/steps.json" ]; then
    echo "❌ CUA 超时未完成 (${MAX_WAIT}s)" | tee -a "$LOG_FILE"
    pkill -f '/root/.cua/cua' 2>/dev/null || true
    exit 2
fi

echo "" | tee -a "$LOG_FILE"
echo "📊 烟测报告" | tee -a "$LOG_FILE"
echo "==========" | tee -a "$LOG_FILE"

REPORT=""
if [ -f "$RUN_DIR/records/cua_smoke_report.md" ]; then
    REPORT="$RUN_DIR/records/cua_smoke_report.md"
elif [ -f "$RUN_DIR/records/findings.md" ]; then
    REPORT="$RUN_DIR/records/findings.md"
else
    # 找最大的 .md
    REPORT=$(ls -S "$RUN_DIR/records/"*.md 2>/dev/null | head -1)
fi

if [ -n "$REPORT" ] && [ -f "$REPORT" ]; then
    cat "$REPORT" | tee -a "$LOG_FILE"
    cp "$REPORT" "$OUT_DIR/report_${TIMESTAMP}.md"
else
    echo "⚠️ 未找到 CUA 结构化报告,仅有 steps.json" | tee -a "$LOG_FILE"
    tail -30 "$RUN_DIR/steps.json" | tee -a "$LOG_FILE"
fi

# Step 6: 退出码判定 (用 grep 在报告中找关键词)

if [ -n "$REPORT" ] && [ -f "$REPORT" ]; then
    # ❌ 失败标记
    if grep -qE "❌|ReferenceError|TypeError|Cannot read prop|白屏|空白页" "$REPORT"; then
        echo "" | tee -a "$LOG_FILE"
        echo "❌ 烟测发现 P0 错误,详见: $OUT_DIR/report_${TIMESTAMP}.md" | tee -a "$LOG_FILE"
        # 写入 issue 队列(如脚本存在)
        if [ -x /root/.openclaw/workspace/StockAgent/scripts/cron_issues.sh ]; then
            ERR_SUMMARY=$(grep -E "❌|ReferenceError|TypeError" "$REPORT" | head -5 | tr '\n' '|' | head -c 400)
            bash /root/.openclaw/workspace/StockAgent/scripts/cron_issues.sh add P0 \
                "CUA浏览器烟测" \
                "前端运行时错误" \
                "$ERR_SUMMARY" \
                "见 $OUT_DIR/report_${TIMESTAMP}.md" \
                "检查最近前端 commit + 强刷浏览器" 2>/dev/null || true
        fi
        exit 1
    fi
fi

echo "" | tee -a "$LOG_FILE"
echo "✅ 烟测全部通过 ($(date '+%F %T'))" | tee -a "$LOG_FILE"

# 清理: 保留最近 7 天日志
find "$OUT_DIR" -type f -mtime +7 -delete 2>/dev/null || true

exit 0
