#!/bin/bash
# 盘前扫描器自愈脚本
# 检查扫描器进程+扫描循环状态，如未运行则自动启动
# 用法: bash scripts/scanner_autoheal.sh [--force]

set -euo pipefail

API_BASE="http://localhost:8000/api/v1"
LOG_PREFIX="[AUTOHEAL]"
FORCE_START="${1:-}"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $LOG_PREFIX $*"; }

# 1. 检查后端进程存活
if ! pgrep -f 'python.*main.py' > /dev/null 2>&1; then
    log "❌ 后端进程不存在，尝试启动 systemd 服务"
    systemctl restart stockagent-backend.service
    sleep 5
    if ! pgrep -f 'python.*main.py' > /dev/null 2>&1; then
        log "❌ 后端进程启动失败！"
        exit 1
    fi
    log "✅ 后端进程启动成功"
fi

# 2. 检查 API 可达性
for i in 1 2 3; do
    if curl -sf "$API_BASE/scanner/status" > /dev/null 2>&1; then
        break
    fi
    if [ $i -eq 3 ]; then
        log "❌ API 不可达(3次重试失败)，重启服务"
        systemctl restart stockagent-backend.service
        sleep 8
    fi
    sleep 2
done

# 3. 检查扫描循环是否激活
STATUS=$(curl -sf "$API_BASE/scanner/status" 2>/dev/null || echo '{}')
IS_RUNNING=$(echo "$STATUS" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    data = d.get('data', d)
    is_running = data.get('is_running', False)
    scan_count = data.get('scan_count', 0)
    health = data.get('health', {})
    status = health.get('status', 'unknown')
    # 扫描循环激活 = is_running且health不是red(或scan_count>0说明今天扫描过)
    if is_running and (scan_count > 0 or status != 'red'):
        print('true')
    else:
        print('false')
except:
    print('error')
" 2>/dev/null || echo "error")

if [ "$IS_RUNNING" = "true" ]; then
    log "✅ 扫描循环已激活，无需操作"
    exit 0
fi

if [ "$IS_RUNNING" = "error" ]; then
    log "⚠️ 无法解析扫描器状态，尝试启动"
fi

# 4. 启动扫描循环
log "🔄 扫描循环未激活，调用 start API..."

START_RESULT=$(curl -sf -X POST "$API_BASE/scanner/start" \
    -H "Content-Type: application/json" \
    -d '{"account_id":"default","trade_mode":"simulated","config":{}}' \
    2>/dev/null || echo '{"error":"curl_failed"}')

START_OK=$(echo "$START_RESULT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print('true' if d.get('success', False) else 'false')
except:
    print('false')
" 2>/dev/null || echo "false")

if [ "$START_OK" = "true" ]; then
    log "✅ 扫描器启动成功"
    # 等待2秒后验证
    sleep 2
    VERIFY=$(curl -sf "$API_BASE/scanner/status" 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    data = d.get('data', d)
    print('true' if data.get('is_running', False) else 'false')
except:
    print('false')
" 2>/dev/null || echo "false")
    if [ "$VERIFY" = "true" ]; then
        log "✅ 验证通过，扫描循环已激活"
    else
        log "⚠️ 启动后验证失败，扫描循环可能未激活"
    fi
else
    log "❌ 扫描器启动失败: $START_RESULT"
    exit 1
fi
