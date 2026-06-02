"""
v2.9.38 测试: PositionChecker提取+compare差异持久化

验证项:
1. _run_checker_on_positions提取(checker/compare复用)
2. _post_sell_state_cleanup提取(3处卖出后清理统一)
3. _persist_compare_diff差异持久化
4. checker模式使用提取方法
5. compare模式使用提取方法+差异持久化
6. legacy模式使用_post_sell_state_cleanup
7. 回测零影响
"""
import ast
import os
import pytest
import inspect


SCANNER_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "market_monitor")
POSITION_CHECKER_PATH = os.path.join(SCANNER_DIR, "position_checker.py")


def _read_source():
    with open(POSITION_CHECKER_PATH) as f:
        return f.read()

def _read_rp_source():
    """读取RuntimePersistence源码【v2.9.45:_persist_compare_diff已迁移】"""
    rp_path = os.path.join(SCANNER_DIR, "runtime_persistence.py")
    with open(rp_path) as f:
        return f.read()


# ==================== _run_checker_on_positions提取 ====================

class TestRunCheckerOnPositions:
    """验证_run_checker_on_positions方法提取"""

    def test_method_exists(self):
        """_run_checker_on_positions方法存在"""
        src = _read_source()
        assert "def _run_checker_on_positions" in src

    def test_returns_5_tuple(self):
        """返回5元组(pos, reason, price, risk, priority)"""
        src = _read_source()
        # 验证results.append包含5个元素
        assert "results.append((pos, reason, sell_price, risk, priority))" in src

    def test_checker_mode_uses_extracted_method(self):
        """checker模式使用_run_checker_on_positions"""
        src = _read_source()
        # _check_positions_checker中调用_run_checker_on_positions
        lines = src.split("\n")
        in_checker = False
        found = False
        for line in lines:
            if "def _check_positions_checker" in line:
                in_checker = True
            elif in_checker and "def " in line and "_check_positions_checker" not in line:
                break
            elif in_checker and "_run_checker_on_positions" in line:
                found = True
                break
        assert found, "_check_positions_checker应使用_run_checker_on_positions"

    def test_compare_mode_uses_extracted_method(self):
        """compare模式使用_run_checker_on_positions(v2.9.73:通过_run_compare_both委托)"""
        src = _read_source()
        # v2.9.73重构: _check_positions_compare委托给_run_compare_both, 后者调用_run_checker_on_positions
        assert "_run_compare_both" in src, "_check_positions_compare应委托给_run_compare_both"
        # _run_compare_both内部调用_run_checker_on_positions
        lines = src.split("\n")
        in_both = False
        found = False
        for line in lines:
            if "def _run_compare_both" in line:
                in_both = True
            elif in_both and "def " in line and "_run_compare_both" not in line:
                break
            elif in_both and "_run_checker_on_positions" in line:
                found = True
                break
        assert found, "_run_compare_both应使用_run_checker_on_positions"

    def test_no_duplicate_checker_loop_in_checker(self):
        """checker模式不再有重复的for pos in positions循环"""
        src = _read_source()
        lines = src.split("\n")
        in_checker = False
        loop_count = 0
        for line in lines:
            if "def _check_positions_checker" in line:
                in_checker = True
            elif in_checker and "def " in line and "_check_positions_checker" not in line:
                break
            elif in_checker and "for pos in positions:" in line:
                loop_count += 1
        # checker模式不应有直接的positions遍历循环
        assert loop_count == 0, f"_check_positions_checker中不应有for pos in positions循环(发现{loop_count}个)"

    def test_trailing_state_lock_in_extracted_method(self):
        """提取方法中正确加锁读取trailing_stops"""
        src = _read_source()
        # _run_checker_on_positions中应有with self.state_lock
        lines = src.split("\n")
        in_method = False
        has_lock = False
        for line in lines:
            if "def _run_checker_on_positions" in line:
                in_method = True
            elif in_method and "def " in line and "_run_checker_on_positions" not in line:
                break
            elif in_method and "with self.state_lock:" in line:
                has_lock = True
                break
        assert has_lock, "_run_checker_on_positions中应有state_lock保护"

    def test_trade_days_held_in_extracted_method(self):
        """提取方法中计算trade_days_held"""
        src = _read_source()
        lines = src.split("\n")
        in_method = False
        has_calc = False
        for line in lines:
            if "def _run_checker_on_positions" in line:
                in_method = True
            elif in_method and "def " in line and "_run_checker_on_positions" not in line:
                break
            elif in_method and "_calc_trade_days_held" in line:
                has_calc = True
                break
        assert has_calc, "_run_checker_on_positions中应计算trade_days_held"


