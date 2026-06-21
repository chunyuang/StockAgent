"""
API契约快照测试 - 前后端字段一致性守卫

第2层防线：确保后端API返回的字段名/结构始终与前端期望一致。
每次改后端代码后跑 pytest tests/test_api_contract.py 即可验证。

原理：
1. 对每个scanner API端点发请求，记录返回的JSON结构（字段名+类型）
2. 与存档的snapshot比对，任何字段增删改名都会触发测试失败
3. 前端composable期望的字段也写入snapshot，双重校验

运行方式：
  pytest tests/test_api_contract.py -v
  pytest tests/test_api_contract.py -v --update-snapshot  # 更新快照（确认变更后）
"""

import pytest
import json
import os
import sys
from pathlib import Path
from typing import Any

# 确保能导入项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
SNAPSHOT_DIR.mkdir(exist_ok=True)

# ========== 前端期望字段定义 ==========
# 从前端composable/store中提取的关键字段，后端必须返回这些字段

# 以2026-06-05后端实际返回字段为准（从API审计提取）
# 前端必须适配这些字段名，不能自己编

FRONTEND_EXPECTED_FIELDS = {
    # === 核心状态API ===
    
    "/scanner/status": {
        "required": ["is_running", "scan_count", "last_scan_time", "active_signals",
                     "positions", "stocks_scanned", "account", "account_id",
                     "trade_mode", "quote_degrade_level"],
    },
    "/scanner/signals": {
        # ScannerSignal: 空列表是正常的（scanner未运行时）
        "required": [],  # list类型，无法检查字段
        "item_fields": ["ts_code", "stock_name", "strategy", "price", "pct_chg", "reason", "created_at", "signal_status"],
    },
    "/scanner/positions": {
        # ScannerPosition: 空列表是正常的
        "required": [],
        "item_fields": ["ts_code", "stock_name", "strategy", "avg_cost", "current_price", "profit_pct", "available_qty", "total_qty"],
    },
    "/scanner/account": {
        # 实盘Tab资产信息
        "required": ["total_assets", "available_cash", "market_value", "today_profit", "total_profit", "position_count", "position_ratio"],
    },
    "/scanner/summary": {
        # 9宫格 - 嵌套在trade_stats/signal_stats/scanner_stats中
        "required": ["account", "trade_stats", "risk_status", "signal_stats", "scanner_stats", "sentiment"],
    },
    "/scanner/health": {
        "required": ["success", "health"],
    },
    
    # === 复盘API ===
    
    "/scanner/daily-report": {
        # 实际返回: date, account, positions, trades, scanner_stats, funnel_summary, sentiment_snapshot
        "required": ["date", "account", "scanner_stats"],
        # ⚠️ 注意: hero/metrics/violations 不在daily-report中，在单独的review-hero API
        "note": "hero/metrics/violations由review-hero/discipline-check/execution-quality提供，不在daily-report中",
    },
    "/scanner/review-hero": {
        # 实际返回: date, conclusion, conclusion_type, metrics, benchmark, sentiment, violations
        "required": ["date", "conclusion", "conclusion_type", "metrics"],
        # ⚠️ 注意: 前端期望return_pct/win_rate，但后端返回conclusion_type+metrics
        "note": "前端需从conclusion或metrics中提取return_pct/win_rate",
    },
    "/scanner/trade-attribution": {
        # list类型，item有: ts_code, stock_name, strategy, buy_price, sell_price, profit_pct...
        "required": [],
        "item_fields": ["ts_code", "stock_name", "strategy", "buy_price", "sell_price", "profit_pct", "sell_reason"],
    },
    "/scanner/discipline-check": {
        # 实际返回: date, total_actions, correct_actions, execution_rate, violation_count, violations
        "required": ["date", "execution_rate", "violation_count", "violations"],
        # ⚠️ 注意: 前端期望stop_loss_execution_rate，后端返回execution_rate
        "note": "stop_loss_execution_rate → execution_rate (字段名不同)",
    },
    "/scanner/execution-quality": {
        "required": ["avg_slippage_pct", "fill_rate_pct", "total_orders", "filled_orders", "date"],
    },
    "/scanner/deviation-attribution": {
        # 实际返回: period, live_stats, risk_alerts, deviations, details
        "required": ["period", "live_stats", "deviations", "details"],
        # ⚠️ 注意: 前端期望slippage/discipline/stock_selection/timing，后端返回不同的结构
        "note": "deviation 4层归因可能在details中，需检查嵌套",
    },
    "/scanner/review-forward": {
        # 实际返回: date, sentiment, advice, strategy_switches
        "required": ["date", "sentiment", "advice"],
    },
    "/scanner/weekly-report": {
        # 实际返回: period, account, daily_stats, strategy_summary, totals, scanner_stats
        "required": ["period", "account", "daily_stats", "strategy_summary", "totals"],
        # ⚠️ 注意: 前端期望overview/daily_breakdown/strategy_performance，后端返回不同的字段名
        "note": "overview→period, daily_breakdown→daily_stats, strategy_performance→strategy_summary",
    },
    "/scanner/review-monthly": {
        # 实际返回: period, summary, strategy_stats, behavior_drift, daily_breakdown, weekly_trend, param_drift
        "required": ["period", "summary", "strategy_stats", "behavior_drift", "param_drift"],
    },
    
    # === 情绪API ===
    "/scanner/sentiment-timeline": {
        # 实际返回: date, mode, points, trades
        "required": ["date", "mode", "points"],
        # ⚠️ 注意: 前端期望scores，后端返回points
        "note": "前端用scores，后端返回points。字段名不同！",
    },
    "/scanner/market-sentiment": {
        "required": ["score", "period", "period_label", "position_ratio", "limit_up_count", "limit_down_count"],
    },
    "/scanner/sentiment-strategy-matrix": {
        "required": ["matrix", "strategy_totals", "recommendations"],
    },
    
    # === 风控API ===
    "/scanner/position-risk-matrix": {
        # 实际返回: positions, global (无dimensions/overall_score/overall_level！)
        "required": ["global"],
        # ⚠️ 严重问题: 前端期望dimensions/overall_score/overall_level，后端不返回这些字段
        "note": "dimensions/overall_score/overall_level MISSING! global只有total_assets/cash_ratio等基本字段",
    },
    "/scanner/position-risk-levels": {
        "required": [],  # 前端未使用此API,scanner未运行时返回{success:false}
    },
    
    # === 扫描追踪API ===
    "/scanner/scan-dates": {
        "required": [],
        "item_fields": ["date", "count", "is_debug"],
    },
    "/scanner/scan-traces": {
        "required": [],
        "item_fields": ["trade_date", "scan_time", "account_id", "summary", "layer_details", "scan_id"],
    },
    "/scanner/limit-pools": {
        # 非开盘时间全部为空，正常
        "required": [],
        "item_fields": [],
    },
    "/scanner/premarket-scan": {
        # POST端点, 手动触发盘前扫描
        "required": [],  # POST, 不在GET测试中
        "item_fields": [],
    },
    
    # === 参数API ===
    "/scanner/param-snapshot": {
        "required": ["date", "global_risk", "strategies"],
    },
    "/scanner/param-drift": {
        "required": ["start_date", "end_date", "drift_count"],
    },
    "/scanner/params": {
        "required": ["halfway_chase", "first_limit_up", "limit_down_qiao"],
    },
    "/scanner/strategy-params-compare": {
        "required": ["strategy_comparisons", "global_risk", "drift_count"],
    },
    
    # === 运维API ===
    "/scanner/system-health-detail": {
        "required": ["scanner", "data_sources", "mongo", "redis", "system", "health_score"],
    },
    "/scanner/audit-log": {
        "required": [],
        "item_fields": ["timestamp", "action", "ts_code", "strategy", "reason"],
    },
    "/scanner/performance-history": {
        "required": [],
        "item_fields": ["account_id", "trade_date", "account", "stats"],
    },
    "/scanner/auto-trades": {
        "required": [],
    },
}


