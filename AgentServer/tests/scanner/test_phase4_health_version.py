"""Phase4.2: 版本信息与健康检查增强测试

验证:
1. /health端点包含version字段(git_hash/git_branch/design_doc_version)
2. _get_version_info返回正确结构
3. WS重连间隔3秒(设计文档规范)
4. 回测零影响
"""

import pytest
from unittest.mock import patch, MagicMock


# ============================================================================
# 1. _get_version_info
# ============================================================================

class TestVersionInfo:
    """验证版本信息辅助函数"""

    def test_version_info_has_required_fields(self):
        """_get_version_info应返回git_hash/git_branch/design_doc_version"""
        import importlib
        import sys
        # 动态导入scanner API模块
        api_path = "nodes.web.api.scanner_system"
        if api_path in sys.modules:
            mod = sys.modules[api_path]
        else:
            return  # 模块未加载,跳过
        
        if not hasattr(mod, '_get_version_info'):
            pytest.skip("_get_version_info not found in scanner API")
        
        info = mod._get_version_info()
        assert "git_hash" in info
        assert "git_branch" in info
        assert "design_doc_version" in info
        assert info["design_doc_version"] >= "v2.9.18"
        assert info["git_hash"]  # 不为空

    def test_version_info_git_fallback(self):
        """git命令失败时返回unknown"""
        import subprocess
        import sys
        api_path = "nodes.web.api.scanner_system"
        if api_path not in sys.modules:
            return
        
        mod = sys.modules[api_path]
        if not hasattr(mod, '_get_version_info'):
            pytest.skip("_get_version_info not found")
        
        # 【v2.9.10:清除版本缓存, 确保patch生效】
        if hasattr(mod, '_version_cache'):
            mod._version_cache["value"] = None
            mod._version_cache["ts"] = 0
        
        with patch("subprocess.check_output", side_effect=subprocess.SubprocessError("no git")):
            info = mod._get_version_info()
            assert info["git_hash"] == "unknown"
            assert info["git_branch"] == "unknown"

    def test_health_dead_includes_version(self):
        """Scanner未运行时/health也应包含version字段"""
        import os
        # 拆分后/health端点在scanner_system.py
        system_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'web', 'api', 'scanner_system.py'
        )
        if os.path.exists(system_path):
            with open(system_path) as f:
                source = f.read()
        else:
            pytest.skip("scanner_system.py not found")
        
        # 验证dead状态的health响应包含version(搜索更宽范围)
        dead_idx = source.find('"overall_status": "dead"')
        assert dead_idx > 0, "dead status not found in scanner_system.py"
        dead_section = source[dead_idx:dead_idx+500]
        assert '"version"' in dead_section or "'version'" in dead_section, \
            "dead状态health响应应包含version字段"

    def test_health_running_includes_version(self):
        """运行时/health响应应包含version字段"""
        import os
        # 拆分后/health端点在scanner_system.py
        system_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'web', 'api', 'scanner_system.py'
        )
        if os.path.exists(system_path):
            with open(system_path) as f:
                source = f.read()
        else:
            pytest.skip("scanner_system.py not found")
        
        # 验证version在_daemon_status之后
        assert '_get_version_info()' in source, \
            "/health应调用_get_version_info()"


# ============================================================================
# 2. WS重连间隔
# ============================================================================

class TestWSReconnect:
    """验证WS重连间隔符合设计文档(3秒)"""

    def test_ws_reconnect_3_seconds(self):
        """WS断线重连应为3秒(设计文档Phase4.1规范)"""
        import os
        # P0-3重构: WS重连从MarketMonitorView迁移到useWebSocket hook
        hook_path = os.path.join(
            os.path.dirname(__file__), '..', '..', '..', 'frontend',
            'src', 'hooks', 'useWebSocket.ts'
        )
        if not os.path.exists(hook_path):
            pytest.skip("useWebSocket hook not found")
        
        with open(hook_path) as f:
            source = f.read()
        
        # 检查默认重连间隔为3000ms
        assert "retryInterval = 3000" in source, \
            "useWebSocket默认重连间隔应为3000ms(3秒)"


# ============================================================================
# 3. Scanner Store集成
# ============================================================================

