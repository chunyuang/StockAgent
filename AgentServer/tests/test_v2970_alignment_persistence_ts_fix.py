"""v2.9.70 测试: Compare对齐统计持久化+通知+恢复 + TypeScript修复

测试范围:
1. CompareAlignmentStats.from_dict恢复
2. CompareAlignmentStats.record返回值(notify_ready)
3. _persist_alignment_stats方法存在
4. _restore_alignment_stats方法存在+初始化调用
5. /alignment-stats API端点
6. 版本常量v2.9.70
7. 前端TS修复验证
8. 回测零影响
"""
import pytest
import sys
import os
import inspect

# 项目路径
AGENT_SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, AGENT_SERVER)


class TestCompareAlignmentStatsFromDict:
    """CompareAlignmentStats.from_dict恢复"""

    def test_from_dict_basic(self):
        """从字典恢复基本统计"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        data = {
            "total_checks": 100,
            "total_positions": 500,
            "agreement_count": 95,
            "only_legacy_count": 3,
            "only_checker_count": 2,
            "both_count": 90,
            "consecutive_agree": 25,
            "max_consecutive_agree": 30,
            "last_check_time": "2026-06-03 14:30:00",
            "first_check_time": "2026-06-01 09:30:00",
            "notified_switch_ready": True,
        }
        stats = CompareAlignmentStats.from_dict(data)
        assert stats.total_checks == 100
        assert stats.total_positions == 500
        assert stats.agreement_count == 95
        assert stats.consecutive_agree == 25
        assert stats._notified_switch_ready is True

    def test_from_dict_empty(self):
        """空字典使用默认值"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats.from_dict({})
        assert stats.total_checks == 0
        assert stats.agreement_count == 0
        assert stats.consecutive_agree == 0
        assert stats._notified_switch_ready is False

    def test_from_dict_partial(self):
        """部分字段缺失使用默认值"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats.from_dict({"total_checks": 10, "agreement_count": 8})
        assert stats.total_checks == 10
        assert stats.agreement_count == 8
        assert stats.both_count == 0  # 缺失字段默认0

    def test_from_dict_to_dict_roundtrip(self):
        """to_dict→from_dict往返一致性"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        original = CompareAlignmentStats()
        original.total_checks = 50
        original.agreement_count = 48
        original.consecutive_agree = 20
        original.both_count = 45
        original.last_check_time = "2026-06-03 15:00:00"
        original.first_check_time = "2026-06-03 09:30:00"
        original._notified_switch_ready = True
        
        restored = CompareAlignmentStats.from_dict(original.to_dict())
        assert restored.total_checks == original.total_checks
        assert restored.agreement_count == original.agreement_count
        assert restored.consecutive_agree == original.consecutive_agree
        assert restored.both_count == original.both_count
        assert restored._notified_switch_ready == original._notified_switch_ready