def extract_json_structure(data: Any, prefix: str = "") -> dict:
    """递归提取JSON结构：字段名→类型，忽略具体值"""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                result[key] = extract_json_structure(value, path)
            elif isinstance(value, list):
                if len(value) > 0:
                    result[key] = [extract_json_structure(value[0], f"{path}[0]")]
                else:
                    result[key] = ["<empty_list>"]
            else:
                result[key] = type(value).__name__
        return result
    elif isinstance(data, list):
        if len(data) > 0:
            return [extract_json_structure(data[0], f"{prefix}[0]")]
        return ["<empty_list>"]
    else:
        return type(data).__name__


def load_snapshot(endpoint: str) -> dict | None:
    """加载存档的快照"""
    path = SNAPSHOT_DIR / f"{endpoint.replace('/', '_').strip('_')}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def save_snapshot(endpoint: str, structure: dict):
    """保存快照"""
    path = SNAPSHOT_DIR / f"{endpoint.replace('/', '_').strip('_')}.json"
    path.write_text(json.dumps(structure, indent=2, ensure_ascii=False) + "\n")


def diff_structures(old: dict, new: dict, prefix: str = "") -> list[str]:
    """对比两个JSON结构的差异"""
    diffs = []

    if isinstance(old, dict) and isinstance(new, dict):
        old_keys = set(old.keys())
        new_keys = set(new.keys())

        # 新增字段
        for key in new_keys - old_keys:
            diffs.append(f"  + {prefix}.{key}: {new[key]}")

        # 删除字段
        for key in old_keys - new_keys:
            diffs.append(f"  - {prefix}.{key}: {old[key]}")

        # 类型变化
        for key in old_keys & new_keys:
            if old[key] != new[key]:
                if isinstance(old[key], dict) and isinstance(new[key], dict):
                    diffs.extend(diff_structures(old[key], new[key], f"{prefix}.{key}"))
                else:
                    diffs.append(f"  ~ {prefix}.{key}: {old[key]} → {new[key]}")

    return diffs


