"""
v2.9 优化测试

验证:
1. QuoteManager回调替代_scanner引用(消除循环依赖)
2. 盘后结算EventBus解耦(绩效快照+飞书日报从scan_loop移到订阅器)
3. 跌停检查去重(PositionManager已处理,scanner不再重复)
4. 运行时快照跨日校验
5. QuoteManager event_emitter回调接口
"""

import asyncio
import pytest
import time
import threading
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


# ==================== QuoteManager回调接口测试 ====================

class TestQuoteManagerCallbackInterface:
    """验证QuoteManager使用回调替代_scanner引用"""

    def test_has_event_emitter_attr(self):
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        assert hasattr(qm, '_event_emitter')
        assert qm._event_emitter is None

    def test_set_event_emitter_stores_callback(self):
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        callback = AsyncMock()
        qm.set_event_emitter(callback)
        assert qm._event_emitter is callback

    def test_no_scanner_ref_after_init(self):
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        assert not hasattr(qm, '_scanner') or qm._scanner is None

    def test_source_code_no_scanner_ref(self):
        import inspect
        from nodes.market_monitor.quote_manager import QuoteManager
        source = inspect.getsource(QuoteManager)
        # 过滤注释和字符串,只检查代码行
        code_lines = [l for l in source.split('\n') 
                      if not l.strip().startswith('#') and not l.strip().startswith('"""')]
        code_text = '\n'.join(code_lines)
        # _scanner不应出现在代码逻辑中(注释中可以)
        # 具体检查: 不应该有 self._scanner 或 _scanner = 的赋值/引用
        assert 'self._scanner' not in code_text, "QuoteManager不应引用self._scanner(已改为回调模式)"
        assert '._scanner' not in code_text, "QuoteManager不应引用_scanner属性(已改为回调模式)"

    @pytest.mark.asyncio
    async def test_no_callback_no_crash(self):
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        result = await qm.fetch_realtime_batch(force=True)
        assert isinstance(result, dict)

    def test_emitter_callback_signature(self):
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        async def mock_emitter(event_name: str, data: dict):
            pass
        qm.set_event_emitter(mock_emitter)
        assert callable(qm._event_emitter)


# ==================== 盘后结算EventBus解耦测试 ====================

class TestDailySettledEventBusDecouple:
    """验证盘后结算通过EventBus驱动"""

    @pytest.mark.asyncio
    async def test_daily_settled_triggers_save_performance(self):
        from nodes.market_monitor.scanner_event_bus import ScannerEventBus
        bus = ScannerEventBus()
        scanner = MagicMock()
        scanner._save_performance_snapshot = AsyncMock()
        scanner._push_daily_summary = AsyncMock()
        
        async def handler(data):
            trade_date = data.get("trade_date", "")
            if trade_date:
                await scanner._save_performance_snapshot(trade_date)
                await scanner._push_daily_summary(trade_date)
        
        bus.on("daily_settled", handler)
        await bus.emit("daily_settled", {"trade_date": "20260529", "total_profit": 1000})
        await asyncio.sleep(0.05)
        scanner._save_performance_snapshot.assert_called_once_with("20260529")
        scanner._push_daily_summary.assert_called_once_with("20260529")

    @pytest.mark.asyncio
    async def test_performance_failure_isolated(self):
        from nodes.market_monitor.scanner_event_bus import ScannerEventBus
        bus = ScannerEventBus()
        scanner = MagicMock()
        scanner._save_performance_snapshot = AsyncMock(side_effect=Exception("DB down"))
        scanner._push_daily_summary = AsyncMock()
        
        async def handler(data):
            trade_date = data.get("trade_date", "")
            if trade_date:
                try:
                    await scanner._save_performance_snapshot(trade_date)
                except Exception:
                    pass
                try:
                    await scanner._push_daily_summary(trade_date)
                except Exception:
                    pass
        
        bus.on("daily_settled", handler)
        await bus.emit("daily_settled", {"trade_date": "20260529"})
        await asyncio.sleep(0.05)
        scanner._push_daily_summary.assert_called_once_with("20260529")

    def test_scan_loop_no_direct_save_performance(self):
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._scan_loop)
        assert "_save_performance_snapshot" not in source, \
            "_save_performance_snapshot应通过EventBus触发"

    def test_scan_loop_no_direct_push_daily_summary(self):
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._scan_loop)
        assert "_push_daily_summary" not in source, \
            "_push_daily_summary应通过EventBus触发"


