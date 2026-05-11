#!/bin/bash
fuser -k 8000/tcp 2>/dev/null || true
# 定位项目根目录（相对于脚本位置）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sleep 2
cd "$SCRIPT_DIR"
python AgentServer/main.py web --host 0.0.0.0 --port 8000 > logs/web_node.log 2>&1
