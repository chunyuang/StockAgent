#!/bin/bash
# =============================================
# 🎨 前端一键构建+部署+验证脚本
# 用法:
#   ./bin/frontend_deploy.sh          # 正常构建部署
#   ./bin/frontend_deploy.sh --watch  # 文件监听模式(修改自动构建)
# =============================================

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

FRONTEND_DIR="${PROJECT_ROOT}/frontend"
DIST_DIR="${FRONTEND_DIR}/dist"
STATIC_DIR="${PROJECT_ROOT}/AgentServer/static"
NGINX_CONF="/etc/nginx/sites-enabled/stockagent"

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}🎨 前端构建+部署+验证${NC}"
echo -e "${CYAN}============================================${NC}"

# =============================================
# Step 1: 清理Vite缓存(防止缓存腐败导致白屏)
# =============================================
echo -e "${YELLOW}🧹 1/5 清理Vite依赖缓存...${NC}"
VITE_CACHE="${FRONTEND_DIR}/node_modules/.vite"
if [ -d "$VITE_CACHE" ]; then
    CACHE_SIZE=$(du -sh "$VITE_CACHE" 2>/dev/null | cut -f1)
    rm -rf "$VITE_CACHE"
    echo -e "${GREEN}✅ 已清理 ${CACHE_SIZE} 缓存${NC}"
else
    echo -e "${GREEN}✅ 无Vite缓存，跳过${NC}"
fi

# =============================================
# Step 2: 构建前端
# =============================================
echo -e "${YELLOW}🔨 2/5 构建前端 (npm run build)...${NC}"
cd "$FRONTEND_DIR"
BUILD_LOG="${PROJECT_ROOT}/logs/frontend_build.log"

if npm run build > "$BUILD_LOG" 2>&1; then
    BUILD_SIZE=$(du -sh "$DIST_DIR" 2>/dev/null | cut -f1)
    FILE_COUNT=$(find "$DIST_DIR" -type f | wc -l)
    echo -e "${GREEN}✅ 构建成功: ${BUILD_SIZE}, ${FILE_COUNT} 个文件${NC}"
else
    echo -e "${RED}❌ 构建失败！日志:${NC}"
    tail -20 "$BUILD_LOG"
    exit 1
fi

# =============================================
# Step 3: 同步dist → AgentServer/static (rsync, 原子性)
# =============================================
echo -e "${YELLOW}📦 3/5 同步 dist/ → AgentServer/static/...${NC}"

# 先同步到临时目录，再原子替换
TEMP_STATIC="${STATIC_DIR}.tmp"
rm -rf "$TEMP_STATIC"
rsync -a --delete "${DIST_DIR}/" "$TEMP_STATIC/"

# 原子替换: 删旧→改名为新
rm -rf "$STATIC_DIR"
mv "$TEMP_STATIC" "$STATIC_DIR"

echo -e "${GREEN}✅ 静态文件已同步${NC}"

# =============================================
# Step 4: 验证页面可渲染
# =============================================
echo -e "${YELLOW}🔍 4/5 验证页面可渲染...${NC}"

# 检查关键文件存在
CRITICAL_FILES=("index.html" "assets")
for f in "${CRITICAL_FILES[@]}"; do
    if [ ! -e "${STATIC_DIR}/${f}" ]; then
        echo -e "${RED}❌ 缺失关键文件: ${f}${NC}"
        exit 1
    fi
done

# 检查index.html包含关键内容
if ! grep -q 'id="app"' "${STATIC_DIR}/index.html"; then
    echo -e "${RED}❌ index.html 缺少 #app 挂载点${NC}"
    exit 1
fi

# 检查JS入口文件存在
JS_ENTRY=$(grep -oP 'src="/assets/[^"]+\.js"' "${STATIC_DIR}/index.html" | head -1)
if [ -z "$JS_ENTRY" ]; then
    echo -e "${RED}❌ index.html 缺少JS入口${NC}"
    exit 1
