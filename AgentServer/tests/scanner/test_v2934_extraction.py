#!/usr/bin/env python3
"""
v2.9.34 — 情绪得分+收盘同步提取 测试

验证:
- EmotionCycleManager.update_sentiment_score提取
- RuntimePersistence.sync_close_data_to_mongo提取
- DELEGATE_MAP注册
- scanner.py行数回归
- 回测零影响
"""

import ast
import os
import pytest

# 项目根目录
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCANNER_PATH = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner.py")
_EMOTION_PATH = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "emotion_cycle.py")
_RP_PATH = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "runtime_persistence.py")
_ROUTER_PATH = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner_delegate_router.py")


def _read_file(path):
    with open(path) as f:
        return f.read()


# ==================== 1. EmotionCycleManager.update_sentiment_score ====================

class TestUpdateSentimentScoreExtraction:
    """验证_update_sentiment_score提取到EmotionCycleManager"""

    def test_emotion_cycle_has_method(self):
        """EmotionCycleManager有update_sentiment_score静态方法"""
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        assert hasattr(EmotionCycleManager, 'update_sentiment_score')

    def test_method_is_static(self):
        """update_sentiment_score是@staticmethod"""
        source = _read_file(_EMOTION_PATH)
        # 找到方法定义
        idx = source.find("async def update_sentiment_score")
        assert idx > 0, "update_sentiment_score方法未找到"
        # 检查前面有@staticmethod
        before = source[max(0, idx - 200):idx]
        assert "@staticmethod" in before, "缺少@staticmethod装饰器"

    def test_method_signature_has_scanner_and_trade_date(self):
        """方法签名: (scanner, trade_date: str)"""
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        import inspect
        sig = inspect.signature(EmotionCycleManager.update_sentiment_score)
        params = list(sig.parameters.keys())
        assert "scanner" in params, f"缺少scanner参数: {params}"
        assert "trade_date" in params, f"缺少trade_date参数: {params}"

    def test_method_writes_sentiment_scores(self):
        """方法写入sentiment_scores集合"""
        source = _read_file(_EMOTION_PATH)
        idx = source.find("async def update_sentiment_score")
        end = source.find("\n\n\n# 全局单例", idx)
        method_code = source[idx:end]
        assert "sentiment_scores" in method_code, "未写入sentiment_scores集合"
        assert "upsert=True" in method_code, "缺少upsert=True"

    def test_method_has_fallback_data_sources(self):
        """方法有3级数据源fallback"""
        source = _read_file(_EMOTION_PATH)
        idx = source.find("async def update_sentiment_score")
        end = source.find("\n\n\n# 全局单例", idx)
        method_code = source[idx:end]
        assert "scanner_realtime" in method_code, "缺少scanner_realtime数据源"
        assert "limit_list" in method_code, "缺少limit_list数据源"
        assert "daily_basic" in method_code, "缺少daily_basic数据源"


# ==================== 2. RuntimePersistence.sync_close_data_to_mongo ====================

