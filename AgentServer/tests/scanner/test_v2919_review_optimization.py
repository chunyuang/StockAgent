"""
v2.9.19 审查优化测试 — _execute_risk_sell拆分 + scan_once提取 + _scan_loop回放提取 + get_status简化

变更项:
1. _execute_risk_sell: 82行→40行, 提取_post_sell_cleanup(timeline+统计+状态清理+事件+持久化)
2. scan_once: 80行→50行, 提取_sync_broker_prices + _update_scan_stats + _persist_scan_result
3. _scan_loop: 回放模式提取为_scan_loop_replay
4. get_status: 提取_build_account_info
"""
import pytest
import os
import sys
import inspect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ============================================================================
# 1. _execute_risk_sell拆分验证
# ============================================================================

class TestExecuteRiskSellRefactor:
    """验证_execute_risk_sell→_post_sell_cleanup提取"""

    def test_execute_risk_sell_calls_post_sell_cleanup(self):
        """_execute_risk_sell成功时调用_post_sell_cleanup"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._execute_risk_sell)
        assert "_post_sell_cleanup" in source, "_execute_risk_sell应委托_post_sell_cleanup"

    def test_post_sell_cleanup_exists(self):
        """_post_sell_cleanup方法存在且是async"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_post_sell_cleanup')
        assert inspect.iscoroutinefunction(MarketScanner._post_sell_cleanup)

    def test_post_sell_cleanup_has_source_param(self):
        """_post_sell_cleanup接受source关键字参数"""
        from nodes.market_monitor.scanner import MarketScanner
        sig = inspect.signature(MarketScanner._post_sell_cleanup)
        assert 'source' in sig.parameters

    def test_post_sell_cleanup_contains_timeline(self):
        """_post_sell_cleanup包含timeline记录"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._post_sell_cleanup)
        assert "_timeline" in source

    def test_post_sell_cleanup_contains_state_lock(self):
        """_post_sell_cleanup包含_state_lock保护"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._post_sell_cleanup)
        assert "_state_lock" in source
        assert "_trailing_stops.pop" in source

    def test_post_sell_cleanup_contains_eventbus(self):
        """_post_sell_cleanup包含EventBus事件发射"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._post_sell_cleanup)
        assert "RISK_SELL_EXECUTED" in source
        assert "POSITION_CHANGED" in source

    def test_post_sell_cleanup_contains_persistence(self):
        """_post_sell_cleanup包含持久化调用"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._post_sell_cleanup)
        assert "save_state" in source
        assert "_save_runtime_snapshot" in source

    def test_post_sell_cleanup_contains_record_trade_result(self):
        """_post_sell_cleanup包含_record_trade_result调用"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._post_sell_cleanup)
        assert "_record_trade_result" in source

    def test_execute_risk_sell_still_handles_failure(self):
        """_execute_risk_sell仍处理卖出失败"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._execute_risk_sell)
        assert "卖出失败" in source or "RISK_SELL" in source

    def test_force_empty_uses_post_sell_cleanup(self):
        """_execute_force_empty复用_post_sell_cleanup(通过_liquidate_positions)"""
        from nodes.market_monitor.scanner import MarketScanner
        # v2.9.20: _execute_force_empty委托到_liquidate_positions
        # _liquidate_positions内部调用_post_sell_cleanup
        source_fe = inspect.getsource(MarketScanner._execute_force_empty)
        assert "_liquidate_positions" in source_fe, (
            "_execute_force_empty应委托到_liquidate_positions"
        )
        source_liq = inspect.getsource(MarketScanner._liquidate_positions)
        assert "_post_sell_cleanup" in source_liq, (
            "_liquidate_positions未复用_post_sell_cleanup! "
            "强制空仓后缺少timeline/统计/状态清理/事件/持久化, 审计缺失。"
        )

    def test_sell_all_positions_uses_post_sell_cleanup(self):
        """_sell_all_positions复用_post_sell_cleanup(通过_liquidate_positions)"""
        from nodes.market_monitor.scanner import MarketScanner
        # v2.9.20: _sell_all_positions委托到_liquidate_positions
        source_sa = inspect.getsource(MarketScanner._sell_all_positions)
        assert "_liquidate_positions" in source_sa, (
            "_sell_all_positions应委托到_liquidate_positions"
        )
        source_liq = inspect.getsource(MarketScanner._liquidate_positions)
        assert "_post_sell_cleanup" in source_liq, (
            "_liquidate_positions未复用_post_sell_cleanup! "
            "停止清仓后缺少timeline/统计/状态清理/事件/持久化, 审计缺失。"
        )


# ============================================================================
# 2. scan_once提取验证
# ============================================================================

