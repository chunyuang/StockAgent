"""v2.9.13: _scan_loop时间段提取 + 线程安全修复 测试"""
import asyncio
import threading
import time
from unittest.mock import MagicMock, AsyncMock, patch
import pytest


# ==================== _scan_loop时间段提取 ====================

class TestScanLoopTradingExtraction:
    """验证_scan_loop_trading提取方法"""

    def test_scan_loop_trading_exists(self):
        """MarketScanner有_scan_loop_trading方法"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_scan_loop_trading')

    def test_scan_loop_trading_is_async(self):
        """_scan_loop_trading是async方法"""
        from nodes.market_monitor.scanner import MarketScanner
        import inspect
        assert inspect.iscoroutinefunction(MarketScanner._scan_loop_trading)

    def test_scan_loop_trading_returns_bool(self):
        """_scan_loop_trading返回类型注解为bool"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        src = inspect.getsource(MarketScanner._scan_loop_trading)
        # 验证签名包含 -> bool
        assert '-> bool' in src.split('\n')[0]

    def test_scan_loop_settlement_exists(self):
        """MarketScanner有_scan_loop_settlement方法"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_scan_loop_settlement')

    def test_scan_loop_settlement_is_async(self):
        """_scan_loop_settlement是async方法"""
        from nodes.market_monitor.scanner import MarketScanner
        import inspect
        assert inspect.iscoroutinefunction(MarketScanner._scan_loop_settlement)


class TestScanLoopTradingLogic:
    """_scan_loop_trading业务逻辑验证"""

    def _make_scanner(self):
        from nodes.market_monitor.scanner import MarketScanner
        config = {"initial_cash": 1_000_000}
        scanner = MarketScanner(config=config)
        scanner._broker = MagicMock()
        scanner._broker.get_positions.return_value = []
        scanner._quote_manager = MagicMock()
        scanner._quote_manager.should_try_recover.return_value = False
        scanner._risk_running = False
        scanner._risk_thread = None
        scanner._risk_thread_restarts = 0
        scanner._event_bus = MagicMock()
        scanner._event_bus.emit = AsyncMock()
        return scanner

    @pytest.mark.asyncio
    async def test_trading_returns_true_on_full_scan(self):
        """全量扫描时返回True"""
        scanner = self._make_scanner()
        scanner.scan_once = AsyncMock()
        # last_full_scan = 0 → elapsed >> SCAN_INTERVAL
        result = await scanner._scan_loop_trading("20260530", 0)
        assert result is True
        scanner.scan_once.assert_called_once()

    @pytest.mark.asyncio
    async def test_trading_returns_false_on_wait(self):
        """等待时返回False"""
        scanner = self._make_scanner()
        scanner.scan_once = AsyncMock()
        # last_full_scan = now → elapsed ≈ 0
        result = await scanner._scan_loop_trading("20260530", time.time())
        assert result is False
        scanner.scan_once.assert_not_called()


class TestScanLoopSettlementLogic:
    """_scan_loop_settlement业务逻辑验证"""

    def _make_scanner(self):
        from nodes.market_monitor.scanner import MarketScanner
        config = {"initial_cash": 1_000_000}
        scanner = MarketScanner(config=config)
        scanner._broker = MagicMock()
        scanner._broker.account = MagicMock()
        scanner._broker.account.today_profit = 100
        scanner._broker.account.total_assets = 1_000_100
        scanner._broker.save_state = AsyncMock()
        scanner._event_bus = MagicMock()
        scanner._event_bus.emit = AsyncMock()
        scanner._save_timeline = AsyncMock()
        return scanner

    @pytest.mark.asyncio
    async def test_settlement_calls_daily_settlement(self):
        """盘后结算调用broker.daily_settlement"""
        scanner = self._make_scanner()
        await scanner._scan_loop_settlement("20260530")
        scanner._broker.daily_settlement.assert_called_once_with("20260530")

    @pytest.mark.asyncio
    async def test_settlement_saves_state(self):
        """盘后结算保存broker状态"""
        scanner = self._make_scanner()
        await scanner._scan_loop_settlement("20260530")
        scanner._broker.save_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_settlement_emits_daily_settled(self):
        """盘后结算发射DAILY_SETTLED事件"""
        scanner = self._make_scanner()
        await scanner._scan_loop_settlement("20260530")
        scanner._event_bus.emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_settlement_saves_timeline(self):
        """盘后结算保存timeline"""
        scanner = self._make_scanner()
        await scanner._scan_loop_settlement("20260530")
        scanner._save_timeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_settlement_broker_failure_safe(self):
        """broker.save_state失败不影响结算"""
        scanner = self._make_scanner()
        scanner._broker.save_state = AsyncMock(side_effect=Exception("MongoDB down"))
        await scanner._scan_loop_settlement("20260530")  # 不应抛异常
        scanner._broker.daily_settlement.assert_called_once()


# ==================== 线程安全修复 ====================

class TestPositionManagerEffectiveStopPriceThreadSafety:
    """PositionManager.get_effective_stop_price线程安全修复"""

    def test_uses_safe_read_method(self):
        """get_effective_stop_price使用_get_trailing_stop_safe(线程安全)"""
        import inspect
        from nodes.market_monitor.position_manager import PositionManager
        src = inspect.getsource(PositionManager.get_effective_stop_price)
        assert '_get_trailing_stop_safe' in src
        # 不应直接访问trailing_stops.get
        assert 'self.trailing_stops.get' not in src

    def test_trailing_stop_safe_returns_copy(self):
        """_get_trailing_stop_safe返回深拷贝"""
        from nodes.market_monitor.position_manager import PositionManager
        scanner = MagicMock()
        scanner._state_lock = threading.Lock()
        scanner._trailing_stops = {"600036.SH": {"activated": True, "stop_price": 40.0, "high_price": 42.0}}
        pm = PositionManager(scanner)
        result = pm._get_trailing_stop_safe("600036.SH")
        assert result is not None
        assert result["stop_price"] == 40.0
        # 修改拷贝不影响原始
        result["stop_price"] = 999
        assert pm._scanner._trailing_stops["600036.SH"]["stop_price"] == 40.0


class TestScannerPremarketLocks:
    """scanner.premarket_prepare中共享状态写操作加锁"""

    def test_circuit_breaker_reset_uses_lock(self):
        """premarket_prepare中_circuit_breaker重置使用state_lock"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        src = inspect.getsource(MarketScanner.premarket_prepare)
        # v2.9.17: 应该有state_lock保护circuit_breaker写入(直接with或_with_state_lock)
        # 检查方法体中包含lock相关代码(在circuit_breaker赋值附近)
        lines = src.split('\n')
        cb_lines = [i for i, l in enumerate(lines) if 'circuit_breaker' in l and '=' in l and 'daily_start_assets' in l]
        if cb_lines:
            # 找到circuit_breaker赋值行，检查之前10行内是否有lock
            for idx in cb_lines:
                context = '\n'.join(lines[max(0, idx-10):idx])
                assert ('_state_lock' in context or '_with_state_lock' in context), \
                    f"circuit_breaker赋值附近缺少lock保护 (line {idx})"

    def test_pending_sells_clear_uses_lock(self):
        """_pending_sells.clear()使用state_lock(v2.9.21:在_reset_daily_risk_state中)"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        # v2.9.21: _pending_sells.clear()从premarket_prepare提取到_reset_daily_risk_state
        src = inspect.getsource(MarketScanner._reset_daily_risk_state)
        lines = src.split('\n')
        found_lock_protection = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            if '_pending_sells.clear()' in stripped:
                for j in range(max(0, i-10), i):
                    if ('with lock:' in lines[j] or 'with self._state_lock:' in lines[j]
                            or '_with_state_lock' in lines[j]):
                        found_lock_protection = True
                        break
                break
        assert found_lock_protection, "_pending_sells.clear()缺少lock保护"


class TestTrailingStopsSafeRead:
    """scanner中trailing_stops读取线程安全"""

    def test_load_positions_trailing_count_safe(self):
        """_load_positions中trailing_stops计数使用安全读取"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        src = inspect.getsource(MarketScanner._load_positions)
        # v2.9.13: 不应直接len(self._trailing_stops)(无锁)
        # 允许在_safe_copy_trailing_stops返回值上用len()
        assert 'len(self._safe_copy_trailing_stops())' in src, "应使用_safe_copy_trailing_stops()安全读取"


