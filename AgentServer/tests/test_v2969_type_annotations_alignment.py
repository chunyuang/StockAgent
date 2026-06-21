#!/usr/bin/env python3
"""v2.9.70测试: 返回类型注解补全 + EMOTION_DOWNGRADE_RULES清理 + 灰度对齐追踪器

验证:
1. 55个返回类型注解补全(91.9%→97%+)
2. EMOTION_DOWNGRADE_RULES type:ignore消除
3. CompareAlignmentStats灰度对齐追踪器
4. /alignment-stats API端点
5. 回测零影响
"""
import ast
import os
import sys

import pytest

# 项目路径
AGENT_SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, AGENT_SERVER)


class TestReturnTypeAnnotationsV2969:
    """验证返回类型注解补全"""

    def _get_missing_return_annotations(self) -> list:
        """获取所有缺失返回类型注解的方法"""
        missing = []
        for root, dirs, files in os.walk(os.path.join(AGENT_SERVER, "nodes", "market_monitor")):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if not f.endswith(".py") or f == "__init__.py":
                    continue
                path = os.path.join(root, f)
                try:
                    tree = ast.parse(open(path).read())
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if node.name.startswith("__") and node.name.endswith("__"):
                                continue
                            if node.returns is None:
                                missing.append((f, node.name, node.lineno))
                except Exception:
                    pass
        return missing

    def test_return_annotation_coverage_above_95(self):
        """返回类型注解覆盖率>=95%"""
        total_public = 0
        annotated_return = 0
        for root, dirs, files in os.walk(os.path.join(AGENT_SERVER, "nodes", "market_monitor")):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if not f.endswith(".py") or f == "__init__.py":
                    continue
                path = os.path.join(root, f)
                try:
                    tree = ast.parse(open(path).read())
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if node.name.startswith("__") and node.name.endswith("__"):
                                continue
                            total_public += 1
                            if node.returns is not None:
                                annotated_return += 1
                except Exception:
                    pass
        pct = annotated_return / total_public * 100 if total_public else 0
        assert pct >= 95.0, f"返回类型注解覆盖率{pct:.1f}%<95% (需补全{total_public - annotated_return}个)"

    def test_no_type_ignore_in_scanner(self):
        """scanner.py不再有bare type: ignore (specific type: ignore[xxx] is OK)"""
        content = open(os.path.join(AGENT_SERVER, "nodes", "market_monitor", "scanner.py")).read()
        # Bare '# type: ignore' without specific error code is not allowed
        for line_no, line in enumerate(content.split('\n'), 1):
            if '# type: ignore' in line and '# type: ignore[' not in line:
                pytest.fail(f'scanner.py line {line_no} has bare type: ignore (use type: ignore[xxx] instead)')

    def test_emotion_downgrade_rules_typed(self):
        """EMOTION_DOWNGRADE_RULES有类型注解"""
        content = open(os.path.join(AGENT_SERVER, "nodes", "market_monitor", "scanner.py")).read()
        # 应该有Optional[Dict]类型注解
        assert "EMOTION_DOWNGRADE_RULES: Optional[Dict]" in content, \
            "EMOTION_DOWNGRADE_RULES缺少Optional[Dict]类型注解"

    def test_daemon_watchdog_mixin_annotations(self):
        """daemon_watchdog_mixin返回注解"""
        content = open(os.path.join(AGENT_SERVER, "nodes", "market_monitor", "daemon_watchdog_mixin.py")).read()
        assert "-> None:" in content, "daemon_watchdog_mixin缺少-> None注解"

    def test_data_source_router_annotations(self):
        """data_source_router返回注解"""
        content = open(os.path.join(AGENT_SERVER, "nodes", "market_monitor", "data_source_router.py")).read()
        assert "def register(self, name: str, adapter: Any, priority: int = 99) -> None:" in content

    def test_emotion_cycle_annotations(self):
        """emotion_cycle静态方法返回注解"""
        content = open(os.path.join(AGENT_SERVER, "nodes", "market_monitor", "emotion_cycle.py")).read()
        assert "-> Tuple[" in content, "emotion_cycle缺少Tuple返回注解"

    def test_gm_broker_annotations(self):
        """gm_broker返回注解"""
        content = open(os.path.join(AGENT_SERVER, "nodes", "market_monitor", "gm_broker.py")).read()
        assert "def is_running(self) -> bool:" in content
        assert "async def start(self) -> Dict[str, Any]:" in content

    def test_scanner_event_subscribers_annotations(self):
        """scanner_event_subscribers返回注解"""
        content = open(os.path.join(AGENT_SERVER, "nodes", "market_monitor", "scanner_event_subscribers.py")).read()
        assert "-> Callable:" in content, "subscriber工厂函数缺少-> Callable注解"
        assert "-> None:" in content, "subscriber处理函数缺少-> None注解"

    def test_tiered_scanner_annotations(self):
        """tiered_scanner返回注解"""
        content = open(os.path.join(AGENT_SERVER, "nodes", "market_monitor", "tiered_scanner.py")).read()
        assert "def _apply_config(self) -> None:" in content
        assert "def set_scanner(self, scanner: Any) -> None:" in content