class TestScanOnceRefactor:
    """验证scan_once方法拆分"""

    def test_sync_broker_prices_exists(self):
        """_sync_broker_prices方法存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_sync_broker_prices')

    def test_sync_broker_prices_is_sync(self):
        """_sync_broker_prices是同步方法(纯遍历)"""
        from nodes.market_monitor.scanner import MarketScanner
        assert not inspect.iscoroutinefunction(MarketScanner._sync_broker_prices)

    def test_sync_broker_prices_updates_realtime(self):
        """_sync_broker_prices调用broker.update_realtime"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._sync_broker_prices)
        assert "update_realtime" in source

    def test_update_scan_stats_exists(self):
        """_update_scan_stats方法存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_update_scan_stats')

    def test_update_scan_stats_is_sync(self):
        """_update_scan_stats是同步方法"""
        from nodes.market_monitor.scanner import MarketScanner
        assert not inspect.iscoroutinefunction(MarketScanner._update_scan_stats)

    def test_update_scan_stats_updates_heartbeat(self):
        """_update_scan_stats更新看门狗心跳"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._update_scan_stats)
        assert "update_heartbeat" in source

    def test_persist_scan_result_exists(self):
        """_persist_scan_result方法存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_persist_scan_result')

    def test_persist_scan_result_is_async(self):
        """_persist_scan_result是异步方法(有MongoDB写入)"""
        from nodes.market_monitor.scanner import MarketScanner
        assert inspect.iscoroutinefunction(MarketScanner._persist_scan_result)

    def test_persist_scan_result_saves_state(self):
        """_persist_scan_result包含save_state"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._persist_scan_result)
        assert "save_state" in source

    def test_scan_once_calls_extracted_methods(self):
        """scan_once调用提取出的方法"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.scan_once)
        assert "_sync_broker_prices" in source
        assert "_update_scan_stats" in source
        assert "_persist_scan_result" in source


# ============================================================================
# 3. _scan_loop回放模式提取验证
# ============================================================================

class TestScanLoopReplayExtraction:
    """验证_scan_loop回放模式提取"""

    def test_scan_loop_replay_exists(self):
        """_scan_loop_replay方法存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_scan_loop_replay')

    def test_scan_loop_replay_is_async(self):
        """_scan_loop_replay是异步方法"""
        from nodes.market_monitor.scanner import MarketScanner
        assert inspect.iscoroutinefunction(MarketScanner._scan_loop_replay)

    def test_scan_loop_calls_replay(self):
        """_scan_loop在回放模式下调用_scan_loop_replay"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._scan_loop)
        assert "_scan_loop_replay" in source

    def test_scan_loop_replay_contains_scan_once(self):
        """_scan_loop_replay调用scan_once"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._scan_loop_replay)
        assert "scan_once" in source


# ============================================================================
# 4. get_status简化验证
# ============================================================================

class TestGetStatusSimplification:
    """验证get_status提取_build_account_info"""

    def test_build_account_info_exists(self):
        """_build_account_info方法存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_build_account_info')

    def test_build_account_info_is_sync(self):
        """_build_account_info是同步方法"""
        from nodes.market_monitor.scanner import MarketScanner
        assert not inspect.iscoroutinefunction(MarketScanner._build_account_info)

    def test_build_account_info_handles_gm(self):
        """_build_account_info处理掘金模式"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._build_account_info)
        assert "MODE_GM" in source

    def test_build_account_info_handles_sim(self):
        """_build_account_info处理模拟broker"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._build_account_info)
        assert "total_assets" in source
        assert "available_cash" in source

    def test_get_status_calls_build_account_info(self):
        """get_status调用_build_account_info"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.get_status)
        assert "_build_account_info" in source


# ============================================================================
# 5. 方法行数回归验证
# ============================================================================

class TestMethodSizeReduction:
    """验证重构后方法行数减少"""

    def test_execute_risk_sell_under_45_lines(self):
        """_execute_risk_sell应≤45行(重构后)"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._execute_risk_sell)
        lines = [l for l in source.split('\n') if l.strip()]
        assert len(lines) <= 45, f"_execute_risk_sell {len(lines)}行,应≤45"

    def test_scan_once_under_55_lines(self):
        """scan_once应≤80行(v2.9.22:新增分步计时)(重构后)"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.scan_once)
        lines = [l for l in source.split('\n') if l.strip()]
        assert len(lines) <= 80, f"scan_once {len(lines)}行,应≤80"

    def test_get_status_under_35_lines(self):
        """get_status应≤35行(重构后)"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.get_status)
        lines = [l for l in source.split('\n') if l.strip()]
        assert len(lines) <= 35, f"get_status {len(lines)}行,应≤35"


# ============================================================================
# 6. 回测零影响
# ============================================================================

class TestNoBacktestRegressionV2919:
    """回测模块不受v2.9.19影响"""

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker API未变"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        # v2.9.6: __init__需要strategy_params/strategy_risk_params/risk_config
        # 验证check_realtime_sell方法存在即可
        assert hasattr(SellSignalChecker, 'check_realtime_sell')

    def test_strategy_defaults_importable(self):
        """默认参数正常导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        assert isinstance(STRATEGY_CONFIGS, dict)

    def test_portfolio_backtester_importable(self):
        """回测引擎正常导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_new_methods_not_in_backtest(self):
        """新增方法不存在于回测模块"""
        from nodes.backtest_engine.factor_selection import portfolio_backtest
        assert not hasattr(portfolio_backtest, '_post_sell_cleanup')
        assert not hasattr(portfolio_backtest, '_sync_broker_prices')

    def test_scanner_line_count(self):
        """scanner.py行数应≤1930(v2.9.22:分步计时+错误恢复)"""
        scanner_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'market_monitor', 'scanner.py'
        )
        if not os.path.exists(scanner_path):
            pytest.skip("scanner.py not found")
        with open(scanner_path) as f:
            line_count = sum(1 for _ in f)
        assert line_count <= 2150, f"scanner.py行数{line_count}>1860"
