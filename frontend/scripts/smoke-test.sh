#!/bin/bash
# ================================================================
# Frontend Smoke Test - 运行时烟雾测试
#
# 用Playwright加载每个Tab, 检查console是否有Error级别的报错
# 拦截"today is not defined"这类运行时才能发现的bug
#
# 使用: bash scripts/smoke-test.sh [URL]
# ================================================================

set -euo pipefail
URL="${1:-http://localhost:8000/monitor}"
ERRORS=0

echo "🔥 Frontend Smoke Test"
echo "======================="
echo "Target: $URL"

python3 << 'PYEOF'
import sys
import time
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/monitor"

TABS = [
    ("实盘交易", "trading"),
    ("盘前竞价", "premarket"),
    ("扫描追踪", "scan-trace"),
    ("每日复盘", "review"),
    ("风控矩阵", "risk"),
    ("情绪周期", "sentiment"),
    ("历史记录", "history"),
    ("数据分析", "analysis"),
    ("账户资产", "account"),
    ("系统运维", "ops"),
]

errors_found = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    
    # Collect console errors
    console_errors = []
    def on_console(msg):
        if msg.type == "error":
            console_errors.append(f"[{msg.type}] {msg.text[:200]}")
    page.on("console", on_console)
    
    page.goto(URL, wait_until="networkidle", timeout=30000)
    time.sleep(3)
    
    print(f"\n  页面加载完成, 开始逐Tab测试...")
    
    for tab_name, tab_id in TABS:
        # Clear previous errors
        prev_count = len(console_errors)
        
        # Click the tab
        try:
            tab_btn = page.locator(".tab-btn").filter(has_text=tab_name)
            if tab_btn.count() > 0:
                tab_btn.first.click()
                time.sleep(4)
                
                # Check for new console errors
                new_errors = console_errors[prev_count:]
                if new_errors:
                    for err in new_errors:
                        # Skip known benign errors
                        if any(skip in err for skip in ['WebSocket', 'favicon', 'net::', 'ResizeObserver']):
                            continue
                        errors_found.append((tab_name, err))
                        print(f"  ❌ [{tab_name}] {err[:100]}")
                else:
                    print(f"  ✅ [{tab_name}] 无错误")
            else:
                print(f"  ⚠️  [{tab_name}] Tab按钮未找到")
        except Exception as e:
            errors_found.append((tab_name, str(e)))
            print(f"  ❌ [{tab_name}] 异常: {e}")
    
    browser.close()

if errors_found:
    print(f"\n❌ 发现 {len(errors_found)} 个运行时错误:")
    for tab, err in errors_found:
        print(f"  [{tab}] {err[:150]}")
    sys.exit(1)
else:
    print(f"\n✅ 所有Tab运行时烟雾测试通过")
    sys.exit(0)
PYEOF

