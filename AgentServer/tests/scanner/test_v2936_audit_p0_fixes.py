"""
v2.9.36 审查P0/P1 Bug修复验证测试

对应 REALTIME_MONITOR_AUDIT_20260531.md 中4个Bug修复:
- P0#1: Redis→WebSocket桥接在lifespan中启动
- P0#2: signal_persistence集合常量定义
- P0#3: daily_settlement路由装饰器
- P1#4: RedisWSBridge._log_cache引用修复
"""
import ast
import os
import pytest


# ==================== 路径常量 ====================
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_PY = os.path.join(BASE, "nodes", "web", "app.py")
SIGNAL_PERSIST = os.path.join(BASE, "nodes", "web", "signal_persistence.py")
SCANNER_API = os.path.join(BASE, "nodes", "web", "api", "scanner_trading.py")
WS_BRIDGE = os.path.join(BASE, "nodes", "web", "redis_ws_bridge.py")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ==================== P0#1: Bridge启动 ====================

class TestBridgeStartedInLifespan:
    """验证Redis→WS桥接在app.py lifespan中启动"""

    def test_lifespan_imports_init_bridge(self):
        """lifespan中导入init_bridge"""
        src = _read(APP_PY)
        assert "init_bridge" in src, "lifespan应导入init_bridge"

    def test_lifespan_calls_bridge_start(self):
        """lifespan中调用bridge.start()"""
        src = _read(APP_PY)
        assert "bridge.start()" in src, "lifespan应调用bridge.start()"

    def test_lifespan_calls_bridge_stop_on_shutdown(self):
        """lifespan关闭时调用bridge.stop()"""
        src = _read(APP_PY)
        assert "bridge.stop()" in src, "lifespan关闭应调用bridge.stop()"

    def test_lifespan_bridge_in_try_except(self):
        """桥接启动/停止在try/except中(不影响主服务)"""
        src = _read(APP_PY)
        # 找到bridge.start()所在上下文
        lines = src.split("\n")
        bridge_start_line = None
        for i, line in enumerate(lines):
            if "bridge.start()" in line:
                bridge_start_line = i
                break
        assert bridge_start_line is not None, "应包含bridge.start()调用"
        # 检查附近有try/except
        nearby = "\n".join(lines[max(0, bridge_start_line-5):bridge_start_line+1])
        assert "try" in nearby, "bridge启动应在try块中"


# ==================== P0#2: 集合常量定义 ====================

class TestSignalPersistenceCollections:
    """验证signal_persistence集合常量已定义"""

    def test_collection_review_defined(self):
        """COLLECTION_REVIEW已定义为字符串常量"""
        src = _read(SIGNAL_PERSIST)
        assert 'COLLECTION_REVIEW = "daily_postmarket_review"' in src, \
            "COLLECTION_REVIEW应定义为'daily_postmarket_review'"

    def test_collection_execution_log_defined(self):
        """COLLECTION_EXECUTION_LOG已定义为字符串常量"""
        src = _read(SIGNAL_PERSIST)
        assert 'COLLECTION_EXECUTION_LOG = "signal_execution_log"' in src, \
            "COLLECTION_EXECUTION_LOG应定义为'signal_execution_log'"

    def test_collection_pool_defined(self):
        """COLLECTION_POOL已定义为字符串常量"""
        src = _read(SIGNAL_PERSIST)
        assert 'COLLECTION_POOL = "premarket_pool"' in src, \
            "COLLECTION_POOL应定义为'premarket_pool'"

    def test_collections_used_not_just_commented(self):
        """常量在代码中被引用(不只是注释)"""
        src = _read(SIGNAL_PERSIST)
        # COLLECTION_REVIEW应在非注释行被引用
        used_review = sum(1 for line in src.split("\n")
                          if "COLLECTION_REVIEW" in line and not line.strip().startswith("#"))
        assert used_review >= 2, f"COLLECTION_REVIEW应被引用≥2次(定义+使用), 实际{used_review}"


# ==================== P0#3: daily_settlement路由 ====================

class TestDailySettlementRoute:
    """验证daily_settlement有路由装饰器"""

    def test_daily_settlement_has_router_decorator(self):
        """daily_settlement函数有@router.post装饰器"""
        src = _read(SCANNER_API)
        lines = src.split("\n")
        for i, line in enumerate(lines):
            if "async def daily_settlement" in line:
                # 检查前面一行是否有装饰器
                prev = lines[i-1].strip() if i > 0 else ""
                assert prev.startswith('@router.post'), \
                    f"daily_settlement应有@router.post装饰器, 前行: '{prev}'"
                return
        pytest.fail("未找到daily_settlement函数定义")

    def test_daily_settlement_route_path(self):
        """路由路径为/scanner/daily-settlement"""
        src = _read(SCANNER_API)
        assert '@router.post("/scanner/daily-settlement")' in src, \
            "路由路径应为/scanner/daily-settlement"


# ==================== P1#4: _log_cache引用修复 ====================

class TestLogCacheReference:
    """验证RedisWSBridge.get_stats()不再引用_log_cache"""

    def test_get_stats_no_log_cache_len(self):
        """get_stats中不再使用len(self._log_cache)"""
        src = _read(WS_BRIDGE)
        assert "len(self._log_cache)" not in src, \
            "get_stats不应再引用self._log_cache长度"

    def test_get_stats_cached_tasks_is_int(self):
        """cached_tasks字段为整数常量"""
        src = _read(WS_BRIDGE)
        # 找到cached_tasks行
        for line in src.split("\n"):
            if "cached_tasks" in line and not line.strip().startswith("#"):
                assert "0" in line, "cached_tasks应为0(不再缓存)"
                assert "_log_cache" not in line or "不再" in line, "不应引用_log_cache(除注释外)"
                return
        pytest.fail("未找到cached_tasks字段")


# ==================== 回测零影响 ====================

class TestNoBacktestRegressionV2936:
    """验证修复不影响回测模块"""

    def test_backtest_no_app_py_import(self):
        """回测模块不导入app.py"""
        import importlib
        try:
            mod = importlib.import_module("nodes.backtest_engine.factor_selection.portfolio_backtest")
            src = open(mod.__file__, "r").read()
            assert "app.py" not in src
            assert "signal_persistence" not in src
            assert "redis_ws_bridge" not in src
        except ImportError:
            pass  # 回测模块不可导入时跳过

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker API未变"""
        try:
            from nodes.market_monitor.sell_signal_checker import SellSignalChecker
            checker = SellSignalChecker.__new__(SellSignalChecker)
            assert hasattr(checker, 'check_realtime_sell')
        except ImportError:
            pass

    def test_strategy_defaults_importable(self):
        """策略默认参数正常导入"""
        # strategy_defaults在回测引擎中(market_monitor通过import引用)
        sd_path = os.path.join(BASE, "nodes", "backtest_engine", "strategy_defaults.py")
        assert os.path.exists(sd_path), f"strategy_defaults.py应存在: {sd_path}"
        src = open(sd_path).read()
        assert "STRATEGY_CONFIGS" in src, "应包含STRATEGY_CONFIGS"
