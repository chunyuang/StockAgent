#!/bin/bash
# V27参数扫描 - 8组参数,每组独立进程
cd /root/.openclaw/workspace/StockAgent/AgentServer
SCRIPT=scripts/run_v27_scan_single.py

echo "label|return|sharpe|drawdown|winrate|plr|trades|time"
echo "---|---|---|---|---|---|---|---"

# 0: V27基线(当前默认参数)
timeout 180 python $SCRIPT --label V27_基线 2>/dev/null

# 1: 龙头低吸TP 10%→12%
timeout 180 python $SCRIPT --label 龙头TP12% --dragon-tp 0.12 2>/dev/null

# 2: 龙头低吸TP 10%→15%
timeout 180 python $SCRIPT --label 龙头TP15% --dragon-tp 0.15 2>/dev/null

# 3: 跌停翘板SL 5%→4%
timeout 180 python $SCRIPT --label 跌停SL4% --limitdown-sl 0.04 2>/dev/null

# 4: 半路追涨SL 5%→4%
timeout 180 python $SCRIPT --label 半路SL4% --halfway-sl 0.04 2>/dev/null

# 5: 半路追涨TP 12%→15%
timeout 180 python $SCRIPT --label 半路TP15% --halfway-tp 0.15 2>/dev/null

# 6: 龙头TP12% + 半路TP15%
timeout 180 python $SCRIPT --label 龙头TP12+半路TP15 --dragon-tp 0.12 --halfway-tp 0.15 2>/dev/null

# 7: 龙头TP15% + 跌停SL4%
timeout 180 python $SCRIPT --label 龙头TP15+跌停SL4 --dragon-tp 0.15 --limitdown-sl 0.04 2>/dev/null
