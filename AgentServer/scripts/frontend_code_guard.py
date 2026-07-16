#!/usr/bin/env python3
"""前端代码路径守卫 — 检测 fetch()/API URL 不一致问题

基于 2026-06-16 的教训: AccountTab 用了 raw fetch('/scanner/...') 
而漏掉 /api/v1 前缀, 导致 404 → 账户数据全0 + 风控❌

检查项:
1. raw fetch() 调用是否带 /api/v1 前缀
2. api.get()/api.post() 调用的 URL 是否以 / 开头(baseURL 会自动拼接)
3. 硬编码的 localhost 端口/地址
4. 后端 API 端点是否全部可达(200)
5. 前端调用的 API 路径在后端是否有对应路由

退出码: 0=健康, 1=有问题
"""
import re
import sys
import requests
from pathlib import Path

FRONTEND_SRC = "/root/.openclaw/workspace/StockAgent/frontend/src"
API_BASE = "http://localhost:8000/api/v1"


def check_raw_fetch_prefix():
    """检查1: raw fetch() 调用必须带 /api/v1 前缀"""
    issues = []
    
    for vue_file in Path(FRONTEND_SRC).rglob("*.vue"):
        content = vue_file.read_text()
        lines = content.split("\n")
        
        for i, line in enumerate(lines, 1):
            # Match: fetch('/something') or fetch(`/something`)
            m = re.search(r"fetch\(['\"`](/[^'\"]+)['\"`]", line)
            if not m:
                continue
            url = m.group(1)
            # Skip allowed patterns
            if url.startswith("/api/v1/"):
                continue
            if url.startswith("/config") or url.startswith("/__"):
                continue
            # This is a raw fetch without /api/v1!
            rel_path = vue_file.relative_to(FRONTEND_SRC)
            issues.append(f"{rel_path}:{i} fetch('{url}') 缺少 /api/v1 前缀")
    
    return issues


def check_api_util_urls():
    """检查2: api.get()/api.post() 的 URL 应以 / 开头(拼接 baseURL)"""
    issues = []
    
    for ts_file in Path(FRONTEND_SRC).rglob("*.ts"):
        content = ts_file.read_text()
        lines = content.split("\n")
        
        for i, line in enumerate(lines, 1):
            # Match: api.get('http://...') — 绝对URL, 绕过 baseURL
            if re.search(r"api\.(get|post|put|delete)\(['\"`](https?://)", line):
                rel_path = ts_file.relative_to(FRONTEND_SRC)
                issues.append(f"{rel_path}:{i} 绝对URL, 绕过 baseURL: {line.strip()[:80]}")
    
    return issues


def check_hardcoded_hosts():
    """检查3: 硬编码的 localhost 端口/地址"""
    issues = []
    forbidden = ["localhost:8765", "localhost:50051", "localhost:5174", ":8000/api"]
    
    for src_file in Path(FRONTEND_SRC).rglob("*.ts"):
        if ".d.ts" in str(src_file):
            continue
        content = src_file.read_text()
        lines = content.split("\n")
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            for pattern in forbidden:
                if pattern in line:
                    rel_path = src_file.relative_to(FRONTEND_SRC)
                    issues.append(f"{rel_path}:{i} 硬编码 '{pattern}': {line.strip()[:80]}")
    
    return issues


def check_backend_api_reachable():
    """检查4: 后端 API 端点可达性"""
    issues = []
    
    # Key endpoints that the frontend monitor uses (GET only)
    endpoints = [
        "/scanner/status",
        "/scanner/health",
        "/scanner/analysis?period=30d",
        "/scanner/position-risk-levels",
        "/scanner/position-risk-matrix",
        "/scanner/market-sentiment",
        "/scanner/system-health-detail",
        "/scanner/strategy-performance",
        "/scanner/scan-traces?limit=5",
        "/scanner/sentiment-timeline",
        "/scanner/timeline/history?days=1",
        "/scanner/auto-trades?limit=10",
        "/scanner/limit-pools",
        "/scanner/sentiment-strategy-matrix",
        "/scanner/execution-quality",
        "/scanner/discipline-check",
        "/scanner/trade-attribution",
        "/scanner/historical-review",
        "/scanner/review-hero",
        "/scanner/param-snapshot",
        "/scanner/param-drift",
        "/scanner/daily-report",
        "/scanner/scan-config",
        "/scanner/strategy-params-compare",
        "/scanner/performance-history?days=30",
        # Backtest
        "/backtest/ultra-short/history",
        # Stock
        "/stocks/search?keyword=000001",
        # Market

    ]
    
    unreachable = []
    for ep in endpoints:
        try:
            r = requests.get(f"{API_BASE}{ep}", timeout=5)
            if r.status_code == 404:
                unreachable.append(f"{ep} → 404")
            elif r.status_code >= 500:
                unreachable.append(f"{ep} → {r.status_code}")
        except Exception as e:
            unreachable.append(f"{ep} → {type(e).__name__}")
    
    if unreachable:
        issues.append(f"{len(unreachable)} 个 API 不可达: {unreachable[:5]}")
    
    return issues