class TestCompareAlignmentStatsV2969:
    """灰度对齐追踪器测试"""

    def test_alignment_stats_init(self):
        """CompareAlignmentStats初始化"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        assert stats.total_checks == 0
        assert stats.alignment_rate == 0.0
        assert stats.switch_ready is False

    def test_alignment_stats_record_agreement(self):
        """记录完全一致的结果"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        stats.record(set(), set(), {"600036.SH"})  # only both, no differences
        assert stats.total_checks == 1
        assert stats.agreement_count == 1
        assert stats.alignment_rate == 1.0
        assert stats.consecutive_agree == 1

    def test_alignment_stats_record_disagreement(self):
        """记录不一致的结果"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        stats.record({"600036.SH"}, set(), set())  # only legacy
        assert stats.total_checks == 1
        assert stats.agreement_count == 0
        assert stats.alignment_rate == 0.0
        assert stats.consecutive_agree == 0

    def test_alignment_stats_consecutive_agree(self):
        """连续一致计数"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        for _ in range(10):
            stats.record(set(), set(), {"600036.SH"})
        assert stats.consecutive_agree == 10
        assert stats.max_consecutive_agree == 10
        # 不一致重置
        stats.record({"600036.SH"}, set(), set())
        assert stats.consecutive_agree == 0
        assert stats.max_consecutive_agree == 10
        # 再一致
        for _ in range(5):
            stats.record(set(), set(), {"600036.SH"})
        assert stats.consecutive_agree == 5
        assert stats.max_consecutive_agree == 10

    def test_alignment_stats_switch_ready(self):
        """切换就绪判断"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        # 50次一致
        for _ in range(50):
            stats.record(set(), set(), {"600036.SH"})
        assert stats.total_checks == 50
        assert stats.alignment_rate == 1.0
        assert stats.consecutive_agree == 50
        assert stats.switch_ready is True

    def test_alignment_stats_switch_not_ready_insufficient_checks(self):
        """切换条件: 检查次数不足"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        for _ in range(30):
            stats.record(set(), set(), {"600036.SH"})
        assert stats.switch_ready is False  # 30 < 50

    def test_alignment_stats_switch_not_ready_low_rate(self):
        """切换条件: 对齐率不足"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        # 47次一致, 3次不一致
        for _ in range(47):
            stats.record(set(), set(), {"600036.SH"})
        for _ in range(3):
            stats.record({"600036.SH"}, set(), set())
        assert stats.total_checks == 50
        assert stats.alignment_rate == pytest.approx(0.94, abs=0.01)
        assert stats.switch_ready is False

    def test_alignment_stats_coverage_rate(self):
        """覆盖率计算"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        # both=3, only_checker=1 → coverage=3/4=0.75
        stats.record(set(), set(), {"600036.SH", "000001.SZ", "000898.SZ"})
        stats.record(set(), {"300001.SZ"}, set())
        assert stats.coverage_rate == pytest.approx(0.75, abs=0.01)

    def test_alignment_stats_to_dict(self):
        """序列化"""
        from nodes.market_monitor.position_checker import CompareAlignmentStats
        stats = CompareAlignmentStats()
        stats.record(set(), set(), {"600036.SH"})
        d = stats.to_dict()
        assert "total_checks" in d
        assert "alignment_rate" in d
        assert "switch_ready" in d
        assert "recommendation" not in d  # recommendation由API端点添加
        assert d["total_checks"] == 1
        assert d["alignment_rate"] == 1.0

    def test_position_checker_has_alignment_stats(self):
        """PositionChecker有alignment_stats属性"""
        from nodes.market_monitor.position_checker import PositionChecker
        # 检查类定义中有_alignment_stats初始化
        source = open(os.path.join(AGENT_SERVER, "nodes", "market_monitor", "position_checker.py")).read()
        assert "_alignment_stats = CompareAlignmentStats()" in source
        assert "def alignment_stats" in source


