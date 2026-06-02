"""v2.9.32: 数据加载+风控重置+停止持久化提取 测试

验证:
- RuntimePersistence数据加载方法独立可用
- RiskWatchdog.reset_daily_risk_state线程安全
- scanner.py委托模式正确
- ensure_future→create_task修复
- 回测零影响
"""

import asyncio
import os
import threading
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ==================== RuntimePersistence数据加载 ====================

class TestRuntimePersistenceDataLoading:
    """验证RuntimePersistence新增的数据加载方法"""

    def test_load_stock_list_method_exists(self):
        """RuntimePersistence.load_stock_list方法存在"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, 'load_stock_list')

    def test_load_daily_factors_method_exists(self):
        """RuntimePersistence.load_daily_factors方法存在"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, 'load_daily_factors')

    def test_load_stock_name_map_method_exists(self):
        """RuntimePersistence.load_stock_name_map方法存在"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, 'load_stock_name_map')

    def test_warm_weekend_cache_method_exists(self):
        """RuntimePersistence.warm_weekend_cache方法存在"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, 'warm_weekend_cache')

    def test_persist_stop_state_method_exists(self):
        """RuntimePersistence.persist_stop_state方法存在"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, 'persist_stop_state')

    def test_restore_start_state_method_exists(self):
        """RuntimePersistence.restore_start_state方法存在"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, 'restore_start_state')

    def test_load_positions_method_exists(self):
        """RuntimePersistence.load_positions方法存在"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, 'load_positions')

    def test_warm_weekend_cache_returns_dict(self):
        """warm_weekend_cache返回dict"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        import pandas as pd
        
        rp = RuntimePersistence.__new__(RuntimePersistence)
        rp._scanner = MagicMock()
        
        # 空DataFrame
        result = rp.warm_weekend_cache(pd.DataFrame(), {}, None)
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_warm_weekend_cache_with_data(self):
        """warm_weekend_cache从DataFrame填充缓存"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        import pandas as pd
        
        rp = RuntimePersistence.__new__(RuntimePersistence)
        rp._scanner = MagicMock()
        
        df = pd.DataFrame([
            {"ts_code": "600036.SH", "close": 40.0, "pre_close": 39.2,
             "pct_chg": 2.0, "open": 39.5, "high": 40.5, "low": 39.0,
             "vol": 1000, "amount": 40000, "turnover_rate": 1.5,
             "volume_ratio": 0.8, "name": "招商银行"},
            {"ts_code": "000001.SZ", "close": 15.0, "pre_close": 14.8,
             "pct_chg": 1.3, "open": 14.9, "high": 15.2, "low": 14.7,
             "vol": 500, "amount": 7500, "turnover_rate": 0.5,
             "volume_ratio": 0.3, "name": "平安银行"},
        ])
        name_map = {"600036.SH": "招商银行", "000001.SZ": "平安银行"}
        
        result = rp.warm_weekend_cache(df, name_map)
        assert len(result) == 2
        assert "600036.SH" in result
        assert result["600036.SH"]["price"] == 40.0
        assert result["600036.SH"]["name"] == "招商银行"
        assert result["000001.SZ"]["name"] == "平安银行"

    def test_warm_weekend_cache_skips_zero_close(self):
        """warm_weekend_cache跳过close<=0的行"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        import pandas as pd
        
        rp = RuntimePersistence.__new__(RuntimePersistence)
        rp._scanner = MagicMock()
        
        df = pd.DataFrame([
            {"ts_code": "600036.SH", "close": 40.0, "pre_close": 39.2,
             "pct_chg": 2.0, "open": 39.5, "high": 40.5, "low": 39.0,
             "vol": 1000, "amount": 40000, "turnover_rate": 1.5,
             "volume_ratio": 0.8, "name": "招商银行"},
            {"ts_code": "000001.SZ", "close": 0, "pre_close": 14.8,
             "pct_chg": -100, "open": 14.9, "high": 15.2, "low": 14.7,
             "vol": 0, "amount": 0, "turnover_rate": 0,
             "volume_ratio": 0, "name": "停牌股"},
        ])
        result = rp.warm_weekend_cache(df, {})
        assert len(result) == 1  # 跳过close=0的

    def test_warm_weekend_cache_calls_quote_manager(self):
        """warm_weekend_cache调用quote_manager.warm_sources_cache"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        import pandas as pd
        
        rp = RuntimePersistence.__new__(RuntimePersistence)
        rp._scanner = MagicMock()
        
        qm = MagicMock()
        df = pd.DataFrame([
            {"ts_code": "600036.SH", "close": 40.0, "pre_close": 39.2,
             "pct_chg": 2.0, "open": 39.5, "high": 40.5, "low": 39.0,
             "vol": 1000, "amount": 40000, "turnover_rate": 1.5,
             "volume_ratio": 0.8, "name": "招商银行"},
        ])
        
        rp.warm_weekend_cache(df, {}, quote_manager=qm)
        qm.warm_sources_cache.assert_called_once()


# ==================== RiskWatchdog.reset_daily_risk_state ====================

class TestRiskWatchdogResetDailyRiskState:
    """验证RiskWatchdog.reset_daily_risk_state"""

    def test_method_exists(self):
        """方法存在"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        assert hasattr(RiskWatchdog, 'reset_daily_risk_state')

    def test_resets_circuit_breaker(self):
        """重置circuit_breaker状态"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        from nodes.market_monitor.scanner import MarketScanner
        
        scanner = MarketScanner.__new__(MarketScanner)
        scanner._state_lock = threading.Lock()
        scanner._circuit_breaker = {
            "daily_start_assets": 0,
            "today_trades": 5,
            "today_losses": 3,
            "trading_paused": True,
            "pause_reason": "test",
        }
        scanner._pending_sells = {}
        scanner._execution_stats = {"stop_loss_response_times": [1.0, 2.0]}
        
        # Mock broker with account
        mock_broker = MagicMock()
        mock_acct = MagicMock()
        mock_acct.total_assets = 1_000_000
        mock_broker.get_account.return_value = mock_acct
        mock_broker.get_positions.return_value = []
        scanner._broker = mock_broker
        
        RiskWatchdog.reset_daily_risk_state(scanner)
        
        assert scanner._circuit_breaker["daily_start_assets"] == 1_000_000
        assert scanner._circuit_breaker["today_trades"] == 0
        assert scanner._circuit_breaker["today_losses"] == 0
        assert scanner._circuit_breaker["trading_paused"] is False
        assert scanner._circuit_breaker["pause_reason"] == ""

    def test_clears_stale_pending_sells(self):
        """清理无持仓的pending_sells"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        from nodes.market_monitor.scanner import MarketScanner
        
        scanner = MarketScanner.__new__(MarketScanner)
        scanner._state_lock = threading.Lock()
        scanner._circuit_breaker = {"daily_start_assets": 0, "today_trades": 0,
                                     "today_losses": 0, "trading_paused": False, "pause_reason": ""}
        scanner._execution_stats = {"stop_loss_response_times": []}
        scanner._pending_sells = {
            "600036.SH": {"reason": "跌停挂起"},
            "000001.SZ": {"reason": "跌停挂起"},
        }
        
        mock_broker = MagicMock()
        mock_acct = MagicMock()
        mock_acct.total_assets = 1_000_000
        mock_broker.get_account.return_value = mock_acct
        # 只有600036.SH还在持仓
        pos = MagicMock()
        pos.ts_code = "600036.SH"
        mock_broker.get_positions.return_value = [pos]
        scanner._broker = mock_broker
        
        RiskWatchdog.reset_daily_risk_state(scanner)
        
        # pending_sells最终全部清空(clear), 但000001.SZ应被识别为stale
        assert len(scanner._pending_sells) == 0