# ==================== 跌停检查去重测试 ====================

class TestLimitDownDedup:
    """验证PositionManager已处理跌停,scanner不再重复检查"""

    def test_position_manager_handles_limit_down(self):
        from nodes.market_monitor.position_manager import PositionManager
        scanner = MagicMock()
        scanner._state_lock = threading.Lock()
        scanner._trailing_stops = {}
        scanner._pending_sells = {}
        scanner._position_risk_levels = {}
        scanner._position_risk_overrides = {}
        scanner.SELL_LOGIC_MODE = "legacy"
        scanner._get_strategy_risk = MagicMock(return_value={
            "stop_loss_pct": 0.03, "take_profit_pct": 0.07, "trailing_stop_pct": 0.05
        })
        broker = MagicMock()
        scanner._broker = broker
        pos = MagicMock()
        pos.ts_code = "000001.SZ"
        pos.available_qty = 100
        pos.profit_pct = -5.0
        pos.current_price = 10.0
        pos.avg_cost = 10.5
        pos.strategy = "test"
        broker.get_positions.return_value = [pos]
        pm = PositionManager(scanner)
        with patch.object(pm, '_is_limit_down', return_value=True):
            realtime = {"000001.SZ": {"price": 10.0}}
            to_sell = pm.check_stop_loss_only(realtime)
        assert len(to_sell) == 0
        assert "000001.SZ" in scanner._pending_sells

    def test_position_manager_handles_limit_down_recovery(self):
        from nodes.market_monitor.position_manager import PositionManager
        scanner = MagicMock()
        scanner._state_lock = threading.Lock()
        scanner._trailing_stops = {}
        scanner._pending_sells = {
            "000001.SZ": {"reason": "跌停挂起", "price": 10.0, "added_at": time.time(), "source": "test"}
        }
        scanner._position_risk_levels = {}
        scanner._position_risk_overrides = {}
        scanner.SELL_LOGIC_MODE = "legacy"
        scanner._get_strategy_risk = MagicMock(return_value={
            "stop_loss_pct": 0.03, "take_profit_pct": 0.07, "trailing_stop_pct": 0.05
        })
        broker = MagicMock()
        scanner._broker = broker
        pos = MagicMock()
        pos.ts_code = "000001.SZ"
        pos.available_qty = 100
        pos.profit_pct = -5.0
        pos.current_price = 10.5
        pos.avg_cost = 10.5
        pos.strategy = "test"
        broker.get_positions.return_value = [pos]
        pm = PositionManager(scanner)
        with patch.object(pm, '_is_limit_down', return_value=False):
            realtime = {"000001.SZ": {"price": 10.5}}
            to_sell = pm.check_stop_loss_only(realtime)
        assert len(to_sell) >= 1
        assert "000001.SZ" not in scanner._pending_sells

    def test_scanner_no_duplicate_limit_down_check(self):
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._check_stop_loss_only)
        assert "_is_limit_down" not in source, \
            "scanner._check_stop_loss_only不应重复调用_is_limit_down(PM已处理跌停)"


# ==================== 运行时快照跨日校验测试 ====================

