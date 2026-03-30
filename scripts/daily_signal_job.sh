#!/bin/bash
# 每日实盘信号生成定时任务
# 每日15:30盘后运行

cd /root/.openclaw/workspace/StockAgent

# 初始化环境
export PYTHONPATH=.:./AgentServer

# 1. 生成今日信号，保存到文件
DATE=$(date +%Y%m%d)
SIGNAL_FILE="./real_trading/signals/${DATE}.json"
mkdir -p ./real_trading/signals

echo "[$(date)] 开始生成 ${DATE} 实盘信号..."
python real_trading/generate_daily_signals.py --output "${SIGNAL_FILE}"

# 2. 推送信号到飞书
echo "[$(date)] 开始推送信号..."
# 读取信号内容推送
SIGNAL_CONTENT=$(python -c "
import json
data = json.load(open('${SIGNAL_FILE}', 'r', encoding='utf-8'))
date = data['date']
sentiment = data['sentiment']
content = f'📊 **{date} 实盘交易信号**\n---\n### 📈 市场情绪\n- 评分：**{sentiment[\"score\"]}分**\n- 等级：**{sentiment[\"level\"]}**\n- 仓位上限：**{sentiment[\"position_limit\"]:.0%}**\n- 允许策略：**{", ".join(sentiment[\"allowed_strategies\"])}**\n---\n### 🎯 选股结果\n{data[\"trading_plan\"]}'
print(content)
")
# 推送到飞书
/root/.openclaw/bin/openclaw message send --message "$SIGNAL_CONTENT" --channel feishu

# 3. 执行自动模拟交易
echo "[$(date)] 开始执行自动模拟交易..."
cd real_trading && python auto_trade_executor.py --date "${DATE}"

# 4. 生成当日绩效报告
echo "[$(date)] 生成当日绩效报告..."
PERFORMANCE_REPORT=$(python performance_report.py --account $(python -c "import json; data = json.load(open('paper_accounts.json')); print(next(acc_id for acc_id, acc in data.items() if acc['status'] == 'active'))"))
/root/.openclaw/bin/openclaw message send --message "📈 每日实盘绩效报告\n---\n$PERFORMANCE_REPORT" --channel feishu
cd ..

echo "[$(date)] 任务完成，信号已保存到 ${SIGNAL_FILE}，交易已执行，报告已推送"