class TestScannerStoreIntegration:
    """验证Scanner Store与组件集成"""

    def test_store_has_data_freshness(self):
        """Scanner Store应包含dataFreshness计算属性"""
        import os
        store_path = os.path.join(
            os.path.dirname(__file__), '..', '..', '..', 'frontend', 
            'src', 'stores', 'scanner.ts'
        )
        if not os.path.exists(store_path):
            pytest.skip("Scanner store not found")
        
        with open(store_path) as f:
            source = f.read()
        
        assert "dataFreshness" in source
        assert "DataFreshness" in source
        assert "'green'" in source or '"green"' in source
        assert "'yellow'" in source or '"yellow"' in source
        assert "'red'" in source or '"red"' in source

    def test_store_has_ws_update(self):
        """Scanner Store应包含updateFromWs方法"""
        import os
        store_path = os.path.join(
            os.path.dirname(__file__), '..', '..', '..', 'frontend', 
            'src', 'stores', 'scanner.ts'
        )
        if not os.path.exists(store_path):
            pytest.skip("Scanner store not found")
        
        with open(store_path) as f:
            source = f.read()
        
        assert "updateFromWs" in source
        assert "refreshFromApi" in source

    def test_component_uses_store_for_freshness(self):
        """MarketMonitorView应使用ScannerStore+useWebSocket进行WS/REST数据管理"""
        import os
        view_path = os.path.join(
            os.path.dirname(__file__), '..', '..', '..', 'frontend', 
            'src', 'views', 'monitor', 'MarketMonitorView.vue'
        )
        if not os.path.exists(view_path):
            pytest.skip("Frontend file not found")
        
        with open(view_path) as f:
            source = f.read()
        
        # P0-2重构: script拆到useScannerMonitor composable, 组件调用composable
        assert "useScannerStore" in source or "useScannerMonitor" in source, "组件应导入useScannerStore或useScannerMonitor"
        # v2.9.64: MarketMonitorView script已拆到composable, scannerStore由composable内部使用
        assert "scannerStore" in source or "useScannerMonitor" in source, "组件应使用scannerStore或useScannerMonitor"
        # P0-2重构: WS逻辑已随useScannerMonitor迁移, 组件只调用composable
        assert "useScannerMonitor" in source or "wsHook" in source or "useWebSocket" in source, "组件应使用useScannerMonitor或useWebSocket hook"
        # 新鲜度样式 — v2.9.75: rb-freshness样式已移到OpsTab
        assert "rb-freshness" in source or "freshness" in source or "OpsTab" in source, "组件应包含新鲜度相关样式/逻辑或已提取到OpsTab"


# ============================================================================
# 4. 回测零影响
# ============================================================================

class TestNoBacktestRegressionPhase4:
    """验证Phase4改动不影响回测模块"""

    def test_sell_signal_checker_api_unchanged(self):
        """sell_signal_checker API未变"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        import inspect
        sig = inspect.signature(SellSignalChecker.check_realtime_sell)
        params = list(sig.parameters.keys())
        assert "position" in params
        # API已升级: realtime_data拆为realtime_price/high_price/open_price
        assert "realtime_price" in params or "realtime_data" in params

    def test_strategy_defaults_importable(self):
        """strategy_param_center可正常导入"""
        from nodes.market_monitor.strategy_param_center import StrategyParamCenter
        center = StrategyParamCenter()
        defaults = center._get_all_defaults()
        assert isinstance(defaults, dict)
        assert len(defaults) >= 4

    def test_portfolio_backtester_importable(self):
        """PortfolioBacktester可正常导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_version_info_not_in_backtest(self):
        """_get_version_info不应出现在回测模块中"""
        import os
        backtest_dir = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'backtest_engine'
        )
        if not os.path.exists(backtest_dir):
            return
        
        for root, dirs, files in os.walk(backtest_dir):
            for f in files:
                if f.endswith('.py'):
                    path = os.path.join(root, f)
                    with open(path) as fh:
                        if "_get_version_info" in fh.read():
                            pytest.fail(f"_get_version_info出现在回测模块: {path}")

    def test_scanner_daemon_not_in_backtest(self):
        """ScannerDaemon不应被回测模块引用"""
        import os
        backtest_dir = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'backtest_engine'
        )
        if not os.path.exists(backtest_dir):
            return
        
        for root, dirs, files in os.walk(backtest_dir):
            for f in files:
                if f.endswith('.py'):
                    path = os.path.join(root, f)
                    with open(path) as fh:
                        content = fh.read()
                        if "scanner_daemon" in content or "ScannerDaemon" in content:
                            pytest.fail(f"ScannerDaemon出现在回测模块: {path}")