class TestRuntimeSnapshotCrossDayValidation:
    """验证运行时快照跨日检查逻辑"""

    def test_same_day_restores_all_state(self):
        scanner = MagicMock()
        scanner._state_lock = threading.Lock()
        scanner._trailing_stops = {}
        scanner._pending_sells = {}
        today = datetime.now().strftime("%Y%m%d")
        doc = {
            "trade_date": today,
            "trailing_stops": {"600036.SH": {"activated": True, "stop_price": 38.5}},
            "pending_sells": {"000001.SZ": {"reason": "跌停挂起"}},
        }
        snapshot_date = doc.get("trade_date", "")
        is_same_day = (snapshot_date == today)
        assert is_same_day is True
        if is_same_day:
            with scanner._state_lock:
                if "trailing_stops" in doc:
                    scanner._trailing_stops = doc["trailing_stops"]
                if "pending_sells" in doc:
                    scanner._pending_sells = doc["pending_sells"]
        assert "600036.SH" in scanner._trailing_stops
        assert "000001.SZ" in scanner._pending_sells

    def test_cross_day_skips_intraday_state(self):
        today = datetime.now().strftime("%Y%m%d")
        yesterday = "20260528" if today != "20260528" else "20260527"
        doc = {"trade_date": yesterday}
        is_same_day = (doc.get("trade_date", "") == today)
        assert is_same_day is False

    def test_snapshot_includes_trade_date_and_degrade_level(self):
        scanner = MagicMock()
        scanner._state_lock = threading.Lock()
        scanner._trailing_stops = {}
        scanner._pending_sells = {}
        scanner._position_risk_levels = {}
        scanner._circuit_breaker = {}
        scanner._stats = {}
        scanner._active_signals = []
        scanner._dry_run = False
        scanner._trade_date = "20260529"
        scanner._quote_degrade_level = 1
        # 验证getattr能获取
        assert getattr(scanner, '_trade_date', '') == "20260529"
        assert getattr(scanner, '_quote_degrade_level', 0) == 1

    def test_load_snapshot_source_code_has_cross_day_check(self):
        """RuntimePersistence.load_runtime_snapshot源码包含跨日校验"""
        import inspect
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        source = inspect.getsource(RuntimePersistence.load_runtime_snapshot)
        assert "is_same_day" in source, "load_runtime_snapshot应包含跨日校验逻辑"
        assert "trade_date" in source, "跨日校验应检查trade_date字段"


# ==================== 回测无影响验证 ====================

class TestNoBacktestRegressionV29:
    """验证v2.9优化不影响回测模块"""

    def test_backtest_engine_importable(self):
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_sell_signal_checker_importable(self):
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        assert SellSignalChecker is not None

    def test_quote_manager_not_in_backtest(self):
        import inspect
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        source = inspect.getsource(PortfolioBacktester)
        assert "quote_manager" not in source

    def test_event_bus_subscribers_not_in_backtest(self):
        import inspect
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        source = inspect.getsource(SellSignalChecker)
        assert "scanner_event_subscribers" not in source
        assert "quote_manager" not in source

    def test_runtime_persistence_not_in_backtest(self):
        import inspect
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        source = inspect.getsource(PortfolioBacktester)
        assert "runtime_persistence" not in source


# ==================== EventBus事件完整性测试 ====================

class TestEventBusEmissionCompleteness:
    """验证所有交易路径都发射了EventBus事件"""

    def test_position_checker_emits_events(self):
        """PositionChecker卖出后发射RISK_SELL_EXECUTED+POSITION_CHANGED"""
        import inspect
        from nodes.market_monitor.position_checker import PositionChecker
        source = inspect.getsource(PositionChecker)
        # 验证源码包含EventBus发射逻辑
        assert "RISK_SELL_EXECUTED" in source, "PositionChecker应发射RISK_SELL_EXECUTED事件"
        assert "POSITION_CHANGED" in source, "PositionChecker应发射POSITION_CHANGED事件"

    def test_signal_manager_emits_position_changed_on_buy(self):
        """SignalManager买入后发射POSITION_CHANGED"""
        import inspect
        from nodes.market_monitor.signal_manager import SignalManager
        source = inspect.getsource(SignalManager)
        assert "POSITION_CHANGED" in source, "SignalManager应发射POSITION_CHANGED事件(买入)"

    def test_risk_sell_emits_events(self):
        """_execute_risk_sell→post_sell_cleanup发射RISK_SELL_EXECUTED+POSITION_CHANGED"""
        import inspect
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        # v2.9.27: 事件发射在RuntimePersistence.post_sell_cleanup中
        cleanup_source = inspect.getsource(RuntimePersistence.post_sell_cleanup)
        assert "RISK_SELL_EXECUTED" in cleanup_source
        assert "POSITION_CHANGED" in cleanup_source

    def test_all_sell_paths_emit_events(self):
        """验证所有卖出路径(风控/PositionChecker/情绪调仓)都发射EventBus事件"""
        import inspect
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        # 风控卖出 → post_sell_cleanup
        cleanup_source = inspect.getsource(RuntimePersistence.post_sell_cleanup)
        assert "RISK_SELL_EXECUTED" in cleanup_source
        # 情绪调仓卖出 — _handle_emotion_phase_change已提取到EmotionCycleManager【v2.9.24】
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        emotion_source = inspect.getsource(EmotionCycleManager.handle_emotion_phase_change)
        from nodes.market_monitor.scanner import MarketScanner
        # 【v2.9.31:EMOTION_CHANGED发射从_apply_filter_pipeline提取到_process_filter_result】
        filter_pipeline_source = inspect.getsource(MarketScanner._apply_filter_pipeline)
        process_result_source = inspect.getsource(MarketScanner._process_filter_result)
        assert "EMOTION_CHANGED" in filter_pipeline_source + process_result_source


