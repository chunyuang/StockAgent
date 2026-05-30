#!/bin/bash
# =============================================
# 🔧 Nginx配置修复脚本 - 确保生产模式稳定
# 规则:
#   - :80  → 8000 (build版本, 稳定可靠)
#   - :5174 → Vite dev (仅开发时直接访问)
#   - 永远不让:80走Vite dev(缓存腐败导致白屏)
# =============================================

set -euo pipefail

NGINX_CONF="/etc/nginx/sites-enabled/stockagent"

cat > "$NGINX_CONF" << 'NGINX_EOF'
server {
    listen 80;
    server_name 172.16.16.101;

    # WebSocket
    location = /ws {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
    }

    # API接口
    location /api/ {
        proxy_pass http://localhost:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 前端 — 生产模式: 直接用build版本(8000)
    # 永远不要把:80指向Vite dev(5174)！
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX_EOF

# 验证并重载
if /usr/sbin/nginx -t 2>&1; then
    /usr/sbin/nginx -s reload
    echo "✅ Nginx已切换到生产模式(:80 → :8000)"
    echo "   Vite dev server仍可通过 :5174 直接访问(开发用)"
else
    echo "❌ Nginx配置验证失败！"
    exit 1
fi