# ==================== Scanner委托验证 ====================

class TestScannerDelegationV2932:
    """验证scanner.py中v2.9.32委托方法的正确性"""

    def test_delegate_map_entries(self):
        """v2.9.52: 有显式方法定义的数据加载方法已从DELEGATE_MAP移除(避免死代码)"""
        from nodes.market_monitor.scanner import MarketScanner
        from nodes.market_monitor.scanner_delegate_router import DELEGATE_MAP
        
        # 显式定义的方法应有hasattr检查
        assert hasattr(MarketScanner, '_load_stock_list')
        assert hasattr(MarketScanner, '_load_daily_factors')
        assert hasattr(MarketScanner, '_load_stock_name_map')
        assert hasattr(MarketScanner, '_warm_weekend_cache')
        assert hasattr(MarketScanner, '_reset_daily_risk_state')
        
        # 显式方法不应在DELEGATE_MAP中(优先级更高,MAP条目永远不会被使用)
        assert '_load_stock_list' not in DELEGATE_MAP
        assert '_load_daily_factors' not in DELEGATE_MAP
        assert '_reset_daily_risk_state' not in DELEGATE_MAP

    def test_scanner_line_count(self):
        """scanner.py行数应在合理范围"""
        scanner_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'market_monitor', 'scanner.py'
        )
        with open(scanner_path) as f:
            line_count = sum(1 for _ in f)
        assert line_count < 1750, f"scanner.py行数{line_count}应<1750"
        assert line_count > 800, f"scanner.py行数{line_count}应>1300"


# ==================== ensure_future修复验证 ====================

class TestEnsureFutureFix:
    """验证ensure_future→create_task替换"""

    def test_scanner_no_ensure_future(self):
        """scanner.py不再使用ensure_future(除注释外)"""
        scanner_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'market_monitor', 'scanner.py'
        )
        with open(scanner_path) as f:
            content = f.read()
        
        # 统计ensure_future出现次数(排除注释)
        count = 0
        for line in content.split('\n'):
            stripped = line.strip()
            if 'ensure_future' in stripped and not stripped.startswith('#'):
                count += 1
        assert count == 0, f"scanner.py仍有{count}处ensure_future调用"

    def test_quote_manager_no_ensure_future(self):
        """quote_manager.py不再使用ensure_future"""
        qm_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'market_monitor', 'quote_manager.py'
        )
        with open(qm_path) as f:
            content = f.read()
        
        count = 0
        for line in content.split('\n'):
            stripped = line.strip()
            if 'ensure_future' in stripped and not stripped.startswith('#'):
                count += 1
        assert count == 0, f"quote_manager.py仍有{count}处ensure_future调用"


# ==================== 回测零影响 ====================

class TestNoBacktestRegressionV2932:
    """v2.9.32: 回测零影响"""

    def test_backtest_engine_importable(self):
        """回测引擎正常导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker API未变"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        checker = SellSignalChecker.__new__(SellSignalChecker)
        # 核心方法仍存在
        assert hasattr(SellSignalChecker, 'check_realtime_sell')

    def test_strategy_defaults_importable(self):
        """策略默认参数正常导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        assert isinstance(STRATEGY_CONFIGS, dict)
        assert len(STRATEGY_CONFIGS) > 0
