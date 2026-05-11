#!/bin/bash
# 每日收盘后自动补数据
# crontab: 15 15 * * 1-5 /root/.openclaw/workspace/StockAgent/AgentServer/scripts/daily_data_update.sh >> /var/log/stock_daily_update.log 2>&1
# 周一到周五 15:15 运行(A股15:00收盘,留15分钟缓冲)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

# 检查是否交易日(简单判断: 周末肯定不是)
DOW=$(date +%u)
if [ "$DOW" -ge 6 ]; then
    echo "$LOG_PREFIX 周末非交易日，跳过"
    exit 0
fi

# 检查是否A股节假日(简单版: 1/1, 5/1, 10/1-7等)
TODAY=$(date +%m%d)
case $TODAY in
    0101|0102|0103|0501|0502|0503|1001|1002|1003|1004|1005|1006|1007)
        echo "$LOG_PREFIX 节假日($TODAY)，跳过"
        exit 0
        ;;
esac

echo "$LOG_PREFIX ========== 每日数据更新开始 =========="

# 1. 东方财富全市场快照 → stock_daily_ak_full (OHLCV)
echo "$LOG_PREFIX [1/2] 补全日线OHLCV..."
python3 "$SCRIPT_DIR/eastmoney_daily_bar.py" 2>&1
BAR_EXIT=$?
if [ $BAR_EXIT -eq 0 ]; then
    echo "$LOG_PREFIX [1/2] ✅ 日线OHLCV补全成功"
else
    echo "$LOG_PREFIX [1/2] ⚠️ 日线OHLCV补全失败(exit=$BAR_EXIT), 可能是非交易日"
fi

# 2. 东方财富全市场快照 → daily_basic (PE/PB/流通市值/换手率/量比)
echo "$LOG_PREFIX [2/3] 补全daily_basic..."
python3 "$SCRIPT_DIR/eastmoney_daily_basic.py" 2>&1
BASIC_EXIT=$?
if [ $BASIC_EXIT -eq 0 ]; then
    echo "$LOG_PREFIX [2/3] ✅ daily_basic补全成功"
else
    echo "$LOG_PREFIX [2/3] ⚠️ daily_basic补全失败(exit=$BASIC_EXIT), 可能是非交易日"
fi

# 3. 预计算因子(MA/涨跌停/量比等)
echo "$LOG_PREFIX [3/3] 预计算因子..."
python3 "$SCRIPT_DIR/daily_factor_precompute.py" 2>&1
FACTOR_EXIT=$?
if [ $FACTOR_EXIT -eq 0 ]; then
    echo "$LOG_PREFIX [3/3] ✅ 因子预计算成功"
else
    echo "$LOG_PREFIX [3/3] ⚠️ 因子预计算失败(exit=$FACTOR_EXIT)"
fi

echo "$LOG_PREFIX ========== 每日数据更新完成 =========="
