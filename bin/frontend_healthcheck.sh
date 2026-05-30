#!/bin/bash
# =============================================
# 🏥 前端健康检查脚本 - 检测白屏/渲染失败
# 用法:
#   ./bin/frontend_healthcheck.sh          # 一次性检查
#   ./bin/frontend_healthcheck.sh --watch  # 持续监控(每5分钟)
# 可加入crontab: */5 * * * * /path/to/frontend_healthcheck.sh
# =============================================

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

HEALTH_LOG="${PROJECT_ROOT}/logs/frontend_health.log"
ALERT_FLAG="/tmp/frontend_health_alert_sent"

check() {
    local issues=0
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    echo -e "${YELLOW}[${timestamp}] 前端健康检查...${NC}"
    echo "[${timestamp}] === 前端健康检查 ===" >> "$HEALTH_LOG"

    # =============================================
    # 1. 检查关键文件存在
    # =============================================
    STATIC_DIR="${PROJECT_ROOT}/AgentServer/static"
    DIST_DIR="${PROJECT_ROOT}/frontend/dist"
    
    for dir_name in "$STATIC_DIR" "$DIST_DIR"; do
        if [ ! -f "${dir_name}/index.html" ]; then
            echo -e "${RED}❌ ${dir_name}/index.html 不存在${NC}"
            echo "[${timestamp}] FAIL: ${dir_name}/index.html missing" >> "$HEALTH_LOG"
            issues=$((issues + 1))
        else
            HTML_SIZE=$(stat -c '%s' "${dir_name}/index.html" 2>/dev/null || echo "0")
            if [ "$HTML_SIZE" -lt 100 ]; then
                echo -e "${RED}❌ ${dir_name}/index.html 异常小(${HTML_SIZE} bytes)${NC}"
                echo "[${timestamp}] FAIL: ${dir_name}/index.html too small (${HTML_SIZE}B)" >> "$HEALTH_LOG"
                issues=$((issues + 1))
            fi
        fi
    done

    # =============================================
    # 2. 检查dist和static是否同步(文件数量和最新文件hash)
    # =============================================
    DIST_COUNT=$(find "$DIST_DIR" -type f 2>/dev/null | wc -l)
    STATIC_COUNT=$(find "$STATIC_DIR" -type f 2>/dev/null | wc -l)
    
    if [ "$DIST_COUNT" -ne "$STATIC_COUNT" ]; then
        echo -e "${YELLOW}⚠️  dist(${DIST_COUNT}文件)与static(${STATIC_COUNT}文件)不同步${NC}"
        echo "[${timestamp}] WARN: dist($DIST_COUNT) vs static($STATIC_COUNT) file count mismatch" >> "$HEALTH_LOG"
        # 不同步但不是致命错误,自动修复
        echo -e "${YELLOW}   自动修复: 执行同步...${NC}"
        rsync -a --delete "${DIST_DIR}/" "${STATIC_DIR}/"
        echo "[${timestamp}] FIX: synced dist → static" >> "$HEALTH_LOG"
    fi

    # =============================================
    # 3. 检查后端服务(8000)是否正常响应
    # =============================================
    if ss -tlnp 2>/dev/null | grep -q ":8000 "; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8000/ 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" != "200" ]; then
            echo -e "${RED}❌ 后端(8000)返回 HTTP ${HTTP_CODE}${NC}"
            echo "[${timestamp}] FAIL: backend HTTP ${HTTP_CODE}" >> "$HEALTH_LOG"
            issues=$((issues + 1))
        else
            # 检查页面不是空白
            HTML_LEN=$(curl -s --max-time 5 http://localhost:8000/ 2>/dev/null | wc -c)
            if [ "$HTML_LEN" -lt 200 ]; then
                echo -e "${RED}❌ 后端(8000)返回页面过小(${HTML_LEN} bytes)${NC}"
                echo "[${timestamp}] FAIL: backend page too small (${HTML_LEN}B)" >> "$HEALTH_LOG"
                issues=$((issues + 1))
            else
                echo -e "${GREEN}✅ 后端(8000)正常 (HTTP 200, ${HTML_LEN} bytes)${NC}"
            fi
        fi
    else
        echo -e "${YELLOW}⚠️  后端(8000)未运行${NC}"
        echo "[${timestamp}] WARN: backend not running" >> "$HEALTH_LOG"
    fi

    # =============================================
    # 4. 检查Nginx是否指向8000(而非5174)
    # =============================================
    NGINX_CONF="/etc/nginx/sites-enabled/stockagent"
    if [ -f "$NGINX_CONF" ]; then
        # 检查 location / { 是否指向 5174
        if grep -A2 'location / {' "$NGINX_CONF" | grep -q 'proxy_pass http://localhost:5174'; then
            echo -e "${RED}❌ Nginx :80 指向 Vite dev(5174)，有白屏风险！${NC}"
            echo "[${timestamp}] FAIL: nginx :80 -> 5174 (should be 8000)" >> "$HEALTH_LOG"
            issues=$((issues + 1))
            # 自动修复
            echo -e "${YELLOW}   自动修复: 执行 nginx 配置修复...${NC}"
            "${PROJECT_ROOT}/bin/frontend_fix_nginx.sh" >> "$HEALTH_LOG" 2>&1 || true
        else
            echo -e "${GREEN}✅ Nginx :80 → 8000 (生产模式)${NC}"
        fi
    fi

    # =============================================
    # 5. 检查Vite缓存是否过大(腐败征兆)
    # =============================================
    VITE_CACHE="${PROJECT_ROOT}/frontend/node_modules/.vite"
    if [ -d "$VITE_CACHE" ]; then
        CACHE_SIZE=$(du -sm "$VITE_CACHE" 2>/dev/null | cut -f1)
        if [ "$CACHE_SIZE" -gt 200 ]; then
            echo -e "${YELLOW}⚠️  Vite缓存过大(${CACHE_SIZE}MB)，建议清理${NC}"
            echo "[${timestamp}] WARN: vite cache ${CACHE_SIZE}MB" >> "$HEALTH_LOG"
        fi
    fi

    # =============================================
    # 汇总
    # =============================================
    if [ $issues -eq 0 ]; then
        echo -e "${GREEN}✅ 前端健康检查通过${NC}"
        echo "[${timestamp}] PASS: all checks OK" >> "$HEALTH_LOG"
        rm -f "$ALERT_FLAG"
    else
        echo -e "${RED}❌ 发现 ${issues} 个问题${NC}"
        echo "[${timestamp}] FAIL: ${issues} issues found" >> "$HEALTH_LOG"
        
        # 如果是持续失败，自动重建前端
        if [ ! -f "$ALERT_FLAG" ]; then
            touch "$ALERT_FLAG"
            echo -e "${YELLOW}🔧 自动修复: 重新构建前端...${NC}"
            "${PROJECT_ROOT}/bin/frontend_deploy.sh" >> "$HEALTH_LOG" 2>&1 || true
        fi
    fi
}

# 执行检查
check

# 可选: 持续监控
if [[ "${1:-}" == "--watch" ]]; then
    echo -e "${YELLOW}👀 持续监控模式(每5分钟检查一次, Ctrl+C退出)${NC}"
    while true; do
        sleep 300
        check
    done
fi
