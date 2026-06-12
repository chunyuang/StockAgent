#!/bin/bash
# 持久化的 StockAgent 监控页面浏览器
# - supervisor 监管,崩了自动重启
# - 用 --app 模式: 无地址栏/工具栏,纯净监控视图
# - persistent profile: 记住登录/cookies/localStorage
# - 自动检测后端可达性,不可达时延迟启动

export DISPLAY=:99.0
export HOME=/home/browser
export LANG=zh_CN.UTF-8
export XDG_RUNTIME_DIR=/tmp/runtime-browser
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

URL="http://localhost:8000/monitor"
PROFILE_DIR="/home/browser/.config/stockagent-monitor"
mkdir -p "$PROFILE_DIR"
chown -R browser:browser "$PROFILE_DIR" 2>/dev/null || true

# 等待 X server
for i in $(seq 1 60); do
    xdpyinfo -display :99 >/dev/null 2>&1 && break
    sleep 1
done

# 等待后端可达(最多 120 秒)
for i in $(seq 1 60); do
    if curl -sf "$URL" > /dev/null 2>&1; then
        echo "[monitor-browser] 后端可达,启动 Chrome"
        break
    fi
    echo "[monitor-browser] 后端不可达,等待... ($i/60)"
    sleep 2
done

# 启动 Chrome (--app 模式 = 无浏览器UI,只显示页面)
exec google-chrome \
    --no-sandbox \
    --user-data-dir="$PROFILE_DIR" \
    --app="$URL" \
    --start-maximized \
    --no-first-run \
    --no-default-browser-check \
    --disable-sync \
    --disable-features=TranslateUI \
    --noerrdialogs \
    --disable-session-crashed-bubble \
    --disable-infobars \
    --disable-dev-shm-usage \
    --window-position=0,0 \
    --window-size=1920,1080