class TestSyncCloseDataExtraction:
    """验证_sync_close_data_to_mongo提取到RuntimePersistence"""

    def test_runtime_persistence_has_method(self):
        """RuntimePersistence有sync_close_data_to_mongo方法"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, 'sync_close_data_to_mongo')

    def test_method_is_async(self):
        """sync_close_data_to_mongo是async方法"""
        source = _read_file(_RP_PATH)
        assert "async def sync_close_data_to_mongo" in source, "缺少async def sync_close_data_to_mongo"

    def test_method_has_updateone_import(self):
        """方法内部导入UpdateOne"""
        source = _read_file(_RP_PATH)
        idx = source.find("async def sync_close_data_to_mongo")
        assert idx > 0, "方法未找到"
        end = source.find("\n    async def ", idx + 10)
        if end == -1:
            end = len(source)
        method_code = source[idx:end]
        assert "from pymongo.operations import UpdateOne" in method_code, "缺少UpdateOne导入"

    def test_method_syncs_limit_list(self):
        """方法同步limit_list集合"""
        source = _read_file(_RP_PATH)
        idx = source.find("async def sync_close_data_to_mongo")
        end = source.find("\n    async def ", idx + 10)
        if end == -1:
            end = len(source)
        method_code = source[idx:end]
        assert "limit_list" in method_code, "未同步limit_list"

    def test_method_syncs_daily_basic(self):
        """方法同步daily_basic集合"""
        source = _read_file(_RP_PATH)
        idx = source.find("async def sync_close_data_to_mongo")
        end = source.find("\n    async def ", idx + 10)
        if end == -1:
            end = len(source)
        method_code = source[idx:end]
        assert "daily_basic" in method_code, "未同步daily_basic"

    def test_method_has_bulk_write(self):
        """方法使用bulk_write批量写入"""
        source = _read_file(_RP_PATH)
        idx = source.find("async def sync_close_data_to_mongo")
        end = source.find("\n    async def ", idx + 10)
        if end == -1:
            end = len(source)
        method_code = source[idx:end]
        assert "bulk_write" in method_code, "未使用bulk_write"


# ==================== 3. DELEGATE_MAP注册 ====================

class TestDelegateMapRegistration:
    """验证DELEGATE_MAP和路由器注册"""

    def test_update_sentiment_score_in_delegate_map(self):
        """_update_sentiment_score在DELEGATE_MAP中，路由到_emotion_cycle_class"""
        source = _read_file(_SCANNER_PATH)
        assert '"_update_sentiment_score"' in source, "_update_sentiment_score不在DELEGATE_MAP中"
        # 验证路由目标: 找到条目后检查值
        idx = source.find('"_update_sentiment_score"')
        after = source[idx:idx + 100]
        assert '"_emotion_cycle_class"' in after, f"路由目标不是_emotion_cycle_class: {after[:80]}"

    def test_sync_close_data_in_delegate_map(self):
        """_sync_close_data_to_mongo在DELEGATE_MAP中，路由到_runtime_persistence"""
        source = _read_file(_SCANNER_PATH)
        assert '"_sync_close_data_to_mongo"' in source, "_sync_close_data_to_mongo不在DELEGATE_MAP中"
        idx = source.find('"_sync_close_data_to_mongo"')
        after = source[idx:idx + 100]
        assert '"_runtime_persistence"' in after, f"路由目标不是_runtime_persistence: {after[:80]}"

    def test_update_sentiment_in_async_delegates(self):
        """_update_sentiment_score在_ASYNC_DELEGATE_METHODS中"""
        source = _read_file(_ROUTER_PATH)
        assert '"_update_sentiment_score"' in source, "_update_sentiment_score不在_ASYNC_DELEGATE_METHODS中"

    def test_update_sentiment_in_emotion_bindings(self):
        """update_sentiment_score在_EMOTION_BINDINGS中"""
        source = _read_file(_ROUTER_PATH)
        assert '"update_sentiment_score"' in source, "update_sentiment_score不在_EMOTION_BINDINGS中"

    def test_no_inline_implementation_in_scanner(self):
        """scanner.py不再有_update_sentiment_score的内联实现"""
        source = _read_file(_SCANNER_PATH)
        # 不应有sentiment_scores集合的upsert操作
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if 'sentiment_scores' in line and 'upsert' in line:
                pytest.fail(f"第{i+1}行: scanner.py仍有sentiment_scores内联操作: {line.strip()}")

    def test_no_inline_sync_close_in_scanner(self):
        """scanner.py不再有_sync_close_data_to_mongo的内联实现"""
        source = _read_file(_SCANNER_PATH)
        # 不应有limit_list的bulk_write操作
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if 'limit_list' in line and 'bulk_write' in line:
                pytest.fail(f"第{i+1}行: scanner.py仍有limit_list内联操作: {line.strip()}")


# ==================== 4. 行数回归 ====================

class TestScannerLineCountV2934:
    """验证scanner.py行数在合理范围"""

    def test_scanner_line_count(self):
        """scanner.py行数应<1650(v2.9.34:2个方法提取)"""
        with open(_SCANNER_PATH) as f:
            line_count = sum(1 for _ in f)
        assert line_count < 1650, f"scanner.py行数{line_count}应<1650"
        assert line_count > 1200, f"scanner.py行数{line_count}应>1200"

    def test_emotion_cycle_grew(self):
        """emotion_cycle.py增加了update_sentiment_score"""
        with open(_EMOTION_PATH) as f:
            line_count = sum(1 for _ in f)
        assert line_count >= 550, f"emotion_cycle.py行数{line_count}应>=550(含update_sentiment_score)"

    def test_runtime_persistence_grew(self):
        """runtime_persistence.py增加了sync_close_data_to_mongo"""
        with open(_RP_PATH) as f:
            line_count = sum(1 for _ in f)
        assert line_count >= 850, f"runtime_persistence.py行数{line_count}应>=850(含sync_close_data_to_mongo)"


# ==================== 5. 方法存在性验证 ====================

class TestMethodsAccessible:
    """验证提取后的方法通过DELEGATE_MAP仍可访问"""

    def test_update_sentiment_score_in_delegate_map_dict(self):
        """_DELEGATE_MAP字典包含_update_sentiment_score"""
        source = _read_file(_SCANNER_PATH)
        # 解析DELEGATE_MAP
        start = source.find("_DELEGATE_MAP = {")
        end = source.find("}", start) + 1
        # 找最后一个}
        brace_count = 0
        for i in range(start, len(source)):
            if source[i] == '{':
                brace_count += 1
            elif source[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break
        map_code = source[start:end]
        assert '"_update_sentiment_score"' in map_code
        assert '"_sync_close_data_to_mongo"' in map_code


# ==================== 6. 回测零影响 ====================

class TestNoBacktestRegressionV2934:
    """验证回测模块不受影响"""

    def test_sell_signal_checker_api_unchanged(self):
        """sell_signal_checker API不变"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        checker = SellSignalChecker.__new__(SellSignalChecker)
        assert hasattr(type(checker), 'check_realtime_sell')

    def test_strategy_defaults_importable(self):
        """strategy_defaults可正常导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        assert isinstance(STRATEGY_CONFIGS, dict)
        assert len(STRATEGY_CONFIGS) > 0

    def test_portfolio_backtester_importable(self):
        """回测引擎可正常导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_backtest_no_reference_to_new_methods(self):
        """回测引擎不引用新增方法"""
        import importlib
        spec = importlib.util.find_spec("nodes.backtest_engine.factor_selection.portfolio_backtest")
        assert spec is not None
        source = open(spec.origin).read()
        assert "update_sentiment_score" not in source
        assert "sync_close_data_to_mongo" not in source

    def test_emotion_cycle_no_scanner_import(self):
        """EmotionCycleManager.update_sentiment_score不import scanner"""
        source = _read_file(_EMOTION_PATH)
        idx = source.find("async def update_sentiment_score")
        end = source.find("\n\n\n# 全局单例", idx)
        method_code = source[idx:end]
        # 不应有from nodes.market_monitor.scanner import
        assert "from nodes.market_monitor.scanner import" not in method_code, \
            "update_sentiment_score不应import scanner模块"