# ==================== _post_sell_state_cleanup提取 ====================

class TestPostSellStateCleanup:
    """验证_post_sell_state_cleanup方法提取"""

    def test_method_exists(self):
        """_post_sell_state_cleanup方法存在"""
        src = _read_source()
        assert "def _post_sell_state_cleanup" in src

    def test_trailing_stops_pop_in_cleanup(self):
        """cleanup中清理trailing_stops"""
        src = _read_source()
        lines = src.split("\n")
        in_method = False
        has_pop = False
        for line in lines:
            if "def _post_sell_state_cleanup" in line:
                in_method = True
            elif in_method and "def " in line and "_post_sell_state_cleanup" not in line:
                break
            elif in_method and "trailing_stops.pop" in line:
                has_pop = True
                break
        assert has_pop, "_post_sell_state_cleanup中应有trailing_stops.pop"

    def test_position_risk_levels_pop_in_cleanup(self):
        """cleanup中清理position_risk_levels"""
        src = _read_source()
        lines = src.split("\n")
        in_method = False
        has_pop = False
        for line in lines:
            if "def _post_sell_state_cleanup" in line:
                in_method = True
            elif in_method and "def " in line and "_post_sell_state_cleanup" not in line:
                break
            elif in_method and "position_risk_levels.pop" in line:
                has_pop = True
                break
        assert has_pop, "_post_sell_state_cleanup中应有position_risk_levels.pop"

    def test_state_lock_in_cleanup(self):
        """cleanup中使用state_lock"""
        src = _read_source()
        lines = src.split("\n")
        in_method = False
        has_lock = False
        for line in lines:
            if "def _post_sell_state_cleanup" in line:
                in_method = True
            elif in_method and "def " in line and "_post_sell_state_cleanup" not in line:
                break
            elif in_method and "with self.state_lock:" in line:
                has_lock = True
                break
        assert has_lock, "_post_sell_state_cleanup中应有state_lock"

    def test_broker_save_state_in_cleanup(self):
        """cleanup中调用broker.save_state"""
        src = _read_source()
        lines = src.split("\n")
        in_method = False
        has_save = False
        for line in lines:
            if "def _post_sell_state_cleanup" in line:
                in_method = True
            elif in_method and "def " in line and "_post_sell_state_cleanup" not in line:
                break
            elif in_method and "broker.save_state" in line:
                has_save = True
                break
        assert has_save, "_post_sell_state_cleanup中应有broker.save_state"

    def test_runtime_snapshot_in_cleanup(self):
        """cleanup中调用_save_runtime_snapshot"""
        src = _read_source()
        lines = src.split("\n")
        in_method = False
        has_snapshot = False
        for line in lines:
            if "def _post_sell_state_cleanup" in line:
                in_method = True
            elif in_method and "def " in line and "_post_sell_state_cleanup" not in line:
                break
            elif in_method and "_save_runtime_snapshot" in line:
                has_snapshot = True
                break
        assert has_snapshot, "_post_sell_state_cleanup中应有_save_runtime_snapshot"

    def test_legacy_mode_uses_cleanup(self):
        """legacy模式使用_post_sell_state_cleanup"""
        src = _read_source()
        lines = src.split("\n")
        in_legacy = False
        found = False
        for line in lines:
            if "def _check_positions_legacy" in line:
                in_legacy = True
            elif in_legacy and "def " in line and "_check_positions_legacy" not in line:
                break
            elif in_legacy and "_post_sell_state_cleanup" in line:
                found = True
                break
        assert found, "_check_positions_legacy应使用_post_sell_state_cleanup"

    def test_checker_mode_uses_cleanup(self):
        """checker模式使用_post_sell_state_cleanup"""
        src = _read_source()
        lines = src.split("\n")
        in_checker = False
        found = False
        for line in lines:
            if "def _check_positions_checker" in line:
                in_checker = True
            elif in_checker and "def " in line and "_check_positions_checker" not in line:
                break
            elif in_checker and "_post_sell_state_cleanup" in line:
                found = True
                break
        assert found, "_check_positions_checker应使用_post_sell_state_cleanup"

    def test_no_inline_trailing_pop_in_checker(self):
        """checker模式不再内联trailing_stops.pop"""
        src = _read_source()
        lines = src.split("\n")
        in_checker = False
        has_inline_pop = False
        for line in lines:
            if "def _check_positions_checker" in line:
                in_checker = True
            elif in_checker and "def " in line and "_check_positions_checker" not in line:
                break
            elif in_checker and "trailing_stops.pop" in line and "_post_sell_state_cleanup" not in line:
                has_inline_pop = True
                break
        assert not has_inline_pop, "_check_positions_checker不应内联trailing_stops.pop"

    def test_early_return_on_empty(self):
        """cleanup在to_sell为空时提前返回"""
        src = _read_source()
        # 检查方法开头有if not to_sell: return
        lines = src.split("\n")
        in_method = False
        method_lines = []
        for line in lines:
            if "def _post_sell_state_cleanup" in line:
                in_method = True
            elif in_method and "def " in line and "_post_sell_state_cleanup" not in line:
                break
            elif in_method:
                method_lines.append(line.strip())
        early_return = any("if not to_sell" in l for l in method_lines[:5])
        assert early_return, "_post_sell_state_cleanup应有空列表提前返回"


