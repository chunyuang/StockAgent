#!/usr/bin/env python3
"""
前端 vs 后端 字段一致性检查 (v2.9.120)

检查逻辑:
1. 扫描前端Vue组件中引用的API字段名
2. 调用后端API获取实际返回结构
3. 逐字段比对，发现不匹配立即报错
4. 检查前端computed/模板中访问的属性是否在API返回中存在

运行: python3 scripts/frontend_backend_field_check.py
退出码: 0=全部一致, 1=有不一致
"""
import sys
import os
import re
import json
import asyncio
import importlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

API_BASE = "http://localhost:8000/api/v1"

# ============================================================
# 1. 定义前端组件 -> API映射
# ============================================================
COMPONENT_API_MAP = {
    "ScanInsightView": {
        "file": "frontend/src/views/scan/ScanInsightView.vue",
        "apis": [
            ("/scan-insight/architecture", "architecture"),
            ("/scan-insight/timing", "timing"),
            ("/scan-insight/strategies", "strategies"),
            ("/scan-insight/pipeline", "pipeline"),
        ],
    },
    "PerfTab": {
        "file": "frontend/src/views/monitor/PerfTab.vue",
        "apis": [
            ("/scanner/analysis", "analysis"),
        ],
    },
    "SentimentTab": {
        "file": "frontend/src/views/monitor/SentimentTab.vue",
        "apis": [
            ("/scanner/market-sentiment", "sentiment"),
            ("/scanner/sentiment-live-log?limit=5", "sentiment_live"),
        ],
    },
    "PositionRiskMatrix": {
        "file": "frontend/src/views/monitor/PositionRiskMatrix.vue",
        "apis": [
            ("/scanner/position-risk-matrix", "risk_matrix"),
        ],
    },
    "OpsTab": {
        "file": "frontend/src/views/monitor/OpsTab.vue",
        "apis": [
            ("/scanner/system-health-detail", "health"),
        ],
    },
}

# ============================================================
# 2. 扫描前端组件中的字段引用
# ============================================================
def extract_field_refs(filepath: str) -> set:
    """从Vue组件中提取模板和script中引用的字段名
    
    匹配模式:
    - {{ obj.field }} 模板插值
    - obj.field script访问
    - v-if/v-show="obj.field" 条件
    - :prop="obj.field" 绑定
    """
    refs = set()
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        return refs
    
    # 提取 computed 中的对象属性访问
    # 如 archStatus.is_running, selectedPhase.purpose
    patterns = [
        # archStatus.xxx, timing.xxx 等
        r'(?:archStatus|timing|strategies|pipeline|selectedPhase|sentimentData|riskMatrix|healthData|analysisData)\.(\w+)',
        # data.xxx (API返回的数据)
        r'(?:data|res|result|response|item|row|s|layer|phase)\.(\w+)',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, content)
        for m in matches:
            if m not in ('value', 'length', 'push', 'pop', 'slice', 'map', 'filter', 
                         'forEach', 'find', 'includes', 'indexOf', 'toString',
                         'toFixed', 'join', 'split', 'replace', 'trim', 'keys',
                         'values', 'entries', 'from', 'isArray', 'constructor',
                         'prototype', 'hasOwnProperty', 'then', 'catch', 'finally'):
                refs.add(m)
    
    return refs


def extract_specific_refs(filepath: str, var_names: list) -> dict:
    """提取指定变量的字段引用
    
    如 var_names=['archStatus'], 返回 {'archStatus': {'is_running', 'trade_date', ...}}
    """
    refs = {name: set() for name in var_names}
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        return refs
    
    for name in var_names:
        # 匹配 name.field 和 name?.field
        pattern = rf'{name}\??\.(\w+)'
        matches = re.findall(pattern, content)
        for m in matches:
            if m not in ('value', 'length', 'push', 'pop', 'slice', 'map', 'filter',
                         'forEach', 'find', 'includes', 'indexOf', 'toString',
                         'toFixed', 'join', 'split', 'replace', 'trim'):
                refs[name].add(m)
    
    return refs