class TestCompareAlignmentStatsRecordReturn:
    """record返回值: switch_ready变更通知"""

    def test_record_returns_false_initially(self):
        """初始状态record返回False(未达到切换条件)"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        result = stats.record(set(), set(), {"000001.SZ"})
        assert result is False

    def test_record_returns_true_when_becomes_ready(self):
        """达到切换条件时返回True"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        # 模拟49次一致
        for _ in range(49):
            stats.record(set(), set(), {"000001.SZ"})
        # 第50次一致, 此时total_checks=50, consecutive=50, alignment_rate=1.0
        result = stats.record(set(), set(), {"000001.SZ"})
        assert result is True
        assert stats.switch_ready is True
        assert stats._notified_switch_ready is True

    def test_record_returns_false_when_already_ready(self):
        """已就绪后后续record返回False(不是'首次'就绪)"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        for _ in range(51):
            stats.record(set(), set(), {"000001.SZ"})
        # 第51次: 已就绪, not became_ready
        result = stats.record(set(), set(), {"000001.SZ"})
        assert result is False

    def test_record_resets_on_disagreement(self):
        """不一致时consecutive_agree重置"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        for _ in range(49):
            stats.record(set(), set(), {"000001.SZ"})
        assert stats.consecutive_agree == 49
        # 不一致
        stats.record({"000002.SZ"}, set(), {"000001.SZ"})
        assert stats.consecutive_agree == 0

    def test_to_dict_includes_notified_flag(self):
        """to_dict包含notified_switch_ready字段"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        d = stats.to_dict()
        assert "notified_switch_ready" in d
        assert d["notified_switch_ready"] is False


class TestPersistAlignmentStats:
    """_persist_alignment_stats方法"""

    def test_method_exists(self):
        """方法存在"""
        from nodes.market_monitor.position_checker import PositionChecker
        assert hasattr(PositionChecker, '_persist_alignment_stats')

    def test_method_is_async(self):
        """方法是异步"""
        import inspect
        from nodes.market_monitor.position_checker import PositionChecker
        method = PositionChecker._persist_alignment_stats
        assert inspect.iscoroutinefunction(method)

    def test_method_has_docstring(self):
        """方法有文档字符串"""
        from nodes.market_monitor.position_checker import PositionChecker
        assert PositionChecker._persist_alignment_stats.__doc__ is not None
        assert "持久化" in PositionChecker._persist_alignment_stats.__doc__


class TestRestoreAlignmentStats:
    """_restore_alignment_stats方法"""

    def test_method_exists(self):
        """方法存在"""
        from nodes.market_monitor.position_checker import PositionChecker
        assert hasattr(PositionChecker, '_restore_alignment_stats')

    def test_method_is_sync(self):
        """方法是同步(启动时调用)"""
        import inspect
        from nodes.market_monitor.position_checker import PositionChecker
        method = PositionChecker._restore_alignment_stats
        assert not inspect.iscoroutinefunction(method)

    def test_method_has_docstring(self):
        """方法有文档字符串"""
        from nodes.market_monitor.position_checker import PositionChecker
        assert PositionChecker._restore_alignment_stats.__doc__ is not None
        assert "恢复" in PositionChecker._restore_alignment_stats.__doc__

    def test_init_calls_restore(self):
        """__init__调用_restore_alignment_stats"""
        import inspect
        from nodes.market_monitor.position_checker import PositionChecker
        src = inspect.getsource(PositionChecker.__init__)
        assert "_restore_alignment_stats" in src


class TestAlignmentStatsAPI:
    """alignment-stats API端点"""

    def test_alignment_stats_endpoint_exists(self):
        """alignment-stats端点定义"""
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nodes', 'web', 'api', 'scanner_system.py')
        with open(filepath) as f:
            content = f.read()
        assert 'alignment-stats' in content or 'alignment_stats' in content


class TestVersionV2970:
    """版本常量v2.9.70"""

    def test_design_doc_version(self):
        """_DESIGN_DOC_VERSION = v2.9.81"""
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nodes', 'web', 'api', 'scanner_system.py')
        with open(filepath) as f:
            content = f.read()
        assert '_DESIGN_DOC_VERSION = "v2.9.81"' in content


class TestFrontendTSFixes:
    """前端TypeScript修复验证"""

    def test_use_core_methods_imports_fixed(self):
        """useCoreMethods.ts: 移除未使用的ref/reactive/nextTick/factorLabel/pipelineLabels"""
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'frontend', 'src', 'views', 'monitor', 'composables', 'useCoreMethods.ts')
        if os.path.exists(filepath):
            with open(filepath) as f:
                content = f.read()
            # 不应包含 ref, reactive, nextTick 的未使用导入
            import_line = [l for l in content.split('\n') if 'from \'vue\'' in l][0]
            assert 'ref,' not in import_line or 'refs' in content
            # factorLabel和pipelineLabels不应在导入中
            assert 'factorLabel' not in content.split('\n')[0:20]
            assert 'pipelineLabels' not in content.split('\n')[0:20]

    def test_use_auto_trade_monitor_imports_fixed(self):
        """useAutoTradeMonitor.ts: 移除未使用的ElMessage"""
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'frontend', 'src', 'views', 'monitor', 'composables', 'useAutoTradeMonitor.ts')
        if os.path.exists(filepath):
            with open(filepath) as f:
                content = f.read()
            # ElMessage不应在导入中
            import_lines = [l for l in content.split('\n') if l.strip().startswith('import')]
            el_msg_imports = [l for l in import_lines if 'ElMessage' in l]
            assert len(el_msg_imports) == 0

    def test_strategy_perf_board_type_fix(self):
        """StrategyPerfBoard.vue: api.get返回值类型注解"""
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'frontend', 'src', 'views', 'monitor', 'StrategyPerfBoard.vue')
        if os.path.exists(filepath):
            with open(filepath) as f:
                content = f.read()
            assert 'const r: any = await api.get' in content

    def test_system_health_type_fix(self):
        """SystemHealth.vue: api.get返回值类型注解"""
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'frontend', 'src', 'views', 'monitor', 'SystemHealth.vue')
        if os.path.exists(filepath):
            with open(filepath) as f:
                content = f.read()
            assert 'const r: any = await api.get' in content

    def test_scanner_monitor_weekly_report_in_return(self):
        """useScannerMonitor.ts: weeklyReportData在返回对象中"""
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'frontend', 'src', 'views', 'monitor', 'useScannerMonitor.ts')
        if os.path.exists(filepath):
            with open(filepath) as f:
                content = f.read()
            # weeklyReportData应在return对象中
            return_section = content[content.rfind('return {'):]
            assert 'weeklyReportData' in return_section


class TestNoBacktestRegression:
    """回测零影响验证"""

    def test_sell_signal_checker_not_modified(self):
        """sell_signal_checker.py未修改"""
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nodes', 'backtest_engine', 'factor_selection', 'sell_signal_checker.py')
        if os.path.exists(filepath):
            with open(filepath) as f:
                content = f.read()
            # 不包含v2.9.70相关内容
            assert 'CompareAlignmentStats' not in content
            assert '_persist_alignment_stats' not in content

    def test_strategy_defaults_not_modified(self):
        """strategy_defaults.py未修改"""
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nodes', 'backtest_engine', 'factor_selection', 'strategy_defaults.py')
        if os.path.exists(filepath):
            with open(filepath) as f:
                content = f.read()
            assert 'v2.9.70' not in content

    def test_portfolio_backtester_not_modified(self):
        """PortfolioBacktester未修改"""
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nodes', 'backtest_engine', 'portfolio_backtester.py')
        if os.path.exists(filepath):
            with open(filepath) as f:
                content = f.read()
            assert 'CompareAlignmentStats' not in content