def check_frontend_api_routes():
    """检查5: 前端调用的 API 路径在后端是否有对应路由
    
    只检查单引号/双引号的纯字面量路径, 不检查模板字面量(含${var}的)
    """
    issues = []
    api_paths = set()
    
    for src_file in list(Path(FRONTEND_SRC).rglob("*.ts")) + list(Path(FRONTEND_SRC).rglob("*.vue")):
        if ".d.ts" in str(src_file) or "node_modules" in str(src_file):
            continue
        text = src_file.read_text()
        # Only match api.get('/...') or api.get("/...") with simple path
        # NOT backtick template literals
        for m in re.finditer(r'''api\.(get|post|put|delete)\(['"](/[a-z0-9/_-]+)['"]\)''', text):
            path = m.group(2).split("?")[0]
            if path.endswith(('/start', '/stop', '/reset', '/trade', '/sell-all',
                             '/emergency-liquidate', '/run-backtest', '/daily-settlement',
                             '/circuit-breaker/pause', '/circuit-breaker/reset')):
                continue
            api_paths.add(path)
    
    if not api_paths:
        print("  ⚪ 未找到可解析的 API 路径")
        return []
    
    # Check against backend
    missing = []
    for path in sorted(api_paths):
        try:
            r = requests.get(f"{API_BASE}{path}", timeout=3)
            if r.status_code == 404:
                missing.append(path)
        except:
            pass
    
    if missing:
        issues.append(f"前端调用的 {len(missing)} 个 API 路径后端 404: {missing}")
    else:
        print(f"  ✅ {len(api_paths)} 个前端 API 路径后端均有路由")
    
    return issues
def main():
    all_issues = []
    
    print("=" * 60)
    print("🔍 前端代码路径守卫报告")
    print(f"   时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    # 检查1: raw fetch 前缀
    print("\n🌐 1. raw fetch() URL 前缀检查")
    print("-" * 40)
    issues = check_raw_fetch_prefix()
    if issues:
        for i in issues:
            print(f"  🔴 {i}")
        all_issues.extend(issues)
    else:
        print("  ✅ 所有 raw fetch() 都带 /api/v1 前缀")
    
    # 检查2: api 工具方法 URL
    print("\n🔗 2. api.get()/api.post() URL 检查")
    print("-" * 40)
    issues = check_api_util_urls()
    if issues:
        for i in issues:
            print(f"  🔴 {i}")
        all_issues.extend(issues)
    else:
        print("  ✅ 无绝对URL绕过 baseURL")
    
    # 检查3: 硬编码地址
    print("\n🏠 3. 硬编码地址检查")
    print("-" * 40)
    issues = check_hardcoded_hosts()
    if issues:
        for i in issues:
            print(f"  ⚠️  {i}")
        all_issues.extend(issues)
    else:
        print("  ✅ 无硬编码 localhost 端口")
    
    # 检查4: API 可达性
    print("\n📡 4. 后端 API 端点可达性")
    print("-" * 40)
    issues = check_backend_api_reachable()
    if issues:
        for i in issues:
            print(f"  🔴 {i}")
        all_issues.extend(issues)
    else:
        print("  ✅ 全部 API 端点可达")
    
    # 检查5: 前后端路由一致性
    print("\n🔀 5. 前后端路由一致性")
    print("-" * 40)
    issues = check_frontend_api_routes()
    if issues:
        for i in issues:
            print(f"  🔴 {i}")
        all_issues.extend(issues)
    else:
        print("  ✅ 前端调用的 API 路径后端均有路由")
    
    # 总结
    print("\n" + "=" * 60)
    if all_issues:
        print(f"🔴 发现 {len(all_issues)} 个问题:")
        for i, issue in enumerate(all_issues, 1):
            print(f"   {i}. {issue}")
    else:
        print("✅ 全部检查通过, 前端代码路径健康!")
    
    status = "unhealthy" if all_issues else "healthy"
    print(f"\n📊 STATUS: {status}")
    
    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main())
