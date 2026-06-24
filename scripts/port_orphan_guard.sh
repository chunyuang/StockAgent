#!/bin/bash
#
# port_orphan_guard.sh - 孤儿进程定期巡检
#
# 用途:
#   独立 cron, 每 10 分钟扫描关键端口是否被孤儿进程占用,
#   一旦发现且对应 systemd 服务正在 restart 死循环, 自动 kill 孤儿 + 触发服务重启.
#
# 策略:
#   - 8000 应该由 stockagent-web 拥有
#   - 5174 应该由 stockagent-frontend 拥有
#   - 50051 应该由 stockagent-web 拥有
#   如果端口的占用者不在对应 service 的 cgroup 内 = 孤儿 = 清理
#
# 使用:
#   /root/.openclaw/workspace/StockAgent/scripts/port_orphan_guard.sh
#   echo "*/10 * * * * /root/.openclaw/workspace/StockAgent/scripts/port_orphan_guard.sh" | crontab -
#
# 历史: 2026-06-24 v2.9.99-r10
#

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGFILE="/root/.openclaw/workspace/StockAgent/logs/port_orphan_guard.log"
mkdir -p "$(dirname $LOGFILE)"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$LOGFILE" >&2
}

# 期望: 端口 -> systemd service 名
declare -A PORT_OWNER=(
    [8000]="stockagent-web.service"
    [50051]="stockagent-web.service"
    [5174]="stockagent-frontend.service"
)

FIXED=0
for PORT in "${!PORT_OWNER[@]}"; do
    OWNER="${PORT_OWNER[$PORT]}"
    
    PIDS=$(ss -tlnpH 2>/dev/null | awk -v p=":$PORT" '$4 ~ p {print $NF}' | grep -oE 'pid=[0-9]+' | sed 's/pid=//' | sort -u)
    
    if [ -z "$PIDS" ]; then
        # 端口空: 检查 owner service 是否应该在跑
        if systemctl is-enabled "$OWNER" 2>/dev/null | grep -q enabled; then
            STATE=$(systemctl is-active "$OWNER" 2>/dev/null)
            if [ "$STATE" != "active" ]; then
                log "⚠️ 端口 $PORT 空闲但 $OWNER 状态=$STATE, 尝试启动"
                systemctl start "$OWNER" 2>&1 | head -3 | while read l; do log "   $l"; done
                FIXED=$((FIXED + 1))
            fi
        fi
        continue
    fi
    
    for PID in $PIDS; do
        kill -0 "$PID" 2>/dev/null || continue
        CGROUP=$(cat /proc/$PID/cgroup 2>/dev/null | head -1 | sed 's/.*://')
        
        # 检查 cgroup 是不是 owner service
        if [[ "$CGROUP" == *"/$OWNER"* ]]; then
            # 正常: owner 服务在用
            continue
        fi
        
        # 不是 owner 占用 = 孤儿/冲突
        CMD=$(ps -o cmd= -p $PID 2>/dev/null | head -c 80)
        log "🚨 端口 $PORT 被非 $OWNER 进程占用: PID=$PID cgroup=$CGROUP"
        log "   cmd: $CMD"
        
        # 调用 ensure_port_free 清理
        if "$SCRIPT_DIR/ensure_port_free.sh" "$PORT" 2>&1 | while read l; do log "   $l"; done; then
            log "   ✅ 清理完毕, 重启 $OWNER"
            systemctl restart "$OWNER" 2>&1 | head -2 | while read l; do log "   $l"; done
            FIXED=$((FIXED + 1))
        else
            log "   ❌ 清理失败, 跳过自动重启 (避免雪崩)"
        fi
    done
done

if [ $FIXED -gt 0 ]; then
    log "🛡️ 巡检完成: 修复 $FIXED 个问题"
else
    # 正常时不刷屏, 但每天 0 点记录一次健康状态
    if [ "$(date +%H%M)" = "0000" ]; then
        log "💚 巡检完成: 全部端口归属正确"
    fi
fi
exit 0