# ============================================================
# 3. 调用API获取实际返回结构
# ============================================================
async def fetch_api_shape(path: str) -> dict:
    """调用API并返回其数据的字段结构(只取keys,不取值)"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE}{path}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return {"_error": f"HTTP {resp.status}"}
                data = await resp.json()
                # 取 data 字段
                if isinstance(data, dict) and 'data' in data:
                    data = data['data']
                return data if isinstance(data, dict) else {"_raw": type(data).__name__}
    except Exception as e:
        return {"_error": str(e)[:200]}


def get_nested_keys(obj: dict, prefix: str = "", depth: int = 0) -> set:
    """递归获取嵌套字典的所有键"""
    keys = set()
    if depth > 3 or not isinstance(obj, dict):
        return keys
    for k, v in obj.items():
        full = f"{prefix}.{k}" if prefix else k
        keys.add(full)
        if isinstance(v, dict):
            keys.update(get_nested_keys(v, full, depth + 1))
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            keys.update(get_nested_keys(v[0], f"{full}[]", depth + 1))
    return keys


# ============================================================
# 4. 已知的前端字段问题模式
# ============================================================
KNOWN_PATTERNS = {
    "name_cn": "后端返回name字段, 不是name_cn",
    "risk.stop_loss_pct": "后端返回risk_params数组, 不是risk.stop_loss_pct对象",
    "layer.purpose": "后端返回description, 不是purpose",
    "_scan_thread": "scanner使用_task(asyncio.Task), 不是_scan_thread",
    "scan_count": "后端不返回scan_count, 用position_ratio替代",
    "active_signals": "后端不返回active_signals",
    "circuit_breaker (bool)": "后端返回circuit_breaker是dict{trading_paused,...}, 不是bool",
    "sentiment (str)": "后端返回sentiment是dict{score,period,...}, 不是字符串",
}


def check_known_patterns(filepath: str) -> list:
    """检查已知的前端错误模式"""
    issues = []
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        return issues
    
    checks = [
        (r'\.name_cn\b', "name_cn", "后端返回name字段"),
        (r'\brisk\.stop_loss_pct\b', "risk.stop_loss_pct", "后端返回risk_params数组"),
        (r'\brisk\.take_profit_pct\b', "risk.take_profit_pct", "后端返回risk_params数组"),
        (r'\brisk\.trailing_stop_pct\b', "risk.trailing_stop_pct", "后端返回risk_params数组"),
        (r'\blayer\.purpose\b', "layer.purpose", "后端返回layer.description"),
        (r'\b_scan_thread\b', "_scan_thread", "scanner使用_task属性"),
        (r'\bs\.risk\b(?!\.)', "s.risk", "策略数据用risk_params数组, 不是risk对象"),
    ]
    
    for pattern, field, fix in checks:
        if re.search(pattern, content):
            issues.append(f"  ❌ 引用 '{field}' - {fix}")
    
    return issues


# ============================================================
# 5. 检查TS类型定义完整性
# ============================================================
def check_ts_types() -> list:
    """检查前端TS类型是否覆盖所有tab"""
    issues = []
    
    # 检查MonitorTab类型
    type_file = "frontend/src/views/monitor/useScannerMonitor.ts"
    try:
        with open(type_file, 'r') as f:
            content = f.read()
        
        # 找MonitorTab类型定义
        m = re.search(r"type MonitorTab\s*=\s*([^\n]+)", content)
        if m:
            types = m.group(1)
            required = ['guide', 'trading', 'premarket', 'scan-trace', 'review', 
                       'risk', 'sentiment', 'history', 'analysis', 'account', 'ops', 'perf']
            for t in required:
                if f"'{t}'" not in types and f'"{t}"' not in types:
                    issues.append(f"  ❌ MonitorTab类型缺少 '{t}'")
    except FileNotFoundError:
        issues.append(f"  ❌ 文件不存在: {type_file}")
    
    return issues


# ============================================================
# 6. 检查defineAsyncComponent的errorComponent
# ============================================================
def check_async_components() -> list:
    """检查异步组件是否有错误降级"""
    issues = []
    
    monitor_file = "frontend/src/views/monitor/MarketMonitorView.vue"
    try:
        with open(monitor_file, 'r') as f:
            content = f.read()
        
        # 找所有defineAsyncComponent
        imports = re.findall(r'defineAsyncComponent\s*\(\s*\(\)\s*=>\s*import\([^)]+\)\s*\)', content)
        for imp in imports:
            if 'errorComponent' not in imp and 'errorComponent' not in content:
                # 统一检查, 不逐个
                pass
        
        if 'defineAsyncComponent' in content and 'errorComponent' not in content:
            issues.append("  ⚠️  defineAsyncComponent未设置errorComponent, 组件加载失败会白屏")
    except FileNotFoundError:
        pass
    
    return issues


# ============================================================
# 7. 检查v-if空状态处理
# ============================================================
def check_empty_state(filepath: str) -> list:
    """检查组件是否有空状态处理(v-if + ElEmpty)"""
    issues = []
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        return issues
    
    # 检查是否有ElEmpty或v-if空状态
    if 'ElEmpty' not in content and 'v-if=' not in content:
        issues.append("  ⚠️  无ElEmpty/v-if空状态处理, 数据为空时可能白屏")
    
    return issues


# ============================================================
# 主函数
# ============================================================
async def main():
    print("=" * 70)
    print("前端 vs 后端 字段一致性检查 (v2.9.120)")
    print("=" * 70)
    
    all_issues = []
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # ---- 1. TS类型检查 ----
    print("\n📋 1. TypeScript类型完整性...")
    ts_issues = check_ts_types()
    if ts_issues:
        all_issues.extend(ts_issues)
        for i in ts_issues:
            print(i)
    else:
        print("  ✅ MonitorTab类型完整")
    
    # ---- 2. 异步组件错误降级 ----
    print("\n📋 2. 异步组件错误降级...")
    async_issues = check_async_components()
    if async_issues:
        all_issues.extend(async_issues)
        for i in async_issues:
            print(i)
    else:
        print("  ✅ 异步组件配置正常")
    
    # ---- 3. 已知错误模式检查 ----
    print("\n📋 3. 已知前端字段错误模式...")
    for comp_name, config in COMPONENT_API_MAP.items():
        filepath = os.path.join(base_dir, config["file"])
        issues = check_known_patterns(filepath)
        if issues:
            print(f"\n  [{comp_name}] {config['file']}:")
            all_issues.extend(issues)
            for i in issues:
                print(i)
        else:
            print(f"  ✅ {comp_name}: 无已知错误模式")
    
    # ---- 4. API字段对比 ----
    print("\n📋 4. API返回字段 vs 前端引用...")
    for comp_name, config in COMPONENT_API_MAP.items():
        filepath = os.path.join(base_dir, config["file"])
        print(f"\n  [{comp_name}]:")
        
        for api_path, var_name in config["apis"]:
            # 获取API返回
            api_data = await fetch_api_shape(api_path)
            if "_error" in api_data:
                print(f"    ❌ {api_path} -> {api_data['_error']}")
                all_issues.append(f"  ❌ {comp_name}: {api_path} 调用失败: {api_data['_error']}")
                continue
            
            # 获取API返回的所有嵌套键
            api_keys = get_nested_keys(api_data)
            
            # 提取前端引用
            # 对不同变量名提取
            var_list = [var_name]
            if var_name == "architecture":
                var_list.extend(["archStatus"])
            elif var_name == "timing":
                var_list.extend(["selectedPhase", "timingSessions"])
            elif var_name == "strategies":
                var_list.extend(["strategyList"])
            elif var_name == "pipeline":
                var_list.extend(["pipelineLayers"])
            
            front_refs = extract_specific_refs(filepath, var_list)
            
            # 对比
            api_key_set = set()
            for k in api_keys:
                # 取最后一段
                parts = k.replace("[]", "").split(".")
                api_key_set.add(parts[-1])
                api_key_set.add(parts[0])  # 顶层key
            
            mismatch = []
            for var, refs in front_refs.items():
                for ref in refs:
                    if ref not in api_key_set and ref not in ('_error', '_raw'):
                        # 检查是否在嵌套key中
                        found = False
                        for ak in api_keys:
                            if ref in ak:
                                found = True
                                break
                        if not found:
                            mismatch.append(f"{var}.{ref}")
            
            if mismatch:
                msg = f"    ❌ {api_path} -> 前端引用了API不存在的字段: {', '.join(mismatch[:5])}"
                print(msg)
                all_issues.append(f"  ❌ {comp_name}: {msg}")
            else:
                print(f"    ✅ {api_path} -> 字段匹配")
    
    # ---- 5. 空状态处理 ----
    print("\n📋 5. 组件空状态处理...")
    for comp_name, config in COMPONENT_API_MAP.items():
        filepath = os.path.join(base_dir, config["file"])
        issues = check_empty_state(filepath)
        if issues:
            all_issues.extend(issues)
            for i in issues:
                print(f"  [{comp_name}] {i}")
        else:
            print(f"  ✅ {comp_name}: 有空状态处理")
    
    # ---- 汇总 ----
    print("\n" + "=" * 70)
    if all_issues:
        print(f"❌ 发现 {len(all_issues)} 个问题:")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
        print(f"\n退出码: 1")
        sys.exit(1)
    else:
        print("✅ 全部检查通过, 前后端字段一致")
        print(f"\n退出码: 0")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
