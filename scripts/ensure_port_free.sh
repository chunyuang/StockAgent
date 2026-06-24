#!/bin/bash
#
# ensure_port_free.sh - 端口预占用清理脚本
#
# 用途:
#   systemd 服务启动前, 检测目标端口是否被孤儿/僵尸进程占用,
#   是非 systemd cgroup 管理的进程则强制 kill, 防止 v2.9.99-r9 的孤儿进程占端口 BUG.
#
# 使用:
#   ensure_port_free.sh PORT [PORT2 PORT3 ...]
#   ensure_port_free.sh 8000
#   ensure_port_free.sh 8000 50051
#
# 集成到 systemd unit (推荐):
#   [Service]
#   ExecStartPre=/root/.openclaw/workspace/StockAgent/scripts/ensure_port_free.sh 8000 50051
#   ExecStart=...
#
# 安全规则:
#   1. 只 kill 占着端口的进程, 不动其他进程
#   2. 不 kill systemd cgroup 内的进程(那是另一个服务的合法占用, 应该让 systemd 处理)
#   3. 只 kill PPID=1 的孤儿进程, 或父进程已死的僵尸进程
#   4. 给 3 秒 SIGTERM 优雅退出, 不行才 SIGKILL
#   5. 输出全部 log 到 stderr, 便于 systemd journal 收集
#
# 退出码:
#   0 = 端口已空闲, 或孤儿进程已成功 kill, 安全启动
#   1 = 参数错误
#   2 = 端口被合法 systemd 服务占用(冲突, 拒绝清理)
#   3 = kill 失败(进程僵死无法清理)
#
# 历史: 2026-06-24 v2.9.99-r10 创建
#       根因: 孤儿 python 进程占着 8000, systemd 死循环重启, API 走的还是旧代码
#

set -u

PORTS=("$@")
if [ ${#PORTS[@]} -eq 0 ]; then
    echo "Usage: $0 PORT [PORT2 ...]" >&2
    exit 1
fi

log() { echo "[$(date '+%H:%M:%S')] [port-guard] $*" >&2; }

EXIT_CODE=0
for PORT in "${PORTS[@]}"; do
    log "检查端口 $PORT ..."
    
    # 取占用端口的 PID
    PIDS=$(ss -tlnpH 2>/dev/null | awk -v p=":$PORT" '$4 ~ p {print $NF}' | grep -oE 'pid=[0-9]+' | sed 's/pid=//' | sort -u)
    
    if [ -z "$PIDS" ]; then
        log "  ✅ 端口 $PORT 空闲"
        continue
    fi
    
    for PID in $PIDS; do
        # 看进程是否还活着
        if ! kill -0 "$PID" 2>/dev/null; then
            log "  ⚠️ PID $PID 已不存在(可能 ss 缓存)"
            continue
        fi
        
        # 看 cgroup: 如果在 system.slice/xxx.service 下 = 合法 systemd 服务管理
        CGROUP=$(cat /proc/$PID/cgroup 2>/dev/null | head -1 | sed 's/.*://')
        P_PARENT=$(ps -o ppid= -p $PID 2>/dev/null | tr -d ' ')
        CMD=$(ps -o cmd= -p $PID 2>/dev/null | head -c 100)
        
        log "  发现 PID=$PID PPID=$P_PARENT cgroup=$CGROUP"
        log "       cmd: $CMD"
        
        # 判定是否孤儿
        IS_ORPHAN=false
        if [ "$P_PARENT" = "1" ] && [[ "$CGROUP" != *.service ]]; then
            IS_ORPHAN=true
            log "  🧟 判定: 孤儿进程(PPID=1 且不在 service cgroup)"
        elif [[ "$CGROUP" == */user@*.service/* ]] || [[ "$CGROUP" == *user.slice* ]]; then
            IS_ORPHAN=true
            log "  🧟 判定: 用户会话残留进程(user.slice/user@*.service)"
        elif [ ! -d "/proc/$P_PARENT" ]; then
            IS_ORPHAN=true
            log "  🧟 判定: 父进程已死(僵尸)"
        else
            # 合法 systemd service cgroup 内的进程, 不能动
            log "  🛡️ 跳过: 进程在合法 service cgroup, 不应由此脚本清理"
            log "       (如果是冲突, 请 systemctl stop 对应 service)"
            EXIT_CODE=2
            continue
        fi
        
        if [ "$IS_ORPHAN" = "true" ]; then
            log "  🔫 kill -TERM $PID"
            kill -TERM "$PID" 2>/dev/null
            
            # 给 3 秒优雅退出
            for i in 1 2 3; do
                sleep 1
                if ! kill -0 "$PID" 2>/dev/null; then
                    log "  ✅ PID $PID 已退出"
                    break
                fi
            done
            
            # 强杀
            if kill -0 "$PID" 2>/dev/null; then
                log "  ⚡ SIGKILL $PID (SIGTERM 失败)"
                kill -KILL "$PID" 2>/dev/null
                sleep 1
                if kill -0 "$PID" 2>/dev/null; then
                    log "  ❌ PID $PID 僵死无法 kill"
                    EXIT_CODE=3
                fi
            fi
        fi
    done
    
    # 再确认端口空了
    STILL=$(ss -tlnpH 2>/dev/null | awk -v p=":$PORT" '$4 ~ p {print}' | head -1)
    if [ -n "$STILL" ]; then
        log "  ⚠️ 端口 $PORT 仍被占: $STILL"
        if [ $EXIT_CODE -eq 0 ]; then
            EXIT_CODE=3
        fi
    else
        log "  ✅ 端口 $PORT 清理完毕"
    fi
done

exit $EXIT_CODE