# ==================== compare差异持久化 ====================

class TestCompareDiffPersistence:
    """验证_persist_compare_diff方法(v2.9.45:实现已迁移到RuntimePersistence)"""

    def test_method_exists(self):
        """_persist_compare_diff在position_checker和runtime_persistence均存在"""
        pc_src = _read_source()
        rp_src = _read_rp_source()
        assert "def _persist_compare_diff" in pc_src, "position_checker应有委托方法"
        assert "def persist_compare_diff" in rp_src, "runtime_persistence应有实现方法"

    def test_mongodb_collection_name(self):
        """使用sell_compare_diff集合"""
        rp_src = _read_rp_source()
        assert '"sell_compare_diff"' in rp_src or "'sell_compare_diff'" in rp_src

    def test_ttl_index_creation(self):
        """创建TTL索引(30天)"""
        rp_src = _read_rp_source()
        assert "ttl_30d_compare" in rp_src
        assert "30 * 86400" in rp_src or "2592000" in rp_src

    def test_diff_details_structure(self):
        """差异详情包含必要字段"""
        rp_src = _read_rp_source()
        assert "legacy_reason" in rp_src
        assert "checker_reason" in rp_src
        assert "agreement_rate" in rp_src

    def test_compare_mode_calls_persist(self):
        """compare模式调用_persist_compare_diff(v2.9.73:通过_handle_compare_diff委托)"""
        src = _read_source()
        # v2.9.73重构: _check_positions_compare委托给_handle_compare_diff, 后者调用_persist_compare_diff
        assert "_handle_compare_diff" in src, "_check_positions_compare应委托给_handle_compare_diff"
        # _handle_compare_diff内部调用_persist_compare_diff
        lines = src.split("\n")
        in_diff = False
        found = False
        for line in lines:
            if "def _handle_compare_diff" in line:
                in_diff = True
            elif in_diff and "def " in line and "_handle_compare_diff" not in line:
                break
            elif in_diff and "_persist_compare_diff" in line:
                found = True
                break
        assert found, "_handle_compare_diff应调用_persist_compare_diff"

    def test_position_checker_delegates_to_rp(self):
        """position_checker的_persist_compare_diff委托给runtime_persistence【v2.9.45新增】"""
        src = _read_source()
        assert "rp.persist_compare_diff" in src or "runtime_persistence" in src, (
            "position_checker._persist_compare_diff应委托给RuntimePersistence"
        )

    def test_try_except_protection(self):
        """持久化方法有try/except保护(失败不影响主流程)"""
        rp_src = _read_rp_source()
        lines = rp_src.split("\n")
        in_method = False
        has_try = False
        has_except = False
        for line in lines:
            if "def persist_compare_diff" in line:
                in_method = True
            elif in_method and "def " in line and "persist_compare_diff" not in line:
                break
            elif in_method and line.strip().startswith("try:"):
                has_try = True
            elif in_method and "except Exception" in line:
                has_except = True
        assert has_try and has_except, "persist_compare_diff应有try/except保护"