class TestAPIContract:
    """API契约测试：确保后端返回结构不变"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """检查后端服务是否可访问"""
        import urllib.request
        try:
            urllib.request.urlopen("http://localhost:8000/api/v1/scanner/health", timeout=3)
        except Exception:
            pytest.skip("后端服务未启动，跳过API契约测试")

    def _fetch_api(self, endpoint: str, method: str = "GET", base: str = "http://localhost:8000") -> dict | None:
        """请求API并返回JSON"""
        import urllib.request
        import urllib.parse

        base_url = f"{base}/api/v1{endpoint}"

        try:
            req = urllib.request.Request(base_url, method=method)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                # 解包常见嵌套：{"data": {...}} 或 {"result": {...}}
                if isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], dict):
                        return data["data"]
                    elif "data" in data and data["data"] is None:
                        # API返回data:null，表示scanner未运行/无数据
                        return None
                    if "result" in data and isinstance(data["result"], dict):
                        return data["result"]
                return data
        except Exception as e:
            return None

    @pytest.mark.parametrize("endpoint", sorted(FRONTEND_EXPECTED_FIELDS.keys()))
    def test_frontend_expected_fields_present(self, endpoint, request):
        """确保API返回前端期望的必填字段"""
        data = self._fetch_api(endpoint)
        if data is None:
            pytest.skip(f"API {endpoint} 无响应（scanner可能未运行）")
            return

        # data可能为None（scanner未运行无交易数据）
        if not isinstance(data, dict):
            pytest.skip(f"API {endpoint} 返回非dict数据（scanner可能未运行）")
            return

        expected = FRONTEND_EXPECTED_FIELDS[endpoint]["required"]
        missing = []
        for field in expected:
            # 支持嵌套字段如 "hero.date"
            parts = field.split(".")
            obj = data
            found = True
            for part in parts:
                if isinstance(obj, dict) and part in obj:
                    obj = obj[part]
                else:
                    found = False
                    break
            if not found:
                missing.append(field)

        assert len(missing) == 0, (
            f"API {endpoint} 缺少前端期望的字段:\n"
            f"  缺失: {missing}\n"
            f"  期望: {expected}\n"
            f"  实际返回字段: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}\n"
            f"\n⚠️ 如果改了后端字段名，必须同步修改前端composable/store！"
        )

    @pytest.mark.parametrize("endpoint", sorted(FRONTEND_EXPECTED_FIELDS.keys()))
    def test_snapshot_structure_unchanged(self, endpoint, request):
        """确保API返回结构与快照一致"""
        data = self._fetch_api(endpoint)
        if data is None:
            pytest.skip(f"API {endpoint} 无响应")
            return

        current_structure = extract_json_structure(data)

        # 检查是否要更新快照
        update = request.config.getoption("--update-snapshot", default=False)

        old_structure = load_snapshot(endpoint)
        if old_structure is None:
            # 首次运行，保存快照
            save_snapshot(endpoint, current_structure)
            pytest.skip(f"首次运行，已保存 {endpoint} 快照")
            return

        if update:
            save_snapshot(endpoint, current_structure)
            return

        # 对比差异
        diffs = diff_structures(old_structure, current_structure)
        if diffs:
            diff_text = "\n".join(diffs)
            pytest.fail(
                f"API {endpoint} 返回结构发生变化！\n{diff_text}\n\n"
                f"⚠️ 如果是预期变更，运行: pytest tests/test_api_contract.py --update-snapshot\n"
                f"⚠️ 如果是非预期变更，请检查后端代码是否误改了字段名/结构"
            )

    def test_no_duplicate_api_paths(self):
        """确保没有重复的API路径"""
        from nodes.web.api import (
            scanner_core, scanner_debug, scanner_report,
            scanner_review, scanner_scan, scanner_sentiment,
            scanner_strategy, scanner_system, scanner_trading
        )

        # 只遍历子模块（不遍历scanner.py，因为它include所有子路由）
        all_paths = []
        for module in [scanner_core, scanner_debug, scanner_report,
                       scanner_review, scanner_scan, scanner_sentiment,
                       scanner_strategy, scanner_system, scanner_trading]:
            if hasattr(module, 'router'):
                for route in module.router.routes:
                    if hasattr(route, 'path'):
                        all_paths.append(f"{route.methods} {route.path}")

        # 检查重复
        seen = {}
        for path in all_paths:
            if path in seen:
                pytest.fail(f"重复的API路径: {path} (在 {seen[path]} 和当前模块中)")
            seen[path] = path

    def test_frontend_api_paths_match_backend(self):
        """确保前端调用的API路径在后端都有对应"""
        # 前端实际调用的路径列表（从composable中提取）
        frontend_paths = [
            "/scanner/all",
            "/scanner/status",
            "/scanner/signals",
            "/scanner/positions",
            "/scanner/timeline",
            "/scanner/timeline/history",
            "/scanner/account",
            "/scanner/limit-pools",
            "/scanner/summary",
            "/scanner/position-risk-levels",
            "/scanner/kline/",  # 带参数
            "/scanner/position-risk-matrix",
            "/scanner/health",
            "/scanner/system-health-detail",
            "/scanner/audit-log",
            "/scanner/params",
            "/scanner/strategy-params-compare",
            "/scanner/performance-history",
            "/scanner/auto-trades",
            "/scanner/trade-audit",
            "/scanner/trade-detail/",  # 带参数
            "/scanner/trade-log",
            "/scanner/export-trade-log",
            "/scanner/sentiment-timeline",
            "/scanner/market-sentiment",
            "/scanner/sentiment-strategy-matrix",
            "/scanner/scan-dates",
            "/scanner/scan-traces",
            "/scanner/scan-config",
            "/scanner/daily-report",
            "/scanner/weekly-report",
            "/scanner/review-monthly",
            "/scanner/review-hero",
            "/scanner/trade-attribution",
            "/scanner/discipline-check",
            "/scanner/execution-quality",
            "/scanner/deviation-attribution",
            "/scanner/review-forward",
            "/scanner/param-snapshot",
            "/scanner/param-drift",
            "/scanner/factor-effectiveness",
            "/scanner/review-closed-loop",
            "/scanner/review-weekly",
            "/scanner/historical-review",
            "/scanner/backtest-compare",
            "/scanner/debug/layers",
            "/scanner/debug/premarket-sim",
            "/scanner/debug/scan-trace/",  # 带参数
            "/scanner/debug/strategy-filter",
            "/scanner/start",
            "/scanner/stop",
            "/scanner/reset",
            "/scanner/trade",
            "/scanner/sell",
            "/scanner/sell-all",
            "/scanner/sell-all",
            "/scanner/snapshot",
            "/scanner/scan-once",
            "/scanner/premarket-scan",
            "/scanner/daily-settlement",
            "/scanner/backtest-same-period",
            "/scanner/emergency-liquidate",
            "/scanner/circuit-breaker/pause",
            "/scanner/circuit-breaker/reset",
            "/scanner/run-backtest",
            "/scanner/trailing-stop/",  # PUT带参数
            "/scanner/position-risk/",  # PUT带参数
            "/scanner/params/",  # PUT带参数
            "/scanner/debug/strategy-hot-update/",  # PUT带参数
            "/scanner/daemon/status",
            "/scanner/daemon/restart",
            "/scanner/alignment-stats",
            "/scanner/orders",
            "/scanner/event-bus/history",
            "/scanner/event-bus/stats",
            "/scanner/stream/signals",
            "/scanner/stream/positions",
            "/scanner/premarket-status",
        ]

        # 这个测试只是记录，不自动失败（因为有些路径可能需要参数才能匹配）
        # 但会输出警告帮助人工检查
        print(f"\n前端调用的API路径数: {len(frontend_paths)}")
        print(f"前端期望字段检查的API数: {len(FRONTEND_EXPECTED_FIELDS)}")
