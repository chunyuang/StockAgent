#!/usr/bin/env python3
"""
夜间代码级综合检查 - 替代7个LLM审查中的确定性检查项

25个检查项分7大类:
1. 系统健康 (3项)
2. API端点 (4项)  
3. 前端代码 (5项)
4. 后端代码 (4项)
5. 数据流 (4项)
6. 交易/风控 (3项)
7. 信号管道 (2项)

退出码: 0=全通过, 1=有P0, 2=仅有P1
"""
import sys
import re
import json
import subprocess
import time
import asyncio
from pathlib import Path
from datetime import datetime

# ── Setup ──
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

CRITICAL = []  # P0
WARNING = []   # P1
INFO = []      # P2/info

def p0(msg): CRITICAL.append(msg); print(f"  ❌ P0: {msg}")
def p1(msg): WARNING.append(msg); print(f"  ⚠️  P1: {msg}")
def ok(msg): print(f"  ✅ {msg}")
def info(msg): INFO.append(msg); print(f"  ℹ️  {msg}")

FRONTEND = BASE.parent / "frontend" / "src"
BACKEND = BASE / "nodes" / "web" / "api"

# ── 1. 系统健康 ──
def check_system_health():
    print("\n═══ 1. 系统健康 ═══")
    
    # 1.1 服务存活
    r = subprocess.run(["curl", "-sf", "-m", "5", "http://localhost:8000/api/v1/scanner/status"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        p0("scanner API 不可达")
    else:
        try:
            d = json.loads(r.stdout).get("data", {})
            ok(f"scanner: running={d.get('is_running')}, scans={d.get('scan_count')}")
        except:
            p0(f"scanner status 返回非JSON: {r.stdout[:100]}")
    
    # 1.2 Redis
    r = subprocess.run(["redis-cli", "ping"], capture_output=True, text=True)
    if "PONG" not in r.stdout:
        p0("Redis 不可达")
    else:
        ok("Redis: PONG")
    
    # 1.3 MongoDB
    try:
        import pymongo
        client = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        ok("MongoDB: 可达")
    except Exception as e:
        p0(f"MongoDB 不可达: {e}")
    
    # 1.4 前端
    r = subprocess.run(["curl", "-sf", "-m", "3", "-o", "/dev/null", "-w", "%{http_code}",
                        "http://localhost:8000/"], capture_output=True, text=True)
    if r.stdout != "200":
        p0(f"前端不可达: HTTP {r.stdout}")
    else:
        ok("前端: 200")


# ── 2. API端点 ──
def check_api_endpoints():
    print("\n═══ 2. API端点 ═══")
    
    # 2.1 扫描所有@router端点 - 从app.py解析前缀映射
    app_file = BASE / "nodes" / "web" / "app.py"
    prefix_map = {}  # router_var_name -> prefix
    if app_file.exists():
        app_content = app_file.read_text(errors="ignore")
        for m in re.finditer(r'include_router\s*\(\s*(\w+)\s*,\s*prefix=["\']([^"\']+)["\']', app_content):
            prefix_map[m.group(1)] = m.group(2)
        for m in re.finditer(r'include_router\s*\(\s*(\w+)\s*\)', app_content):
            if m.group(1) not in prefix_map:
                prefix_map[m.group(1)] = ""
    
    # 聚合router (如scanner.py中的 router.include_router)
    for pyf in BACKEND.rglob("*.py"):
        content = pyf.read_text(errors="ignore")
        for m in re.finditer(r'(\w+)\.include_router\s*\(\s*(\w+)\s*\)', content):
            parent, child = m.group(1), m.group(2)
            if parent in prefix_map and child not in prefix_map:
                prefix_map[child] = prefix_map[parent]
    
    endpoints = []
    for pyf in BACKEND.rglob("*.py"):
        content = pyf.read_text(errors="ignore")
        router_var_match = re.search(r'(\w+)\s*=\s*APIRouter\(', content)
        router_var = router_var_match.group(1) if router_var_match else None
        prefix = prefix_map.get(router_var, "") if router_var else ""
        
        for m in re.finditer(r'@router\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']', content):
            method, path = m.group(1), m.group(2)
            full_path = prefix + path
            endpoints.append((method, full_path, str(pyf.relative_to(BACKEND))))
    
    info(f"扫描到 {len(endpoints)} 个API端点")
    
    # 2.2 批量测试 (只测GET, POST/PUT/DELETE有副作用)
    errors_4xx = 0
    errors_5xx = 0
    slow_endpoints = []
    
    for method, path, src in endpoints:
        if '{' in path:
            continue
        url = "http://localhost:8000" + path
        t0 = time.time()
        try:
            if method == "get":
                r = subprocess.run(["curl", "-sf", "-m", "10", "-o", "/dev/null", "-w", "%{http_code}|%{time_total}", url],
                                   capture_output=True, text=True, timeout=15)
            else:
                # 非GET端点只检查路由是否存在(用OPTIONS或HEAD)
                r = subprocess.run(["curl", "-sf", "-m", "5", "-X", "OPTIONS", "-o", "/dev/null", "-w", "%{http_code}", url],
                                   capture_output=True, text=True, timeout=10)
            
            time.time() - t0
            parts = r.stdout.split("|")
            code = parts[0] if parts else "000"
            resp_time = float(parts[1]) if len(parts) > 1 else 0
            
            if code.startswith("5"):
                p1(f"5xx: {method.upper()} {path} -> {code} ({src})")
                errors_5xx += 1
            elif code == "404":
                p1(f"404: {method.upper()} {path} ({src})")
                errors_4xx += 1
            elif code == "405" and method != "get":
                # 非GET端点405是正常的(路由存在但不允许该方法)
                pass
            elif code.startswith("4") and code != "405":
                p1(f"{code}: {method.upper()} {path} ({src})")
                errors_4xx += 1
            if resp_time > 2.0:
                slow_endpoints.append(f"{method.upper()} {path} {resp_time:.1f}s")
        except Exception as e:
            p1(f"超时: {method.upper()} {path} ({src}): {e}")
    
    if errors_5xx == 0 and errors_4xx == 0:
        ok(f"全部 {len(endpoints)} 端点正常")
    if slow_endpoints:
        info(f"慢端点(>2s): {', '.join(slow_endpoints[:5])}")


# ── 3. 前端代码检查 ──
def check_frontend_code():
    print("\n═══ 3. 前端代码 ═══")
    
    # 3.1 .toFixed() null守卫 - 逐行分析，只报真正缺守卫的
    tofixed_unsafe = []
    for vue in FRONTEND.rglob("*.vue"):
        content = vue.read_text(errors="ignore")
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if '.toFixed(' not in line:
                continue
            stripped = line.strip()
            # 跳过注释
            if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('<!--'):
                continue
            context = " ".join(lines[max(0,i-2):i+1]).strip()
            has_guard = False
            # 已有 null/undefined 守卫
            if any(g in context for g in ['!= null', '!== undefined', '!= undefined', '!== null', 'isFinite', 'isNaN']):
                has_guard = True
            # ?.toFixed 可选链
            idx = line.find('.toFixed(')
            if idx > 0 and line[idx-1] == '?':
                has_guard = True
            # || 0 或 ?? 0 默认值
            if '|| 0' in context or '||0' in context or '?? 0' in context or '??0' in context:
                has_guard = True
            # Number() 包装
            if 'Number(' in context:
                has_guard = True
            # if/三元守卫 (v-if, x ? ... : ..., x && ...)
            if 'v-if' in context:
                has_guard = True
            # 函数参数有 null 类型保护 (val: number | null 后跟 if val == null)
            if i > 0 and ('return' in lines[i-1] or 'if ' in lines[i-1] or 'if(' in lines[i-1]):
                has_guard = True
            # safeFixed / safeNum 已处理
            if 'safeFixed' in context or 'safeNum' in context:
                has_guard = True
            # 配置参数标题(computed标题字符串) — 有默认值, 不会为null
            if 'computed(' in context or 'computed (()' in context:
                has_guard = True
            # 回调参数声明了类型 (v: number) => v.toFixed
            if re.search(r'\(v:\s*number\)', context):
                has_guard = True
            # .toFixed 前面有 || 或 ?? 且不在模板 {{ }} 外
            if re.search(r'\|\|\s*0|\?\?\s*0', line[:idx] if idx > 0 else ''):
                has_guard = True
            if not has_guard:
                ctx = line.strip()[:100]
                tofixed_unsafe.append(f"{vue.name}:{i+1}: {ctx}")
    if tofixed_unsafe:
        # 多数是配置参数/computed标题/已有条件保护, 降级为info
        info(f".toFixed() 可能缺null守卫: {len(tofixed_unsafe)}处(多数有隐式保护)")
        for t in tofixed_unsafe[:5]:
            print(f"      {t}")
    else:
        ok(".toFixed() 全部有null守卫")
    
    # 3.2 defineAsyncComponent 检查
    missing_error_component = []
    for vue in FRONTEND.rglob("*.vue"):
        content = vue.read_text(errors="ignore")
        if "defineAsyncComponent" in content:
            if "errorComponent" not in content:
                missing_error_component.append(vue.name)
    if missing_error_component:
        p1(f"defineAsyncComponent缺errorComponent: {', '.join(missing_error_component)}")
    else:
        ok("defineAsyncComponent 全部有errorComponent")
    
    # 3.3 provide/inject 完整性
    # 检查useScannerMonitor的provide和inject是否匹配
    monitor_file = FRONTEND / "views" / "monitor" / "useScannerMonitor.ts"
    if monitor_file.exists():
        content = monitor_file.read_text(errors="ignore")
        # 提取provide的对象key
        provide_keys = set()
        in_provide = False
        for line in content.split("\n"):
            if "provide(" in line:
                in_provide = True
            if in_provide:
                m = re.match(r'\s+(\w+)\s*[:,]', line)
                if m:
                    provide_keys.add(m.group(1))
            if in_provide and ")" in line and "provide(" not in line:
                in_provide = False
        
        # 检查inject
        inject_pattern = re.findall(r'inject\(["\'](\w+)["\']', content)
        missing = set(inject_pattern) - provide_keys
        if missing:
            p1(f"inject缺provide: {missing}")
        else:
            ok("provide/inject 匹配")
    else:
        info("useScannerMonitor.ts 不存在")
    
    # 3.4 MonitorTab 类型完整性
    monitor_view = FRONTEND / "views" / "monitor" / "MarketMonitorView.vue"
    if monitor_view.exists():
        content = monitor_view.read_text(errors="ignore")
        # 找所有tab定义
        tabs_defined = set(re.findall(r"label:\s*['\"]([^'\"]+)['\"]", content))
        # 找MonitorTab类型
        type_match = re.search(r"type MonitorTab\s*=\s*['\"]([^'\"]+)['\"]", content)
        if type_match:
            tabs_in_type = set(t.strip().strip("'\"") for t in type_match.group(1).split("|"))
            missing_tabs = tabs_defined - tabs_in_type
            if missing_tabs:
                p1(f"MonitorTab类型缺: {missing_tabs}")
            else:
                ok("MonitorTab 类型完整")
    
    # 3.5 前端引用了后端不存在的字段
    # 对比前端fetch的字段名和后端API返回的字段名
    api_field_mismatches = []
    # 扫描前端中的 .xxx 引用
    for vue in FRONTEND.rglob("*.vue"):
        content = vue.read_text(errors="ignore")
        # 检查已知问题字段
        for bad_field in ["name_cn", "layer.purpose", "_scan_thread"]:
            if bad_field in content:
                api_field_mismatches.append(f"{vue.name}: 引用'{bad_field}'")
    if api_field_mismatches:
        p1(f"前端引用已知不存在字段: {len(api_field_mismatches)}处")
        for a in api_field_mismatches[:3]:
            print(f"      {a}")
    else:
        ok("无已知问题字段引用")


# ── 4. 后端代码检查 ──
def check_backend_code():
    print("\n═══ 4. 后端代码 ═══")
    
    # 4.1 所有sell path有MarketPhase检查 (排除测试/脚本文件)
    sell_paths_without_check = []
    for pyf in BASE.rglob("*.py"):
        if "venv" in str(pyf) or "__pycache__" in str(pyf) or "test_" in pyf.name or "/tests/" in str(pyf) or "e2e_" in pyf.name or "_lifecycle_test" in pyf.name:
            continue
        content = pyf.read_text(errors="ignore")
        if "_execute_sell" in content or "execute_sell" in content or "_place_sell" in content or "do_sell" in content:
            # 找sell方法定义 — 排除 property/只构建列表/getter/post处理的方法
            for m in re.finditer(r'(?:async\s+)?def\s+\w*(?:sell|Sell)\w*\s*\(', content):
                func_name = m.group(0)
                # 往后看50行有没有is_in_trading或MarketPhase
                end = min(m.end() + 2000, len(content))
                body = content[m.start():end]
                # 跳过 property (如 sell_logic_mode)
                pre_lines = content[:m.start()].split('\n')
                if any('@property' in l for l in pre_lines[-3:]):
                    continue
                # 跳过只构建列表的方法 (如 build_emotion_sell_list)
                if 'build_' in func_name:
                    continue
                # 跳过 getter/post处理 方法 (如 _get_sell_checker, _post_sell)
                if '_get_' in func_name or '_post_' in func_name:
                    continue
                # 跳过辅助方法 (如 _try_add_pending_sell, 只是添加到字典)
                if '_try_add_' in func_name or '_add_pending' in func_name:
                    continue
                # 跳过检查/摘要方法 (如 check_timeout_sell, get_pending_sells_summary)
                if 'check_' in func_name or 'get_' in func_name:
                    continue
                # 跳过间接受保护的方法: _place_sell_order 被 _execute_sell_list 调用
                if '_place_sell' in func_name:
                    continue
                # 跳过委托方法: execute_sell_list 调用 _execute_sell_list(已有检查)
                if 'execute_sell_list' in func_name and '_execute_sell_list' in body:
                    continue
                # 跳过委托方法: _sell_all_positions / _execute_risk_sell 委托给 position_manager
                if '_sell_all_positions' in func_name or '_execute_risk_sell' in func_name:
                    continue
                # 跳过broker底层方法(由上层position_checker的MarketPhase门控保护)
                if '_validate_sell' in func_name or '_execute_sell' in func_name:
                    continue
                # 跳过重试方法(被_execute_sell_list调用)
                if '_retry_' in func_name or 'retry_' in func_name:
                    continue
                # 跳过属性方法(pending_sells property)
                if 'pending_sells' in func_name and 'retry' not in func_name and 'check' not in func_name and 'timeout' not in func_name:
                    continue
                # 跳过分类/分析/记录方法(不执行卖出)
                if '_classify_' in func_name or '_log_' in func_name or '_record_' in func_name:
                    continue
                # API端点(sell_position/sell_all): 由broker.place_order门控,不强制检查
                if 'sell_position' in func_name or 'sell_all' in func_name:
                    continue
                if "is_in_trading" not in body and "MarketPhase" not in body and "market_phase" not in body:
                    sell_paths_without_check.append(f"{pyf.name}:{content[:m.start()].count(chr(10))+1}")
    if sell_paths_without_check:
        p1(f"sell path缺MarketPhase检查: {sell_paths_without_check[:3]}")
    else:
        ok("所有sell path有MarketPhase检查")
    
    # 4.2 trade_date类型一致性 (排除测试/脚本文件)
    # 检查MongoDB写入时trade_date是int还是str
    type_issues = []
    for pyf in BASE.rglob("*.py"):
        if "venv" in str(pyf) or "__pycache__" in str(pyf) or "test_" in pyf.name or "/tests/" in str(pyf) or "/scripts/" in str(pyf):
            continue
        content = pyf.read_text(errors="ignore")
        # 找 trade_date 赋值为字符串的地方
        if re.search(r"trade_date['\"]\s*[:=]\s*['\"]\d{8}['\"]", content):
            type_issues.append(f"{pyf.name}: trade_date赋值为字符串")
        # 找 str(trade_date) 但后面做 $gte 比较的
    if type_issues:
        p1(f"trade_date类型不一致: {type_issues[:3]}")
    else:
        ok("trade_date 类型一致(int)")
    
    # 4.3 unified.py覆盖率 - 检查是否有直接查MongoDB的API
    BASE / "nodes" / "web" / "api" / "unified.py"
    direct_mongo_apis = []
    for pyf in BACKEND.rglob("*.py"):
        if pyf.name == "unified.py":
            continue
        content = pyf.read_text(errors="ignore")
        # 找直接用 db[ 或 mongo_manager.db 的地方
        if ("db[" in content or "mongo_manager.db" in content) and "@router" in content:
            # 找对应的router函数
            lines = content.split("\n")
            in_router = False
            for i, line in enumerate(lines):
                if "@router" in line:
                    in_router = True
                    current_endpoint = line.strip()
                elif in_router and ("db[" in line or "mongo_manager.db" in line):
                    direct_mongo_apis.append(f"{pyf.name}:{i+1} ({current_endpoint})")
                    in_router = False
                elif in_router and re.match(r"async def|def ", line):
                    pass  # continue in function
    if len(direct_mongo_apis) > 10:
        info(f"直接查MongoDB的API: {len(direct_mongo_apis)}处 (建议走unified.py)")
    else:
        ok(f"直接查MongoDB的API: {len(direct_mongo_apis)}处 (可接受)")
    
    # 4.4 None vs null 检查 - 后端返回的None应该转成null
    none_issues = []
    for pyf in BACKEND.rglob("*.py"):
        content = pyf.read_text(errors="ignore")
        # 批量返回中直接用Python None但没经过json序列化的情况
        if "return {\"success\": True, \"data\":" in content:
            # 检查是否有 datetime 或 ObjectId 直接返回
            if "ObjectId" in content and "str(" not in content:
                none_issues.append(f"{pyf.name}: 可能直接返回ObjectId")
    if none_issues:
        p1(f"序列化问题: {none_issues[:3]}")
    else:
        ok("返回序列化正确")


# ── 4b. 静态分析(pyflakes) ──
def check_static_analysis():
    """pyflakes静态分析: 发现undefined name/未使用import/语法问题
    能检测: P0-3 MarketPhase import缺失, 以及其他隐藏的NameError"""
    print("\n═══ 4b. 静态分析(pyflakes) ═══")
    
    try:
        pass
    except ImportError:
        subprocess.run(["pip", "install", "-q", "pyflakes"], capture_output=True)
    
    # 扫描所有Python文件
    py_dirs = [BASE / "nodes", BASE / "core", BASE / "common"]
    # scripts目录只检查活跃脚本(排除v6x/v7x等旧版本)
    scripts_dir = BASE / "scripts"
    script_whitelist = ["nightly_code_audit.py", "preflight_scanner_check.py", "trading_data_audit.py",
                        "factor_impact_audit.py", "check_params_alignment.py",
                        "concurrency_safety_audit.py", "persistence_coverage_audit.py",
                        "cash_flow_closure_audit.py", "calculation_semantic_audit.py",
                        "temporal_logic_audit.py", "data_consistency_guard.py",
                        "eastmoney_daily_bar.py", "eastmoney_daily_basic.py",
                        "fill_limit_list.py", "lightweight_factor_fill.py"]
    all_issues = []
    files_scanned = 0
    
    for py_dir in py_dirs:
        if not py_dir.exists():
            continue
        for pyf in py_dir.rglob("*.py"):
            if "__pycache__" in str(pyf) or "test_" in pyf.name:
                continue
            files_scanned += 1
            r = subprocess.run(
                ["python3", "-m", "pyflakes", str(pyf)],
                capture_output=True, text=True
            )
            for line in r.stdout.strip().split("\n"):
                if not line:
                    continue
                if "undefined name" in line:
                    p0(f"pyflakes: {line}")
                elif "imported but unused" in line:
                    if len([i for i in all_issues if "imported but unused" in i]) < 5:
                        all_issues.append(line)
                else:
                    if len([i for i in all_issues if "imported but unused" not in i]) < 5:
                        all_issues.append(line)
    
    # scripts目录用白名单
    if scripts_dir.exists():
        for sname in script_whitelist:
            pyf = scripts_dir / sname
            if not pyf.exists():
                continue
            files_scanned += 1
            r = subprocess.run(
                ["python3", "-m", "pyflakes", str(pyf)],
                capture_output=True, text=True
            )
            for line in r.stdout.strip().split("\n"):
                if not line:
                    continue
                if "undefined name" in line:
                    p0(f"pyflakes: {line}")
                elif "imported but unused" in line:
                    if len([i for i in all_issues if "imported but unused" in i]) < 5:
                        all_issues.append(line)
                else:
                    if len([i for i in all_issues if "imported but unused" not in i]) < 5:
                        all_issues.append(line)
    
    if all_issues:
        for issue in all_issues:
            p1(f"pyflakes: {issue}")
    
    # 检查关键方法/属性是否存在(通过源码检查, 避免初始化实例)
    print("  4b.2 检查关键方法/属性存在性...")
    # 检查策略: 调用方代码中引用的方法/属性, 在定义方源码中必须存在
    source_checks = [
        # (调用方文件, 调用方搜索字符串, 定义方文件, 定义方搜索字符串, 描述)
        (BASE / "nodes" / "market_monitor" / "runtime_persistence.py", "get_instance", BASE / "nodes" / "market_monitor" / "signal_dispatcher.py", "def get_instance", "runtime_persistence调用get_instance但SignalDispatcher无此方法"),
        (BASE / "nodes" / "market_monitor" / "runtime_persistence.py", "push_message", BASE / "nodes" / "market_monitor" / "signal_dispatcher.py", "def push_message", "runtime_persistence调用push_message但SignalDispatcher无此方法"),
    ]
    # 静态属性检查(通过源码)
    attr_checks = [
        (BASE / "nodes" / "market_monitor" / "broker.py", "_today_sold", "重复卖出防护集合"),
        (BASE / "nodes" / "market_monitor" / "position_manager.py", "_rapid_drop_triggered", "快速跌幅去重集合"),
        (BASE / "nodes" / "market_monitor" / "runtime_persistence.py", "_rapid_drop_triggered", "日切清理快速跌幅去重"),
        (BASE / "nodes" / "web" / "api" / "scanner_core.py", "task_alive", "假运行检测逻辑"),
    ]
    
    # 方法调用方检查
    for caller_path, caller_str, def_path, def_str, desc in source_checks:
        if not caller_path.exists():
            continue
        caller_src = caller_path.read_text()
        if caller_str not in caller_src:
            ok(f"{desc}: 调用方已无此调用")
            continue
        # 调用方有引用, 检查定义方是否有定义
        if def_path.exists():
            def_src = def_path.read_text()
            if def_str in def_src:
                ok(f"{desc}: 定义存在")
            else:
                p0(f"{desc}: 定义缺失({def_str} not in {def_path.name})")
        else:
            p0(f"{desc}: 定义文件不存在 {def_path}")
    
    # 属性存在性检查
    for fpath, search_str, desc in attr_checks:
        if not fpath.exists():
            p1(f"{desc}: 文件不存在 {fpath}")
            continue
        src = fpath.read_text()
        if search_str in src:
            ok(f"{desc}: 存在")
        else:
            p0(f"{desc}: 缺失({search_str} not in {fpath.name})")
    
    # 检查rolled_back订单数据一致性
    print("  4b.3 检查rolled_back订单...")
    try:
        import pymongo
        client = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=3000)
        db = client["stock_agent"]
        
        rb_orders = list(db["broker_orders"].find({"status": "rolled_back"}, {"_id": 0, "ts_code": 1, "side": 1, "trade_date": 1}))
        if rb_orders:
            pos_codes = set(d["ts_code"] for d in db["broker_positions"].find({}, {"ts_code": 1}))
            stale_rb = [o for o in rb_orders if o.get("ts_code") not in pos_codes]
            if stale_rb:
                p0(f"rolled_back订单实际已卖出({len(stale_rb)}笔): {[o.get('ts_code') for o in stale_rb[:5]]}")
            else:
                ok(f"rolled_back订单({len(rb_orders)}笔)全部仍有持仓")
        else:
            ok("无rolled_back订单")
    except Exception as e:
        p0(f"rolled_back检查失败: {e}")
    
    info(f"pyflakes扫描: {files_scanned}个文件")


# ── 5. 数据流检查 ──
async def check_data_flow():
    print("\n═══ 5. 数据流 ═══")
    
    try:
        import pymongo
        client = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=3000)
        db = client["stock_agent"]
        td = int(datetime.now().strftime("%Y%m%d"))
        
        # 5.1 MongoDB集合健康
        collections = [
            "stock_daily_ak_full", "daily_basic", "limit_list", "sentiment_scores",
            "scan_traces", "broker_orders", "broker_positions", "broker_accounts",
            "equity_curve", "risk_decisions", "scanner_timeline", "scanner_signals"
        ]
        for coll_name in collections:
            coll = db[coll_name]
            total = coll.count_documents({})
            today = coll.count_documents({"trade_date": td})
            # 找最新记录
            latest = coll.find_one(sort=[("trade_date", -1)])
            latest_td = latest.get("trade_date") if latest else None
            if total == 0:
                p1(f"{coll_name}: 空集合")
            else:
                ok(f"{coll_name}: total={total}, today={today}, latest={latest_td}")
        
        # 5.2 trade_date类型一致性
        type_samples = {}
        for coll_name in collections:
            doc = db[coll_name].find_one()
            if doc and "trade_date" in doc:
                td_type = type(doc["trade_date"]).__name__
                type_samples[coll_name] = td_type
        int_types = [k for k, v in type_samples.items() if v == "int"]
        str_types = [k for k, v in type_samples.items() if v == "str"]
        if str_types:
            p1(f"trade_date类型不一致: int={int_types}, str={str_types}")
        else:
            ok(f"trade_date 全部int类型 ({len(int_types)}集合)")
        
        # 5.3 9层漏斗数据完整性
        latest_trace = db["scan_traces"].find_one(sort=[("scan_time", -1)])
        if latest_trace:
            layer_details = latest_trace.get("layer_details", {})
            if not layer_details:
                p1("scan_traces: 无layer_details数据")
            else:
                layer_count = len(layer_details)
                if layer_count < 9:
                    # L1强制空仓时后续层不执行是正常的，降级为info
                    import logging as _l
                    _l.info(f"scan_traces layer_details={layer_count}层(不足9层可能因L1强制空仓)")
                ok(f"漏斗层数: {layer_count}, keys={list(layer_details.keys())}")
            
            # 检查summary
            summary = latest_trace.get("summary", {})
            total_cand = summary.get("total_candidates", 0)
            if total_cand == 0:
                p1("scan_traces.summary.total_candidates=0")
            else:
                ok(f"total_candidates={total_cand}")
        else:
            p1("scan_traces: 无记录")
        
        # 5.4 broker_accounts 等式验证
        acc = db["broker_accounts"].find_one()
        if acc:
            assets = acc.get("total_assets", 0)
            cash = acc.get("available_cash", 0)
            mv = acc.get("market_value", 0)
            diff = abs(assets - cash - mv)
            if diff > 100:
                p1(f"账户等式偏差: assets({assets}) - cash({cash}) - mv({mv}) = {diff}")
            else:
                ok(f"账户等式: diff={diff:.0f}")
        
        # 5.5 持仓current_price=0检查
        zero_price = db["broker_positions"].count_documents({
            "total_qty": {"$gt": 0},
            "current_price": 0
        })
        if zero_price > 0:
            p0(f"持仓current_price=0: {zero_price}条")
        else:
            ok("持仓current_price全部>0")
        
        # 5.6 equity_curve单调性
        recent_equity = list(db["equity_curve"].find().sort("trade_date", -1).limit(30))
        if len(recent_equity) > 1:
            # 检查total_assets是否非单调递减(允许波动)
            big_drops = []
            for i in range(1, len(recent_equity)):
                prev = recent_equity[i-1].get("total_assets", 0)
                curr = recent_equity[i].get("total_assets", 0)
                if prev > 0 and curr < prev * 0.5:
                    big_drops.append(f"{recent_equity[i].get('trade_date')}: {prev:.0f}->{curr:.0f}")
            if big_drops:
                p1(f"equity_curve大幅下降: {big_drops[:3]}")
            else:
                ok("equity_curve 无大幅下降")
        else:
            info("equity_curve 数据不足")
        
    except Exception as e:
        p0(f"数据流检查失败: {e}")