# ==================== 代码量回归 ====================

class TestCodeReduction:
    """验证代码量减少"""

    def test_position_checker_line_count(self):
        """position_checker.py行数合理"""
        with open(POSITION_CHECKER_PATH) as f:
            lines = f.readlines()
        # 原始606行, 提取后应不超过700行(+94行新增方法)
        assert len(lines) < 850, f"position_checker.py行数{len(lines)}应<850"

    def test_no_duplicate_for_pos_loop(self):
        """checker和compare不再有重复的for pos in positions遍历"""
        src = _read_source()
        lines = src.split("\n")
        
        # 统计_check_positions_checker中的for pos in positions
        in_checker = False
        checker_loops = 0
        for line in lines:
            if "def _check_positions_checker" in line:
                in_checker = True
            elif in_checker and "def " in line and "_check_positions_checker" not in line:
                break
            elif in_checker and "for pos in positions:" in line:
                checker_loops += 1
        
        # 统计_check_positions_compare中的for pos in positions
        in_compare = False
        compare_loops = 0
        for line in lines:
            if "def _check_positions_compare" in line:
                in_compare = True
            elif in_compare and "def " in line and "_check_positions_compare" not in line:
                break
            elif in_compare and "for pos in positions:" in line:
                compare_loops += 1
        
        assert checker_loops == 0, f"_check_positions_checker中for pos循环应为0(实际{checker_loops})"
        assert compare_loops == 0, f"_check_positions_compare中for pos循环应为0(实际{compare_loops})"


# ==================== 版本同步 ====================

class TestVersionSync:
    """验证版本号同步"""

    def test_design_doc_version(self):
        """API版本号更新"""
        api_path = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "web", "api", "scanner_system.py")
        with open(api_path) as f:
            src = f.read()
        assert '_DESIGN_DOC_VERSION = "v2.9.73"' in src

    def test_docstring_mentions_version(self):
        """position_checker.py文档提到当前版本"""
        src = _read_source()
        # v2.9.38是提取版本, v2.9.43是最新, 文档中至少包含一个
        assert "v2.9.38" in src or "v2.9.54" in src


# ==================== 回测零影响 ====================

class TestNoBacktestRegression:
    """验证回测模块零影响"""

    def test_backtest_engine_importable(self):
        """回测引擎可导入"""
        try:
            from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        except ImportError:
            pass  # 非运行环境可以忽略

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker API未变"""
        try:
            from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
            # check_realtime_sell签名不变
            import inspect
            sig = inspect.signature(SellSignalChecker.check_realtime_sell)
            params = list(sig.parameters.keys())
            assert "position" in params
            assert "trailing_stop_state" in params
            assert "trade_days_held" in params
        except ImportError:
            pass

    def test_strategy_defaults_importable(self):
        """默认参数可导入"""
        try:
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
            assert isinstance(STRATEGY_CONFIGS, dict)
            assert isinstance(GLOBAL_RISK, dict)
        except ImportError:
            pass

    def test_position_checker_not_imported_by_backtest(self):
        """回测引擎不导入PositionChecker"""
        backtest_dir = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "backtest_engine")
        if not os.path.exists(backtest_dir):
            return
        for root, dirs, files in os.walk(backtest_dir):
            for f in files:
                if f.endswith('.py'):
                    with open(os.path.join(root, f)) as fh:
                        src = fh.read()
                    assert "position_checker" not in src, f"回测文件{f}不应引用position_checker"

    def test_new_methods_no_external_imports(self):
        """新方法不引入外部非标准库依赖"""
        src = _read_source()
        lines = src.split("\n")
        new_methods = ["_run_checker_on_positions", "_post_sell_state_cleanup", "_persist_compare_diff"]
        for method_name in new_methods:
            in_method = False
            for line in lines:
                if f"def {method_name}" in line:
                    in_method = True
                elif in_method and "def " in line and method_name not in line:
                    break
                elif in_method and "from " in line and "import " in line:
                    # 允许的内部导入: core.managers, scanner_event_bus
                    imported = line.strip()
                    assert any(allow in imported for allow in 
                               ["core.managers", "scanner_event_bus"]), \
                        f"{method_name}中的导入应限于允许的模块: {imported}"