# ==================== 死代码清理 ====================

class TestBakFileCleanup:
    """确认.bak文件已清理"""

    def test_no_scanner_bak(self):
        """scanner.py.bak已删除"""
        import os
        assert not os.path.exists('AgentServer/nodes/market_monitor/scanner.py.bak')

    def test_no_position_checker_bak(self):
        """position_checker.py.bak已删除"""
        import os
        assert not os.path.exists('AgentServer/nodes/market_monitor/position_checker.py.bak')


# ==================== _scan_loop结构验证 ====================

class TestScanLoopStructure:
    """验证_scan_loop结构简化"""

    def test_scan_loop_references_trading(self):
        """_scan_loop调用_scan_loop_trading"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        src = inspect.getsource(MarketScanner._scan_loop)
        assert '_scan_loop_trading' in src

    def test_scan_loop_references_settlement(self):
        """_scan_loop调用_scan_loop_settlement"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        src = inspect.getsource(MarketScanner._scan_loop)
        assert '_scan_loop_settlement' in src

    def test_scan_loop_shorter(self):
        """_scan_loop行数应<100(v2.9.13提取后)"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        src = inspect.getsource(MarketScanner._scan_loop)
        line_count = len(src.split('\n'))
        assert line_count < 100, f"_scan_loop仍有{line_count}行, 期望<100"


# ==================== 回测无影响 ====================

class TestNoBacktestRegressionV2913:
    """v2.9.13不影响回测模块"""

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker API未变"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        assert hasattr(SellSignalChecker, 'check_realtime_sell')
        assert hasattr(SellSignalChecker, 'check_full_sell')

    def test_strategy_defaults_importable(self):
        """策略默认参数正常导入"""
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        assert 'stop_loss_pct' in GLOBAL_RISK

    def test_portfolio_backtester_importable(self):
        """回测引擎正常导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_scanner_changes_not_in_backtest_path(self):
        """scanner修改不影响回测导入路径"""
        import importlib
        # 确认backtest引擎不引用scanner模块
        bt_mod = importlib.import_module('nodes.backtest_engine.factor_selection.portfolio_backtest')
        src = open(bt_mod.__file__).read()
        assert 'market_monitor.scanner' not in src
        assert 'position_manager' not in src

    def test_new_methods_not_in_backtest(self):
        """新增方法_scan_loop_trading/_scan_loop_settlement不在回测路径中"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert not hasattr(PortfolioBacktester, '_scan_loop_trading')
        assert not hasattr(PortfolioBacktester, '_scan_loop_settlement')