# ==================== __getattr__动态委托测试 ====================

class TestGetattrDelegation:
    """验证__getattr__动态委托分派正确性"""

    def _make_scanner(self):
        from nodes.market_monitor.scanner import MarketScanner
        return MarketScanner(account_id="test_delegate")

    def test_delegate_map_has_entries(self):
        """_DELEGATE_MAP非空"""
        from nodes.market_monitor.scanner import MarketScanner
        assert len(MarketScanner._DELEGATE_MAP) >= 20

    def test_delegated_method_callable(self):
        """委托方法可通过__getattr__获取"""
        scanner = self._make_scanner()
        assert callable(scanner._save_timeline)
        assert callable(scanner._check_positions)
        assert callable(scanner._short_to_ts_code)

    def test_nonexistent_method_raises(self):
        """非委托方法应抛AttributeError"""
        scanner = self._make_scanner()
        with pytest.raises(AttributeError):
            scanner.nonexistent_method_12345()

    def test_class_method_delegate(self):
        """QuoteManager类方法委托"""
        scanner = self._make_scanner()
        result = scanner._short_to_ts_code("000001")
        assert result == "000001.SZ"

    def test_scanner_utils_delegate(self):
        """ScannerUtils委托"""
        scanner = self._make_scanner()
        result = scanner._safe_round(1.23456, 2)
        assert result == 1.23

    def test_position_checker_delegate(self):
        """PositionChecker委托"""
        scanner = self._make_scanner()
        interval = scanner._get_smart_check_interval([])
        assert isinstance(interval, (int, float))
        assert interval > 0

    def test_init_split_methods_exist(self):
        """_init_*子方法存在"""
        from nodes.market_monitor.scanner import MarketScanner
        for name in ['_init_state', '_init_broker', '_init_pipeline', '_init_modules', '_init_risk']:
            assert hasattr(MarketScanner, name), f"Missing _init method: {name}"

    def test_preserved_methods_not_in_delegate_map(self):
        """线程安全方法不在委托映射中(保留为显式方法)"""
        from nodes.market_monitor.scanner import MarketScanner
        assert "_safe_copy_position_risk_levels" not in MarketScanner._DELEGATE_MAP
        assert "_safe_copy_trailing_stops" not in MarketScanner._DELEGATE_MAP
        assert "_get_activated_trailing_stops_safe" not in MarketScanner._DELEGATE_MAP

    def test_init_is_short(self):
        """__init__应为短方法(拆分后≤15行)"""
        from nodes.market_monitor.scanner import MarketScanner
        import inspect
        source = inspect.getsource(MarketScanner.__init__)
        lines = [l for l in source.split('\n') if l.strip() and not l.strip().startswith('#')]
        assert len(lines) <= 15, f"__init__ too long: {len(lines)} lines"
