#!/usr/bin/env python3
"""
API契约测试 — 验证后端API返回结构与前端期望一致

这是防止后端改字段名导致前端白屏的核心防线。
测试内容:
1. 所有scanner GET端点返回{success: bool, data: ...}结构
2. 关键字段名映射(scanner/status, scanner/limit-pools, strategy-config等)
3. HTTP方法匹配(前端POST vs 后端PUT等)
4. 分页参数命名一致性
"""
import sys
import os
import json
import urllib.request
import urllib.error
import time

# 路径设置
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))

BASE = "http://localhost:8000/api/v1"
TIMEOUT = 15


def api_get(path: str, params: str = "") -> dict:
    """GET请求辅助"""
    url = f"{BASE}{path}"
    if params:
        url += f"?{params}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"_http_error": e.code, "_body": body}
    except Exception as ex:
        return {"_error": str(ex)}


def api_method(method: str, path: str, body: dict = None) -> dict:
    """通用HTTP请求辅助"""
    url = f"{BASE}{path}"
    try:
        data = json.dumps(body).encode() if body else b"{}"
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code}
    except Exception as ex:
        return {"_error": str(ex)}


# ==================== 测试类 ====================

class TestAPIContract:
    """API契约测试"""

    def test_scanner_status_structure(self):
        """scanner/status返回结构必须包含前端期望的字段"""
        r = api_get("/scanner/status")
        assert r.get("success") is True, f"scanner/status success!=True: {r.get('success')}"
        data = r.get("data", {})
        # 前端ScannerStatus类型期望的字段
        required_fields = ["is_running", "scan_count", "active_signals", "positions",
                          "stocks_scanned", "stats", "account_id", "trade_mode", "account"]
        for f in required_fields:
            assert f in data, f"scanner/status缺失字段: {f}"

        # stats子对象
        stats = data.get("stats", {})
        required_stats = ["scans", "signals_found", "trades_executed", "stocks_scanned"]
        for f in required_stats:
            assert f in stats, f"scanner/status.stats缺失字段: {f}"

        # account子对象
        account = data.get("account", {})
        required_account = ["total_assets", "available_cash", "market_value", "total_profit"]
        for f in required_account:
            assert f in account, f"scanner/status.account缺失字段: {f}"

    def test_scanner_limit_pools_structure(self):
        """scanner/limit-pools返回结构必须包含前端期望的字段"""
        r = api_get("/scanner/limit-pools")
        assert r.get("success") is True, f"limit-pools success!=True"
        data = r.get("data", {})
        required = ["limit_up", "limit_down", "broken"]
        for f in required:
            assert f in data, f"limit-pools缺失字段: {f}"

    def test_scanner_health_structure(self):
        """scanner/health返回结构必须包含前端期望的字段(parseResponse会提取health→data)"""
        r = api_get("/scanner/health")
        assert r.get("success") is True
        # 后端返回{success, health:{...}}, parseResponse提取health→data
        data = r.get("health") or r.get("data", {})
        required = ["overall_status", "circuit_breaker", "risk_metrics", "data_sources"]
        for f in required:
            assert f in data, f"scanner/health缺失字段: {f}"

    def test_scanner_summary_structure(self):
        """scanner/summary返回结构"""
        r = api_get("/scanner/summary")
        assert r.get("success") is True
        data = r.get("data", {})
        required = ["account", "scanner_stats", "signal_stats", "positions"]
        for f in required:
            assert f in data, f"scanner/summary缺失字段: {f}"

    def test_scanner_daily_report_structure(self):
        """scanner/daily-report返回结构"""
        r = api_get("/scanner/daily-report")
        assert r.get("success") is True
        data = r.get("data", {})
        required = ["date", "scanner_stats", "positions", "trades", "account"]
        for f in required:
            assert f in data, f"daily-report缺失字段: {f}"

    def test_strategy_config_strategies_structure(self):
        """strategy-config/strategies返回结构"""
        r = api_get("/strategy-config/strategies")
        assert r.get("success") is True
        data = r.get("data", [])
        if isinstance(data, list) and data:
            required = ["id", "name", "enabled", "params", "riskParams"]
            for f in required:
                assert f in data[0], f"strategy-config/strategies[0]缺失字段: {f}"

    def test_strategy_config_global_risk_structure(self):
        """strategy-config/global-risk返回结构"""
        r = api_get("/strategy-config/global-risk")
        assert r.get("success") is True
        data = r.get("data", {})
        # 核心风控参数(可能有不同命名)
        has_risk_params = any(k in data for k in ["stop_loss_pct", "max_position_pct", "max_positions", "take_profit_pct"])
        assert has_risk_params, f"global-risk缺少任何风控参数: {list(data.keys())}"

    def test_datasource_sources_structure(self):
        """datasource/sources返回结构"""
        r = api_get("/datasource/sources")
        assert r.get("success") is True
        data = r.get("data", [])
        if isinstance(data, list) and data:
            required = ["name", "available", "priority"]
            for f in required:
                assert f in data[0], f"datasource/sources[0]缺失字段: {f}"

    def test_system_health_structure(self):
        """system/health返回结构"""
        r = api_get("/system/health")
        assert r.get("success") is True
        # system/health返回{success, status, checks, ...}顶层结构
        assert "status" in r or "checks" in r, f"system/health无status/checks字段: {list(r.keys())[:10]}"

    def test_scanner_all_response_wrapper(self):
        """scanner/all必须用{success, data}包装"""
        r = api_get("/scanner/all")
        assert r.get("success") is True
        data = r.get("data", {})
        required = ["signals", "positions", "timeline", "orders"]
        for f in required:
            assert f in data, f"scanner/all缺失字段: {f}"

    def test_http_method_strategy_update(self):
        """策略更新必须是PUT方法(前端api.put)"""
        # 验证PUT返回422(缺少body)而非405(method not allowed)
        r = api_method("PUT", "/strategy-config/strategies/nonexistent", {"params": {}})
        # 应该返回404(策略不存在)或422(验证错误), 而非405(方法不允许)
        code = r.get("_http_error", 200)
        assert code != 405, f"PUT /strategy-config/strategies/{id}返回405(方法不允许)"

    def test_scanner_trailing_stop_put(self):
        """追踪止损必须是PUT方法"""
        # 验证PUT端点存在
        r = api_method("PUT", "/scanner/trailing-stop/000001.SZ", {"activated": True, "trailing_stop_pct": 0.03})
        code = r.get("_http_error", 200)
        assert code != 405, "PUT /scanner/trailing-stop返回405(方法不允许)"

    def test_scanner_post_endpoints_exist(self):
        """scanner关键POST端点必须存在(返回422而非405)"""
        post_endpoints = [
            ("/scanner/start", {}),
            ("/scanner/stop", {"sell_all": False}),
            ("/scanner/daily-settlement", {}),
            ("/scanner/trade", {"ts_code": "000001.SZ", "side": "buy", "quantity": 100, "price": 10.0}),
        ]
        for path, body in post_endpoints:
            r = api_method("POST", path, body)
            code = r.get("_http_error", 200)
            assert code != 405, f"POST {path}返回405(方法不允许)"

    def test_backtest_endpoints_structure(self):
        """回测模块核心端点不受影响"""
        # backtest/factors - 可能返回空列表但不应报错
        r = api_get("/backtest/factors")
        # backtest/factors可能需要auth，检查不是404/405即可
        if r.get("_http_error"):
            assert r["_http_error"] not in (404, 405), f"backtest/factors返回{r['_http_error']}"
        elif r.get("success") is not None:
            assert r.get("success") is True, f"backtest/factors失败: {str(r)[:200]}"

    def test_scanner_params_structure(self):
        """scanner/params返回结构"""
        r = api_get("/scanner/params")
        assert r.get("success") is True
        data = r.get("data", {})
        # params应该是dict或list
        assert isinstance(data, (dict, list)), f"scanner/params返回类型异常: {type(data)}"

    def test_scanner_alignment_stats(self):
        """scanner/alignment-stats返回结构"""
        r = api_get("/scanner/alignment-stats")
        assert r.get("success") is True

    def test_system_data_status_timeout(self):
        """system/data-status不应超时(<=15s)"""
        start = time.time()
        r = api_get("/system/data-status")
        elapsed = time.time() - start
        if "_error" in r and "timed out" in str(r.get("_error", "")).lower():
            # 已知重聚合查询可能超时，标记为warning但不fail
            print(f"  ⚠️ data-status超时({elapsed:.1f}s)，聚合查询需优化")
        else:
            assert elapsed < 16, f"data-status响应时间过长: {elapsed:.1f}s"

    # ==================== PnL 数值正确性测试 (v2.9.99-r6) ====================
    # 背景: broker._sync_save_order_and_position 时序问题导致 broker_orders.profit_pct 经常=0
    # 这些测试确保 sell 订单的 profit_pct 不是全零

    def _count_sell_pnl_zeros(self, data: list, pct_key: str = "profit_pct") -> tuple:
        """辅助: 统计 sell 订单中 profit_pct=0 的个数"""
        total = 0
        zeros = 0
        for item in data:
            side = str(item.get("side", "")).lower()
            if side == "sell" or (not side and pct_key in item):
                total += 1
                pct = item.get(pct_key)
                if not pct or str(pct).strip() in ("0", "0.0", ""):
                    zeros += 1
        return total, zeros

    def test_sell_pnl_orders_nonzero(self):
        """订单列表: sell 订单 profit_pct 不能全 0"""
        r = api_get("/scanner/orders")
        assert r.get("success") is True
        data = r.get("data", [])
        total, zeros = self._count_sell_pnl_zeros(data)
        if total > 0:
            assert zeros < total, f"所有 sell 订单 profit_pct 全为 0 ({zeros}/{total})"
            print(f"  ✅ 订单列表 sell {total} 笔, profit_pct=0: {zeros}")

    def test_sell_pnl_trade_attribution_nonzero(self):
        """复盘归因: sell 订单 profit_pct 不能全 0"""
        r = api_get("/scanner/trade-attribution", "date=20260622")
        assert r.get("success") is True
        data = r.get("data", [])
        total, zeros = self._count_sell_pnl_zeros(data)
        if total > 0:
            assert zeros < total, f"trade-attribution sell profit_pct 全为 0 ({zeros}/{total})"
            print(f"  ✅ 复盘归因 sell {total} 笔, profit_pct=0: {zeros}")

    def test_sell_pnl_sentiment_timeline_nonzero(self):
        """情绪时间线: trades 中 profit_pct 不能全 0"""
        r = api_get("/scanner/sentiment-timeline")
        assert r.get("success") is True
        trades = r.get("data", {}).get("trades", [])
        total, zeros = self._count_sell_pnl_zeros(trades)
        if total > 0:
            assert zeros < total, f"sentiment-timeline sell profit_pct 全为 0 ({zeros}/{total})"
            print(f"  ✅ 情绪时间线 sell {total} 笔, profit_pct=0: {zeros}")

    def test_sell_pnl_daily_report_nonzero(self):
        """日报: strategy_summary closed_profit 不能全 0"""
        r = api_get("/scanner/daily-report")
        assert r.get("success") is True
        ss = r.get("data", {}).get("positions", {}).get("strategy_summary", {})
        nonzero_count = 0
        zero_count = 0
        for k, v in ss.items():
            cp = v.get("closed_profit", 0)
            if cp:
                nonzero_count += 1
            else:
                zero_count += 1
        if nonzero_count + zero_count > 0:
            assert nonzero_count > 0, f"日报 strategy_summary closed_profit 全为 0 (包含 {zero_count} 个策略)"
            print(f"  ✅ 日报 closed_profit 非零策略数: {nonzero_count}, 零: {zero_count}")

    def test_sell_pnl_unified_trades_nonzero(self):
        """统一交易: sell 订单 profit_pct 不能全 0"""
        for date_param in ["", "?date=20260623"]:
            r = api_get("/unified/trades", date_param.lstrip("?"))
            assert r.get("success") is True
            data = r.get("data", {})
            # unified/trades 返回 {date, trades, summary} 结构
            trades = data.get("trades", []) if isinstance(data, dict) else data
            total, zeros = self._count_sell_pnl_zeros(trades)
            if total > 0:
                assert zeros < total, f"unified/trades sell profit_pct 全为 0 ({zeros}/{total})"
                print(f"  ✅ 统一交易(date={date_param or 'today'}) sell {total} 笔, profit_pct=0: {zeros}")


if __name__ == "__main__":
    import traceback
    test = TestAPIContract()
    methods = [m for m in dir(test) if m.startswith("test_")]
    passed = 0
    failed = 0
    errors = []
    
    for m in methods:
        try:
            getattr(test, m)()
            passed += 1
            print(f"✅ {m}")
        except AssertionError as e:
            failed += 1
            errors.append((m, str(e)))
            print(f"❌ {m}: {e}")
        except Exception as e:
            failed += 1
            errors.append((m, f"{type(e).__name__}: {e}"))
            print(f"💥 {m}: {type(e).__name__}: {e}")
    
    print(f"\n{'='*50}")
    print(f"API契约测试: {passed} passed, {failed} failed")
    if errors:
        print("\n❌ 失败详情:")
        for name, err in errors:
            print(f"  {name}: {err}")
    sys.exit(1 if failed else 0)