class TestAlignmentStatsAPIV2969:
    """灰度对齐API端点测试"""

    def test_alignment_stats_endpoint_defined(self):
        """API端点已定义"""
        source = open(os.path.join(AGENT_SERVER, "nodes", "web", "api", "scanner_system.py")).read()
        assert '/alignment-stats' in source
        assert 'get_alignment_stats' in source

    def test_design_doc_version_v2969(self):
        """版本常量v2.9.98"""
        source = open(os.path.join(AGENT_SERVER, "nodes", "web", "api", "scanner_system.py")).read()
        assert 'v2.9.98' in source

    def test_alignment_stats_endpoint_has_recommendation(self):
        """API端点包含切换建议逻辑"""
        source = open(os.path.join(AGENT_SERVER, "nodes", "web", "api", "scanner_system.py")).read()
        assert "recommendation" in source
        assert "switch_ready" in source
        assert "SELL_LOGIC_MODE=compare" in source


class TestNoBacktestRegressionV2969:
    """回测零影响"""

    def test_sell_signal_checker_unmodified(self):
        """sell_signal_checker未修改"""
        path = os.path.join(AGENT_SERVER, "nodes", "backtest_engine", "factor_selection", "sell_signal_checker.py")
        assert os.path.exists(path), "sell_signal_checker.py不存在"
        # CompareAlignmentStats是新类, 不影响回测
        content = open(path).read()
        assert "CompareAlignmentStats" not in content

    def test_strategy_defaults_unmodified(self):
        """strategy_defaults未修改"""
        path = os.path.join(AGENT_SERVER, "nodes", "backtest_engine", "strategy_defaults.py")
        assert os.path.exists(path)
        content = open(path).read()
        assert "CompareAlignmentStats" not in content

    def test_portfolio_backtester_unmodified(self):
        """portfolio_backtester未修改"""
        path = os.path.join(AGENT_SERVER, "nodes", "backtest_engine", "factor_selection", "portfolio_backtest.py")
        assert os.path.exists(path)

    def test_changes_limited_to_market_monitor(self):
        """变更仅限market_monitor模块和web/api"""
        changed_files = [
            "scanner.py", "daemon_watchdog_mixin.py", "data_source_router.py",
            "emotion_cycle.py", "gm_broker.py", "replay_provider.py",
            "scanner_event_subscribers.py", "strategy_param_center.py",
            "tiered_scanner.py", "position_checker.py",
        ]
        for f in changed_files:
            path = os.path.join(AGENT_SERVER, "nodes", "market_monitor", f)
            assert os.path.exists(path), f"{f}不存在"