fi

# 通过HTTP请求验证(如果后端在运行)
if ss -tlnp 2>/dev/null | grep -q ":8000 "; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        # 检查返回的HTML不是空的
        HTML_LEN=$(curl -s http://localhost:8000/ 2>/dev/null | wc -c)
        if [ "$HTML_LEN" -gt 100 ]; then
            echo -e "${GREEN}✅ 页面验证通过 (HTTP 200, ${HTML_LEN} bytes)${NC}"
        else
            echo -e "${RED}❌ 页面内容为空 (${HTML_LEN} bytes)${NC}"
            exit 1
        fi
    else
        echo -e "${YELLOW}⚠️  后端返回 HTTP ${HTTP_CODE}，可能需要重启${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  后端未运行(8000)，跳过HTTP验证${NC}"
fi

echo -e "${GREEN}✅ 静态文件完整性验证通过${NC}"

# =============================================
# Step 5: 确保Nginx指向build版本(8000)
# =============================================
echo -e "${YELLOW}🌐 5/5 检查Nginx配置...${NC}"
if [ -f "$NGINX_CONF" ]; then
    # 检查Nginx是否指向8000(生产)而非5174(Vite dev)
    if grep -q 'proxy_pass http://localhost:8000;' "$NGINX_CONF" && \
       ! grep -q 'location / {.*proxy_pass http://localhost:5174' "$NGINX_CONF"; then
        echo -e "${GREEN}✅ Nginx已指向8000(生产模式)${NC}"
    else
        echo -e "${YELLOW}⚠️  Nginx可能指向Vite dev(5174)，建议运行: ./bin/frontend_fix_nginx.sh${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Nginx配置文件不存在: ${NGINX_CONF}${NC}"
fi

# =============================================
# 完成
# =============================================
STATIC_HTML_TIME=$(stat -c '%y' "${STATIC_DIR}/index.html" 2>/dev/null | cut -d. -f1)
echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${GREEN}✅ 前端部署完成！${NC}"
echo -e "${GREEN}   静态文件: ${STATIC_DIR}${NC}"
echo -e "${GREEN}   更新时间: ${STATIC_HTML_TIME}${NC}"
echo -e "${GREEN}   访问地址: http://172.16.16.101/${NC}"
echo -e "${CYAN}============================================${NC}"

# =============================================
# 可选: 文件监听模式
# =============================================
if [[ "${1:-}" == "--watch" ]]; then
    echo -e "${CYAN}👀 启动文件监听模式(修改src/后自动构建部署)...${NC}"
    echo -e "${CYAN}   按 Ctrl+C 退出${NC}"
    
    # 用inotifywait监听src目录变化
    if command -v inotifywait &>/dev/null; then
        while true; do
            inotifywait -r -e modify,create,delete,move \
                --exclude '\.git|node_modules|dist|\.d\.ts' \
                "${FRONTEND_DIR}/src" 2>/dev/null
            echo -e "${YELLOW}📁 检测到文件变化，重新构建...${NC}"
            # 递归调用自身(不带--watch)
            "$0" || echo -e "${RED}❌ 构建失败，等待下次文件变化${NC}"
        done
    else
        echo -e "${YELLOW}⚠️  需要安装 inotifywait: apt install inotify-tools${NC}"
        # fallback: 每分钟检查一次
        LAST_HASH=""
        while true; do
            CURRENT_HASH=$(find "${FRONTEND_DIR}/src" -newer "${DIST_DIR}/index.html" -type f 2>/dev/null | md5sum | cut -d' ' -f1)
            if [ "$CURRENT_HASH" != "$LAST_HASH" ]; then
                LAST_HASH="$CURRENT_HASH"
                echo -e "${YELLOW}📁 检测到文件变化，重新构建...${NC}"
                "$0" || true
            fi
            sleep 10
        done
    fi
fi

exit 0