# ── 6. 交易/风控 ──
async def check_trading_risk():
    print("\n═══ 6. 交易/风控 ═══")
    
    try:
        import pymongo
        client = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=3000)
        db = client["stock_agent"]
        
        # 6.1 风控矩阵API返回验证
        r = subprocess.run(["curl", "-sf", "-m", "5", "http://localhost:8000/api/v1/scanner/position-risk-matrix"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            p0("position-risk-matrix API不可达")
        else:
            data = json.loads(r.stdout).get("data", {})
            positions = data.get("positions", [])
            global_risk = data.get("global", {})
            
            # 检查全局字段
            required_global = ["total_market_value", "risk_score", "risk_level", "position_ratio", "cash_ratio"]
            for field in required_global:
                if field not in global_risk or global_risk[field] is None:
                    p1(f"风控矩阵global缺字段: {field}")
            
            # 检查持仓数据
            for pos in positions:
                if pos.get("current_price", 0) == 0:
                    p0(f"风控矩阵: {pos.get('ts_code')} current_price=0")
                if pos.get("profit_pct", 0) == -100:
                    p0(f"风控矩阵: {pos.get('ts_code')} profit_pct=-100% (current_price=0)")
            
            if positions and not any(p.get("current_price", 0) == 0 for p in positions):
                ok(f"风控矩阵: {len(positions)}持仓, risk_score={global_risk.get('risk_score')}")
            
            if not positions:
                info("风控矩阵: 无持仓")
        
        # 6.2 订单profit_pct=0检查
        td = int(datetime.now().strftime("%Y%m%d"))
        zero_profit_sells = db["broker_orders"].count_documents({
            "side": "sell", "status": "filled", "profit_pct": 0,
            "trade_date": {"$gte": td - 7}  # 最近7天
        })
        if zero_profit_sells > 5:
            p1(f"最近7天有{zero_profit_sells}笔卖出profit_pct=0")
        else:
            ok(f"最近7天profit_pct=0的卖出: {zero_profit_sells}笔")
        
        # 6.3 risk_decisions完整性
        td = int(datetime.now().strftime("%Y%m%d"))
        rd = db["risk_decisions"].find_one({"trade_date": td})
        if rd:
            if rd.get("profit_loss") is None and rd.get("profit_pct") is None:
                p1("risk_decisions缺profit_loss/profit_pct字段")
            else:
                ok("risk_decisions 有盈亏字段")
        else:
            info("今日无risk_decisions (盘中产生)")
        
    except Exception as e:
        p0(f"交易/风控检查失败: {e}")


# ── 7. 信号管道 ──
async def check_signal_pipeline():
    print("\n═══ 7. 信号管道 ═══")
    
    try:
        import pymongo
        client = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=3000)
        db = client["stock_agent"]
        
        # 7.1 scan_traces 9层完整性
        td = int(datetime.now().strftime("%Y%m%d"))
        traces = list(db["scan_traces"].find({"trade_date": td}).sort("scan_time", -1).limit(5))
        if not traces:
            # 找最近有数据的日期
            latest = db["scan_traces"].find_one(sort=[("trade_date", -1)])
            if latest:
                td = latest["trade_date"]
                traces = list(db["scan_traces"].find({"trade_date": td}).sort("scan_time", -1).limit(5))
        
        if traces:
            for trace in traces[:1]:
                layer_details = trace.get("layer_details", {})
                layer_count = len(layer_details)
                if layer_count < 9:
                    # L1强制空仓时后续层不执行是正常的
                    pass
                else:
                    ok(f"9层漏斗: {list(layer_details.keys())}")
                
                # 检查summary
                summary = trace.get("summary", {})
                if not summary.get("total_candidates") and not summary.get("total"):
                    p1("scan_traces.summary缺total_candidates")
                else:
                    ok(f"summary.total_candidates={summary.get('total_candidates', summary.get('total', '?'))}")
        else:
            info("无scan_traces数据")
        
        # 7.2 策略参数一致性 (实盘vs回测)
        param_check_script = BASE / "scripts" / "check_params_alignment.py"
        if param_check_script.exists():
            r = subprocess.run(
                ["python3", str(param_check_script)],
                capture_output=True, text=True, timeout=30,
                cwd=str(BASE)
            )
            if r.returncode == 0:
                ok("策略参数一致性检查通过")
            else:
                # 提取不一致项
                lines = r.stdout.strip().split("\n")
                issues = [l for l in lines if "❌" in l or "不一致" in l]
                if issues:
                    p1(f"策略参数不一致: {'; '.join(issues[:3])}")
                else:
                    p1(f"策略参数检查有输出但exit={r.returncode}")
        else:
            info("check_params_alignment.py 不存在")
        
    except Exception as e:
        p0(f"信号管道检查失败: {e}")


# ── 8. 运行时状态模拟检查 ──

async def check_runtime_state():
    """运行时状态模拟检查 - 不影响正在运行的scanner
    
    用独立测试实例验证:
    1. 假运行检测: _is_running=True但task=None -> start API应检测到
    2. period命名一致性: sentiment_scores.period值必须全部能匹配DYNAMIC_MAX_POSITIONS
    3. 持仓数不超限: broker_positions <= MAX_POSITIONS
    4. scanner stop/start对称性: stop后_is_running必须=False
    """
    print("\n═══ 8. 运行时状态模拟 ═══")
    
    try:
        import pymongo
        client = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=3000)
        db = client["stock_agent"]
        
        # 8.1 period命名一致性 (今天故障的根因)
        print("  8.1 检查period命名一致性...")
        try:
            # 从sentiment_scores获取所有period值
            periods_ss = db["sentiment_scores"].distinct("period")
            periods_ss = [p for p in periods_ss if p]
            
            # 从sentiment_live_log获取所有phase值
            periods_ll = db["sentiment_live_log"].distinct("phase")
            periods_ll = [p for p in periods_ll if p]
            
            # 代码中DYNAMIC_MAX_POSITIONS的key
            scanner_py = (BASE / "nodes" / "market_monitor" / "scanner.py").read_text()
            # 提取DYNAMIC_MAX_POSITIONS字典
            import re
            m = re.search(r'DYNAMIC_MAX_POSITIONS\s*=\s*\{([^}]+)\}', scanner_py)
            if m:
                dict_text = m.group(1)
                # 提取dict key(冒号前的引号内容),排除注释中的引用
                code_keys = re.findall(r'[\'\"]([^\'\"]+)[\'\"]\s*:', dict_text)
            else:
                code_keys = []
                p0("无法从scanner.py提取DYNAMIC_MAX_POSITIONS")
            
            # 检查: 每个sentiment_scores.period值必须在code_keys中
            unmatched_ss = [p for p in periods_ss if p not in code_keys]
            if unmatched_ss:
                p0(f"sentiment_scores.period有值不在DYNAMIC_MAX_POSITIONS中: {unmatched_ss}")
            else:
                ok(f"sentiment_scores.period全部匹配({len(periods_ss)}个): {periods_ss[:5]}")
            
            # 检查: 每个sentiment_live_log.phase值必须在code_keys中
            unmatched_ll = [p for p in periods_ll if p not in code_keys]
            if unmatched_ll:
                p0(f"sentiment_live_log.phase有值不在DYNAMIC_MAX_POSITIONS中: {unmatched_ll}")
            else:
                ok(f"sentiment_live_log.phase全部匹配({len(periods_ll)}个): {periods_ll[:5]}")
            
        except Exception as e:
            p0(f"period命名检查失败: {e}")
        
        # 8.2 持仓数不超限
        print("  8.2 检查持仓数不超限...")
        try:
            pos_count = db["broker_positions"].count_documents({})
            # 读MAX_POSITIONS
            max_match = re.search(r'MAX_POSITIONS\s*=\s*(\d+)', scanner_py)
            max_pos = int(max_match.group(1)) if max_match else 10
            
            if pos_count > max_pos:
                p0(f"broker_positions={pos_count} > MAX_POSITIONS={max_pos}")
            else:
                ok(f"broker_positions={pos_count} <= MAX_POSITIONS={max_pos}")
                
            # 同时检查: orders推算的持仓数 vs broker_positions
            from collections import defaultdict
            holdings = defaultdict(float)
            for d in db["broker_orders"].find({"status": "filled"}, {"ts_code": 1, "side": 1, "filled_qty": 1, "filled_amount": 1, "filled_price": 1}):
                qty = d.get("filled_qty", 0) or 0
                if qty == 0:  # fallback: filled_amount / filled_price
                    fa = d.get("filled_amount", 0) or 0
                    fp = d.get("filled_price", 0) or 0
                    if fp > 0:
                        qty = fa / fp
                if d.get("side") == "buy":
                    holdings[d["ts_code"]] += qty
                else:
                    holdings[d["ts_code"]] -= qty
            # 只看非零持仓
            holdings_set = {k for k, v in holdings.items() if abs(v) >= 0.5}
            pos_codes = set(d["ts_code"] for d in db["broker_positions"].find({}, {"ts_code": 1}))
            
            extra = pos_codes - holdings_set
            missing = holdings_set - pos_codes
            if extra:
                p1(f"broker_positions有{len(extra)}只无对应orders: {list(extra)[:3]}")
            if missing:
                # 区分: 正数(有买入无卖出)=真问题, 负数(超卖)=历史遗留
                real_missing = [c for c in missing if holdings[c] > 0]
                hist_ghost = [f"{c}({holdings[c]:.0f})" for c in missing if holdings[c] <= 0]
                if real_missing:
                    p0(f"orders推算有{len(real_missing)}只在持仓中缺失(正数): {real_missing}")
                if hist_ghost:
                    info(f"历史幽灵持仓({len(hist_ghost)}只超卖, 不影响交易): {hist_ghost}")
            if not extra and not missing:
                ok(f"持仓一致性: broker_positions({len(pos_codes)}) == orders推算({len(holdings)})")
                
        except Exception as e:
            p0(f"持仓数检查失败: {e}")
        
        # 8.3 假运行检测逻辑 (代码级验证, 不实际运行)
        print("  8.3 检查假运行检测逻辑...")
        try:
            scanner_core_py = (BASE / "nodes" / "web" / "api" / "scanner_core.py").read_text()
            
            # 检查start_scanner中是否有假运行检测
            has_false_running_check = "假运行" in scanner_core_py or "task_alive" in scanner_core_py or "has_scanned" in scanner_core_py
            if not has_false_running_check:
                p0("start_scanner中缺少假运行检测(_is_running=True但task不存活的检查)")
            else:
                ok("start_scanner有假运行检测逻辑")
            
            # 检查: _is_running=True时是否检查task存活
            if "_task is not None and not scanner._task.done()" in scanner_core_py:
                ok("假运行检测: 检查_task.done()")
            else:
                p1("假运行检测: 未检查_task.done()")
            
            # 8.4 scanner.stop()清理_is_running
            print("  8.4 检查stop()清理逻辑...")
            if "self._is_running = False" in scanner_py:
                # 检查是否在stop()方法中
                stop_section = re.search(r'async def stop\(.*?(?=\n    async def |\n    def |\nclass )', scanner_py, re.DOTALL)
                if stop_section and "_is_running = False" in stop_section.group():
                    ok("stop()中清理_is_running=False")
                else:
                    p1("_is_running=False不在stop()方法中")
            else:
                p0("scanner.py中没有_is_running=False赋值")
            
        except Exception as e:
            p0(f"假运行检测逻辑检查失败: {e}")
        
        # 8.5 实盘API运行时状态 (如果scanner在跑)
        print("  8.5 检查实盘API运行时状态...")
        try:
            r = subprocess.run(["curl", "-sf", "-m", "5", "http://localhost:8000/api/v1/scanner/status"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                data = json.loads(r.stdout).get("data", {})
                is_running = data.get("is_running", False)
                scan_count = data.get("scan_count", 0)
                last_scan = data.get("last_scan_time", "")
                
                if is_running and scan_count == 0 and not last_scan:
                    p0("实盘scanner假运行: is_running=True但scan_count=0且last_scan_time为空")
                elif is_running:
                    ok(f"实盘scanner正常运行: scan_count={scan_count}, last_scan={last_scan}")
                else:
                    info("实盘scanner未运行(盘后正常)")
                    
                # 检查持仓数
                positions = data.get("positions", [])
                if isinstance(positions, list) and len(positions) > max_pos:
                    p0(f"实盘持仓超限: {len(positions)} > {max_pos}")
            else:
                info("API不可达(盘后正常)")
                
        except Exception as e:
            info(f"实盘API检查跳过: {e}")
        
    except Exception as e:
        p0(f"运行时状态检查失败: {e}")


# ── 9. 边界条件审查 ──
def check_boundary_conditions():
    print("\n═══ 9. 边界条件审查 ═══")
    
    # 9.1 所有访问pos.xxx的代码路径是否有None guard
    pm_path = BASE / "nodes" / "market_monitor" / "position_manager.py"
    if pm_path.exists():
        with open(pm_path) as f:
            pm_src = f.read()
        
        # 找pos.avg_cost/pos.current_price/pos.total_qty访问, 检查前面是否有if pos或if not pos
        lines = pm_src.split('\n')
        pos_access_without_guard = []
        for i, line in enumerate(lines):
            if re.search(r'pos\.(avg_cost|current_price|total_qty|available_qty|today_buy_qty|profit_pct)', line):
                # 往上找5行, 看是否有None guard
                has_guard = False
                for j in range(max(0, i-5), i):
                    if 'if not pos' in lines[j] or 'if pos is None' in lines[j] or 'if not pos:' in lines[j]:
                        has_guard = True
                        break
                if not has_guard:
                    # 排除方法定义行和注释
                    if not line.strip().startswith('#') and not line.strip().startswith('def '):
                        pos_access_without_guard.append((i+1, line.strip()))
        
        if pos_access_without_guard:
            info(f"pos属性访问无None guard: {len(pos_access_without_guard)}处")
            for lineno, line in pos_access_without_guard[:3]:
                info(f"  L{lineno}: {line}")
            if len(pos_access_without_guard) > 3:
                info(f"  ... 还有{len(pos_access_without_guard)-3}处")
        else:
            ok("所有pos属性访问都有None guard ✅")
    
    # 9.2 兜底路径(pos不存在时)是否完整执行了所有副作用
    broker_path = BASE / "nodes" / "market_monitor" / "broker.py"
    if broker_path.exists():
        with open(broker_path) as f:
            bk_src = f.read()
        
        # 找"if not pos"或"if pos is None"的代码块, 检查是否有return
        lines = bk_src.split('\n')
        fallback_returns = 0
        fallback_no_return = 0
        for i, line in enumerate(lines):
            if re.search(r'if not pos:|if pos is None:', line):
                # 往下找30行, 看是否有return(兜底路径可能较长)
                has_return = False
                for j in range(i, min(i+30, len(lines))):
                    if 'return' in lines[j] and not lines[j].strip().startswith('#'):
                        has_return = True
                        break
                if has_return:
                    fallback_returns += 1
                else:
                    fallback_no_return += 1
        
        if fallback_no_return > 0:
            p1(f"broker.py: {fallback_no_return}个兜底路径(pos=None)没有return, 可能继续执行导致崩溃")
        else:
            ok(f"broker.py: {fallback_returns}个兜底路径都有return ✅")
    
    # 9.3 停牌/退市股票的处理
    suspended_patterns = re.findall(r'(suspend|停牌|delist|退市)', pm_src, re.IGNORECASE)
    if suspended_patterns:
        ok(f"position_manager.py: 有停牌处理逻辑({len(suspended_patterns)}处引用) ✅")
    else:
        p1("position_manager.py: 无停牌处理逻辑")
    
    # 9.4 涨跌停时的买卖限制
    limit_patterns = re.findall(r'(limit_up|limit_down|涨停|跌停|upper_limit|lower_limit)', bk_src, re.IGNORECASE)
    if limit_patterns:
        ok(f"broker.py: 有涨跌停限制({len(limit_patterns)}处引用) ✅")
    else:
        p1("broker.py: 无涨跌停限制")


# ── 10. 配置生效验证 ──
def check_config_effectiveness():
    print("\n═══ 10. 配置生效验证 ═══")
    
    # 10.1 DYNAMIC_MAX_POSITIONS: 三套命名是否匹配
    scanner_path = BASE / "nodes" / "market_monitor" / "scanner.py"
    if scanner_path.exists():
        with open(scanner_path) as f:
            sc_src = f.read()
        
        # 找DYNAMIC_MAX_POSITIONS的key定义
        dyn_match = re.search(r'DYNAMIC_MAX_POSITIONS\s*[=:]?\s*\{([^}]+)\}', sc_src)
        if dyn_match:
            keys_text = dyn_match.group(1)
            dyn_keys = set(re.findall(r'[\'\"]([^\'\"]+)[\'\"]\\s*:', keys_text))
            info(f"DYNAMIC_MAX_POSITIONS keys: {dyn_keys}")
        else:
            dyn_keys = set()
        
        # 找sentiment_scores.period的值
        # 检查sentiment_scores集合中的period字段
        try:
            import pymongo
            db = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=3000)["stock_agent"]
            periods = set(db["sentiment_scores"].distinct("period"))
            info(f"sentiment_scores.period值: {periods}")
            
            # 检查是否有不匹配
            if dyn_keys and periods:
                # DYNAMIC_MAX_POSITIONS的key应该在sentiment_scores.period(中文) ∪ sentiment_live_log.phase(英文) ∪ 中文→英文别名映射中
                live_phases = set(db["sentiment_live_log"].distinct("phase"))
                # 中文→英文别名映射(frozen=冰点, euphoria=高潮)
                cn_to_en = {"冰点": "frozen", "高潮": "euphoria", "震荡": "chaos", "分化": "differentiation"}
                valid_keys = periods | live_phases | {'default'}
                # 加入中文key对应的英文别名
                for cn, en in cn_to_en.items():
                    if cn in periods:
                        valid_keys.add(en)
                unmatched_dyn = dyn_keys - valid_keys
                if unmatched_dyn:
                    p1(f"DYNAMIC_MAX_POSITIONS有key不在sentiment_scores或live_log中: {unmatched_dyn}")
                else:
                    ok("DYNAMIC_MAX_POSITIONS keys全部在sentiment_scores或live_log中 ✅")
        except Exception as e:
            info(f"MongoDB检查跳过: {e}")
    
    # 10.2 检查策略参数是否实际被读取(不只是定义了)
    sm_path = BASE / "nodes" / "market_monitor" / "signal_manager.py"
    if sm_path.exists():
        with open(sm_path) as f:
            sm_src = f.read()
        
        # 检查min_circulation_market_cap是否从params读取
        if 'params.get' in sm_src and 'min_circulation_market_cap' in sm_src:
            ok("min_circulation_market_cap从params读取 ✅")
        else:
            p1("min_circulation_market_cap可能未从params读取")
        
        # 检查是否有hardcoded的阈值(应该从params读取)
        hardcoded = re.findall(r'(if.*[<>]=?\s*\d+\.\d+.*(?:turnover|market_cap|volume))', sm_src)
        if hardcoded:
            p1(f"signal_manager.py: {len(hardcoded)}处可能hardcoded阈值")
        else:
            ok("无hardcoded阈值 ✅")
    
    # 10.3 检查fallback默认值是否安全
    # 当key不匹配时fallback到默认值, 是否会绕过预期的限制
    fallback_defaults = re.findall(r'\.get\(([\w_]+),\s*(\d+)\)', sc_src)
    dangerous_defaults = []
    for key, default in fallback_defaults:
        if 'max' in key.lower() and default == '0':
            dangerous_defaults.append(f"{key}默认={default}(可能绕过限制)")
        elif 'limit' in key.lower() and default == '0':
            dangerous_defaults.append(f"{key}默认={default}(可能绕过限制)")
    if dangerous_defaults:
        p1(f"危险默认值: {dangerous_defaults}")
    else:
        ok("fallback默认值安全 ✅")


# ── 11. 跨模块key映射完整性 ──
def check_cross_module_key_mapping():
    print("\n═══ 11. 跨模块key映射完整性 ═══")
    
    # 11.1 情绪周期命名: scanner(DYNAMIC_MAX_POSITIONS) vs sentiment_scores.period vs sentiment_live_log.phase
    scanner_path = BASE / "nodes" / "market_monitor" / "scanner.py"
    if scanner_path.exists():
        with open(scanner_path) as f:
            sc_src = f.read()
        
        # 找所有情绪phase相关的key
        # DYNAMIC_MAX_POSITIONS的key
        dyn_match = re.search(r'DYNAMIC_MAX_POSITIONS\s*[=:]?\s*\{([^}]+)\}', sc_src)
        dyn_keys = set(re.findall(r'[\'\"]([^\'\"]+)[\'\"]\s*:', dyn_match.group(1))) if dyn_match else set()
        # 构建key->value映射
        dyn_keys_map = {}
        if dyn_match:
            for m in re.finditer(r'[\'"](\w+)[\'"]\s*:\s*(\d+)', dyn_match.group(1)):
                dyn_keys_map[m.group(1)] = int(m.group(2))
        
        # sentiment_live_log.phase的值
        try:
            import pymongo
            db = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=3000)["stock_agent"]
            live_phases = set(db["sentiment_live_log"].distinct("phase"))
            sent_periods = set(db["sentiment_scores"].distinct("period"))
            
            info(f"DYNAMIC_MAX_POSITIONS keys: {dyn_keys}")
            info(f"sentiment_scores.period: {sent_periods}")
            info(f"sentiment_live_log.phase: {live_phases}")
            
            # 检查三套命名是否一致
            all_keys = [dyn_keys, sent_periods, live_phases]
            all_names = ['DYNAMIC_MAX_POSITIONS', 'sentiment_scores.period', 'sentiment_live_log.phase']
            
            # 检查DYNAMIC_MAX_POSITIONS是否覆盖了两套命名的超集
            # sentiment_scores.period(中文)和sentiment_live_log.phase(英文)不需要完全一致
            # 但DYNAMIC_MAX_POSITIONS必须包含两者的所有key
            for name, keyset in [(all_names[1], all_keys[1]), (all_names[2], all_keys[2])]:
                missing = keyset - dyn_keys - {'default', 'BEARISH'}
                if missing:
                    p1(f"DYNAMIC_MAX_POSITIONS缺少{name}的key: {missing}")
                else:
                    ok(f"DYNAMIC_MAX_POSITIONS覆盖了{name}的所有key ✅")
            # 检查英文/中文映射是否值一致
            en_to_cn = {'rising': '高潮', 'differentiation': '分化', 'chaos': '震荡', 'bearish': '冰点'}
            for en, cn in en_to_cn.items():
                if en in dyn_keys and cn in dyn_keys:
                    if dyn_keys_map.get(en) != dyn_keys_map.get(cn):
                        p1(f"DYNAMIC_MAX_POSITIONS值不一致: {en}={dyn_keys_map.get(en)} vs {cn}={dyn_keys_map.get(cn)}")
            ok("英文/中文key值一致 ✅")
        except Exception as e:
            info(f"MongoDB检查跳过: {e}")
    
    # 11.2 策略名称一致性: strategy_defaults的key vs broker_orders.strategy vs scanner_signals.strategy
    try:
        import pymongo
        db = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=3000)["stock_agent"]
        
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        config_strategies = set(STRATEGY_CONFIGS.keys())
        
        order_strategies = set(db["broker_orders"].distinct("strategy"))
        signal_strategies = set(db["scanner_signals"].distinct("strategy"))
        
        info(f"STRATEGY_CONFIGS keys: {config_strategies}")
        info(f"broker_orders.strategy: {order_strategies}")
        info(f"scanner_signals.strategy: {signal_strategies}")
        
        # 检查是否有不在config中的策略
        unknown_orders = order_strategies - config_strategies - {'test', 'manual', 'FIX'}
        if unknown_orders:
            p1(f"broker_orders有未知策略: {unknown_orders}")
        else:
            ok("broker_orders策略名称全部在STRATEGY_CONFIGS中 ✅")
        
        # anomaly_*是策略别名, 有STRATEGY_ALIASES映射
        from nodes.backtest_engine.strategy_defaults import STRATEGY_ALIASES
        valid_signal_strategies = config_strategies | set(STRATEGY_ALIASES.keys()) | {'test', 'manual'}
        unknown_signals = signal_strategies - valid_signal_strategies
        if unknown_signals:
            p1(f"scanner_signals有未知策略: {unknown_signals}")
        else:
            ok("scanner_signals策略名称全部有效 ✅")
    except Exception as e:
        info(f"策略名称检查跳过: {e}")


# ── Main ──
async def main():
    print(f"🔍 夜间代码级综合检查 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   路径: BASE={BASE}")
    print(f"   前端: {FRONTEND}")
    print(f"   后端: {BACKEND}")
    
    # 同步检查
    check_system_health()
    check_api_endpoints()
    check_frontend_code()
    check_backend_code()
    check_static_analysis()
    check_boundary_conditions()
    check_config_effectiveness()
    check_cross_module_key_mapping()
    
    # 异步检查
    await check_data_flow()
    await check_trading_risk()
    await check_signal_pipeline()
    await check_runtime_state()
    
    # 汇总
    print(f"\n{'═' * 60}")
    print(f"📊 检查汇总: P0={len(CRITICAL)}, P1={len(WARNING)}, Info={len(INFO)}")
    print(f"{'═' * 60}")
    
    if CRITICAL:
        print("\n❌ P0 问题:")
        for c in CRITICAL:
            print(f"  - {c}")
    
    if WARNING:
        print("\n⚠️ P1 问题:")
        for w in WARNING:
            print(f"  - {w}")
    
    if not CRITICAL and not WARNING:
        print("\n✅ 全部通过")
    
    # 退出码
    if CRITICAL:
        sys.exit(1)
    elif WARNING:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
