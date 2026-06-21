#!/bin/bash
# 盘前扫描器自愈脚本
# 检查扫描器进程+扫描循环状态，如未运行则自动启动
# 用法: bash scripts/scanner_autoheal.sh [--force]

set -euo pipefail

API_BASE="http://localhost:8000/api/v1"
LOG_PREFIX="[AUTOHEAL]"
FORCE_START="${1:-}"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $LOG_PREFIX $*"; }

# 0. 清理孤儿进程(端口占用问题)
# 如果systemd服务crash-loop因为port 8000被旧进程占用,
# 需要先杀掉占用端口的进程
PORT_PID=$(fuser 8000/tcp 2>/dev/null | tr -d ' ')
if [ -n "$PORT_PID" ]; then
    # 检查这个PID是不是systemd管理的
    SERVICE_PID=$(systemctl show stockagent-backend --property=MainPID --value 2>/dev/null || echo "0")
    if [ "$PORT_PID" != "$SERVICE_PID" ] && [ "$PORT_PID" != "0" ]; then
        log "🔪 发现孤儿进程 PID=$PORT_PID 占用端口8000(服务PID=$SERVICE_PID), 终止中..."
        kill -9 "$PORT_PID" 2>/dev/null || true
        sleep 2
        # 验证端口已释放
        if fuser 8000/tcp > /dev/null 2>&1; then
            log "❌ 端口8000仍被占用, 强制清理"
            fuser -k 8000/tcp 2>/dev/null || true
            sleep 2
        else
            log "✅ 孤儿进程已终止, 端口8000已释放"
        fi
    fi
fi

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

# 1.5 检查 systemd 服务是否 crash-looping
SERVICE_STATUS=$(systemctl is-active stockagent-backend.service 2>/dev/null || echo "unknown")
if [ "$SERVICE_STATUS" = "failed" ] || [ "$SERVICE_STATUS" = "activating" ]; then
    log "⚠️ 服务状态: $SERVICE_STATUS (可能crash-loop), 重启服务"
    # 先确保端口没有孤儿进程
    fuser -k 8000/tcp 2>/dev/null || true
    sleep 2
    systemctl restart stockagent-backend.service
    sleep 8
    SERVICE_STATUS2=$(systemctl is-active stockagent-backend.service 2>/dev/null || echo "unknown")
    if [ "$SERVICE_STATUS2" != "active" ]; then
        log "❌ 服务重启后仍不健康: $SERVICE_STATUS2"
        exit 1
    fi
    log "✅ 服务重启成功"
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

# 2.5 【v2.9.98h修复】周末/非交易时段不启动scanner
# autoheal判断逻辑: is_running&&(scan_count>0||status!='red')
# 周末health永远是red导致反复POST /scanner/start, 时间线累积到2400条
# 解决: 非交易时段跳过start, 只检查进程存活+API可达
DOW=$(date +%u)  # 1=Monday, 7=Sunday
HHMM=$(date +%H%M | sed 's/^0*//')  # 去前导0
IS_WEEKEND=false
IS_OFF_HOURS=false
if [ "$DOW" -ge 6 ]; then
    IS_WEEKEND=true
fi
if [ -z "$HHMM" ] || [ "$HHMM" -lt 900 ] 2>/dev/null || [ "$HHMM" -ge 1530 ] 2>/dev/null; then
    IS_OFF_HOURS=true
fi

if [ "$IS_WEEKEND" = "true" ]; then
    log "⏭️ 周末不启动scanner, 仅检查进程+API存活"
    # 确保进程存活+API可达即可, 不启动scanner
    if [ "$IS_RUNNING" = "true" ]; then
        log "✅ scanner进程运行中, 周末无需启动扫描循环"
    fi
    exit 0
fi
if [ "$IS_OFF_HOURS" = "true" ]; then
    log "⏭️ 非交易时段($HHMM), 仅检查进程+API存活"
    exit 0
fi

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
elif echo "$START_RESULT" | grep -q '已在运行中'; then
    log "ℹ️ 扫描器已在运行中"
else
    log "❌ 扫描器启动失败: $START_RESULT"
    exit 1
fi

# 5. 同步前端生产 build (确保 Web 看到最新代码)
log "🔄 同步前端生产 build..."
cd /root/.openclaw/workspace/StockAgent/frontend
if npx vite build > /tmp/vite_build.log 2>&1; then
    rsync -a --delete dist/ /root/.openclaw/workspace/StockAgent/AgentServer/static/
    log "✅ 前端 build 已同步到 static/"
else
    log "⚠️ 前端 build 失败，保留旧版本 (详见 /tmp/vite_build.log)"
fi

# 6. 确保云桌面浏览器在跑 (反向漏斗:浏览器崩了则重启)
if command -v supervisorctl > /dev/null 2>&1; then
    BROWSER_STATUS=$(supervisorctl status cua-vnc:monitor-browser 2>/dev/null | awk '{print $2}')
    if [ "$BROWSER_STATUS" != "RUNNING" ]; then
        log "🔄 云桌面浏览器未运行 ($BROWSER_STATUS), 重启中..."
        supervisorctl restart cua-vnc:monitor-browser > /dev/null 2>&1
        sleep 5
        log "✅ 云桌面浏览器已重启"
    else
        log "✅ 云桌面浏览器运行中"
        # 刚重新build了前端, 刷新浏览器拿最新代码
        log "🔄 刷新云桌面浏览器以加载最新代码..."
        DISPLAY=:99 xdotool search --name "localhost" key --window %@ ctrl+F5 > /dev/null 2>&1 || \
            DISPLAY=:99 xdotool key --window $(DISPLAY=:99 xdotool search --name "Monitor" 2>/dev/null | head -1) F5 > /dev/null 2>&1 || true
    fi
fi
