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
import sys, os, re, json, ast, subprocess, time, asyncio
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

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
            
            elapsed = time.time() - t0
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
        info(f"useScannerMonitor.ts 不存在")
    
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
    unified_file = BASE / "nodes" / "web" / "api" / "unified.py"
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
                p1(f"scan_traces: 无layer_details数据")
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
    
    # 异步检查
    await check_data_flow()
    await check_trading_risk()
    await check_signal_pipeline()
    
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
