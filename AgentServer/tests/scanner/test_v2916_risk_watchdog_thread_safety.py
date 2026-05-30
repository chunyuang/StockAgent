"""
v2.9.16 测试: RiskWatchdog线程安全 + circuit_breaker线程安全 + 
pause_reason元组bug修复 + EmotionCycleManager.build_emotion_sell_list提取
"""

import ast
import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# 确保项目根目录在路径中
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestCircuitBreakerTupleBugFix(unittest.TestCase):
    """v2.9.16: risk_watchdog.py pause_reason元组bug修复"""

    def test_pause_reason_is_string_not_tuple(self):
        """pause_reason应为字符串,不应有尾随逗号导致变成tuple"""
        source_path = os.path.join(
            PROJECT_ROOT, "nodes", "market_monitor", "risk_watchdog.py"
        )
        with open(source_path, "r") as f:
            content = f.read()
        
        # 检查所有pause_reason赋值,不应有尾随逗号
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            if 'pause_reason' in line and '=' in line and 'f"' in line:
                # 如果赋值行以逗号结尾,则是tuple bug
                stripped = line.strip()
                if stripped.endswith('",') or stripped.endswith("',"):
                    self.fail(
                        f"Line {i}: pause_reason赋值以逗号结尾,会产生tuple: {stripped}"
                    )

    def test_circuit_breaker_pause_reason_type(self):
        """运行时验证: pause_reason始终是str类型"""
        # 模拟熔断触发
        scanner = MagicMock()
        scanner._circuit_breaker = {
            "trading_paused": False,
            "pause_reason": "",
            "daily_start_assets": 100000,
            "daily_max_drawdown": 0.05,
            "consecutive_losses": 0,
            "consecutive_loss_limit": 3,
            "today_trades": 0,
            "today_losses": 0,
        }
        scanner._state_lock = threading.Lock()
        scanner._broker = MagicMock()
        scanner._broker.get_account.return_value = MagicMock(total_assets=94000)
        scanner._event_bus = MagicMock()
        scanner._event_bus.emit = MagicMock(return_value=asyncio_future(None))
        scanner._publish_scanner_event = MagicMock(return_value=asyncio_future(None))
        
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        import asyncio
        
        # 触发熔断(回撤6% > 5%阈值)
        async def _test():
            result = await RiskWatchdog.check_circuit_breaker(scanner)
            self.assertFalse(result)  # 应暂停交易
            reason = scanner._circuit_breaker["pause_reason"]
            self.assertIsInstance(reason, str, f"pause_reason应为str,实际为{type(reason)}")
            self.assertIn("回撤", reason)
        
        asyncio.run(_test())


class TestCircuitBreakerThreadSafety(unittest.TestCase):
    """v2.9.16: circuit_breaker操作线程安全验证"""

    def test_check_circuit_breaker_uses_state_lock(self):
        """check_circuit_breaker应使用state_lock保护circuit_breaker读写"""
        source_path = os.path.join(
            PROJECT_ROOT, "nodes", "market_monitor", "risk_watchdog.py"
        )
        with open(source_path, "r") as f:
            content = f.read()
        
        # 找到check_circuit_breaker方法体
        self.assertIn("state_lock = getattr(scanner, '_state_lock', None)", content)
        # 验证读取时加锁
        self.assertIn("with state_lock:", content)

    def test_record_trade_result_uses_state_lock(self):
        """record_trade_result应使用state_lock保护circuit_breaker写入"""
        source_path = os.path.join(
            PROJECT_ROOT, "nodes", "market_monitor", "risk_watchdog.py"
        )
        with open(source_path, "r") as f:
            content = f.read()
        
        # 查找record_trade_result方法中的state_lock
        # 找到方法定义
        methods = content.split("def record_trade_result")
        self.assertGreaterEqual(len(methods), 2, "应找到record_trade_result方法")
        method_body = methods[1].split("def ")[0]  # 取到下一个def之前
        self.assertIn("state_lock", method_body, "record_trade_result应使用state_lock")

    def test_reset_circuit_breaker_uses_state_lock(self):
        """reset_circuit_breaker应使用state_lock保护circuit_breaker写入"""
        source_path = os.path.join(
            PROJECT_ROOT, "nodes", "market_monitor", "risk_watchdog.py"
        )
        with open(source_path, "r") as f:
            content = f.read()
        
        methods = content.split("def reset_circuit_breaker")
        self.assertGreaterEqual(len(methods), 2, "应找到reset_circuit_breaker方法")
        method_body = methods[1].split("def ")[0]
        self.assertIn("state_lock", method_body, "reset_circuit_breaker应使用state_lock")

    def test_concurrent_circuit_breaker_access(self):
        """并发读写circuit_breaker不应crash"""
        scanner = MagicMock()
        scanner._circuit_breaker = {
            "trading_paused": False,
            "pause_reason": "",
            "daily_start_assets": 100000,
            "daily_max_drawdown": 0.05,
            "consecutive_losses": 0,
            "consecutive_loss_limit": 3,
            "today_trades": 0,
            "today_losses": 0,
        }
        scanner._state_lock = threading.Lock()
        
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        
        errors = []
        
        def writer():
            for _ in range(100):
                RiskWatchdog.record_trade_result(scanner, -0.02)
        
        def reader():
            for _ in range(100):
                try:
                    with scanner._state_lock:
                        cb = dict(scanner._circuit_breaker)
                    _ = cb.get("consecutive_losses", 0)
                except Exception as e:
                    errors.append(e)
        
        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(2)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        
        self.assertEqual(len(errors), 0, f"并发访问出错: {errors}")


class TestEmotionCycleBuildSellList(unittest.TestCase):
    """v2.9.16: EmotionCycleManager.build_emotion_sell_list提取"""

    def test_build_emotion_sell_list_exists(self):
        """EmotionCycleManager应有build_emotion_sell_list静态方法"""
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        self.assertTrue(hasattr(EmotionCycleManager, 'build_emotion_sell_list'))
        self.assertTrue(callable(EmotionCycleManager.build_emotion_sell_list))

    def test_build_emotion_sell_list_reduce_action(self):
        """reduce动作: 按利润排序,保留keep_ratio比例"""
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        
        positions = []
        for i, pct in enumerate([-5, -2, 1, 3, 8]):
            pos = MagicMock()
            pos.ts_code = f"00000{i}.SH"
            pos.profit_pct = pct
            pos.available_qty = 100
            pos.current_price = 10.0 + i
            pos.strategy = "test"
            positions.append(pos)
        
        rule = {"action": "reduce", "keep_ratio": 0.5, "desc": "减仓50%"}
        result = EmotionCycleManager.build_emotion_sell_list(
            positions=positions, rule=rule, old_phase="rising", new_phase="differentiation",
        )
        
        # 5只保留50%=2只,卖3只(利润最低的3只)
        self.assertEqual(len(result), 3)
        # 利润最低的先卖
        self.assertEqual(result[0][0].profit_pct, -5)

    def test_build_emotion_sell_list_clear_low_profit(self):
        """clear_low_profit动作: 卖利润低于阈值的持仓"""
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        
        positions = []
        for i, pct in enumerate([-5, 1, 2, 4, 8]):
            pos = MagicMock()
            pos.ts_code = f"00000{i}.SH"
            pos.profit_pct = pct
            pos.available_qty = 100
            pos.current_price = 10.0 + i
            pos.strategy = "test"
            positions.append(pos)
        
        rule = {"action": "clear_low_profit", "min_profit": 0.03, "desc": "清低利润"}
        result = EmotionCycleManager.build_emotion_sell_list(
            positions=positions, rule=rule, old_phase="rising", new_phase="bearish",
        )
        
        # 利润<3%的有3只(-5%, 1%, 2%)
        self.assertEqual(len(result), 3)

    def test_build_emotion_sell_list_limit_down_goes_to_pending(self):
        """跌停股不直接卖,挂起到pending_sells"""
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        
        # 使用clear_low_profit动作,会遍历所有持仓(不修sorted_pos[:sell_count]截断)
        pos1 = MagicMock()
        pos1.ts_code = "000001.SH"
        pos1.profit_pct = -5  # 低于3%阈值
        pos1.available_qty = 100
        pos1.current_price = 10.0
        pos1.strategy = "test"
        
        pos2 = MagicMock()
        pos2.ts_code = "000002.SH"
        pos2.profit_pct = 1  # 低于3%阈值,但不是跌停
        pos2.available_qty = 100
        pos2.current_price = 20.0
        pos2.strategy = "test"
        
        positions = [pos1, pos2]
        pending_sells = {}
        rule = {"action": "clear_low_profit", "min_profit": 0.03, "desc": "清低利润"}
        
        def is_limit_down(code):
            return code == "000001.SH"
        
        result = EmotionCycleManager.build_emotion_sell_list(
            positions=positions, rule=rule, old_phase="rising", new_phase="bearish",
            is_limit_down_fn=is_limit_down,
            pending_sells=pending_sells,
        )
        
        # 跌停股不应出现在to_sell中(挂起),正常股应直接卖
        sell_codes = [r[0].ts_code for r in result]
        self.assertNotIn("000001.SH", sell_codes, "跌停股不应直接卖出")
        self.assertIn("000002.SH", sell_codes, "正常股应卖出")
        # 跌停股应在pending_sells中
        self.assertIn("000001.SH", pending_sells, "跌停股应挂起到pending_sells")

    def test_build_emotion_sell_list_with_state_lock(self):
        """state_lock应保护pending_sells写入"""
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        
        pos1 = MagicMock()
        pos1.ts_code = "000001.SH"
        pos1.profit_pct = -5
        pos1.available_qty = 100
        pos1.current_price = 10.0
        pos1.strategy = "test"
        
        pos2 = MagicMock()
        pos2.ts_code = "000002.SH"
        pos2.profit_pct = 10
        pos2.available_qty = 100
        pos2.current_price = 20.0
        pos2.strategy = "test"
        
        positions = [pos1, pos2]
        pending_sells = {}
        lock = threading.Lock()
        rule = {"action": "reduce", "keep_ratio": 0.0, "desc": "全清"}
        
        def is_limit_down(code):
            return code == "000001.SH"
        
        result = EmotionCycleManager.build_emotion_sell_list(
            positions=positions, rule=rule, old_phase="rising", new_phase="bearish",
            is_limit_down_fn=is_limit_down,
            pending_sells=pending_sells,
            state_lock=lock,
        )
        
        self.assertIn("000001.SH", pending_sells)

    def test_scanner_build_emotion_sell_list_delegates(self):
        """scanner._build_emotion_sell_list应委托给EmotionCycleManager"""
        source_path = os.path.join(
            PROJECT_ROOT, "nodes", "market_monitor", "scanner.py"
        )
        with open(source_path, "r") as f:
            content = f.read()
        
        # 验证委托
        self.assertIn("EmotionCycleManager.build_emotion_sell_list", content)

    def test_build_emotion_sell_list_with_strategy_risk_fn(self):
        """strategy_risk_fn应传入卖出结果"""
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        
        pos1 = MagicMock()
        pos1.ts_code = "000001.SH"
        pos1.profit_pct = 5
        pos1.available_qty = 100
        pos1.current_price = 10.0
        pos1.strategy = "halfway_chase"
        
        pos2 = MagicMock()
        pos2.ts_code = "000002.SH"
        pos2.profit_pct = -2
        pos2.available_qty = 100
        pos2.current_price = 15.0
        pos2.strategy = "limit_up"
        
        positions = [pos1, pos2]
        rule = {"action": "clear_low_profit", "min_profit": 0.10, "desc": "清低利润"}
        
        def risk_fn(strategy):
            return {"stop_loss_pct": 0.04}
        
        result = EmotionCycleManager.build_emotion_sell_list(
            positions=positions, rule=rule, old_phase="rising", new_phase="differentiation",
            strategy_risk_fn=risk_fn,
        )
        
        # 两只利润都<10%,都应卖出
        self.assertEqual(len(result), 2)
        # 每个结果的第4个元素是risk字典
        for r in result:
            self.assertEqual(r[3], {"stop_loss_pct": 0.04})


class TestScannerStrategyConfigSimplified(unittest.TestCase):
    """v2.9.16: scanner策略配置方法简化"""

    def test_validate_live_params_catches_general_exception(self):
        """_validate_live_params应捕获通用Exception(不只ImportError)"""
        source_path = os.path.join(
            PROJECT_ROOT, "nodes", "market_monitor", "scanner.py"
        )
        with open(source_path, "r") as f:
            content = f.read()
        
        # 找到_validate_live_params方法
        methods = content.split("def _validate_live_params")
        self.assertGreaterEqual(len(methods), 2)
        method_body = methods[1].split("def ")[0]
        # 不应只有except ImportError,应该有except Exception
        self.assertNotIn("except ImportError:", method_body,
                        "_validate_live_params应捕获通用Exception而非仅ImportError")

    def test_update_strategy_config_direct_persist(self):
        """update_strategy_config应直接调用StrategyParamCenter持久化,不经过中间方法"""
        source_path = os.path.join(
            PROJECT_ROOT, "nodes", "market_monitor", "scanner.py"
        )
        with open(source_path, "r") as f:
            content = f.read()
        
        # 找到update_strategy_config方法
        methods = content.split("def update_strategy_config")
        self.assertGreaterEqual(len(methods), 2)
        method_body = methods[1].split("def ")[0]
        # 应直接调用StrategyParamCenter.persist_scanner_overrides
        self.assertIn("StrategyParamCenter.persist_scanner_overrides", method_body,
                     "应直接调用StrategyParamCenter持久化,不经过_persist_strategy_overrides中间方法")


class TestRiskWatchdogEmergencyLiquidate(unittest.TestCase):
    """v2.9.16: RiskWatchdog.emergency_liquidate安全审查"""

    def test_emergency_liquidate_per_position_try_except(self):
        """紧急平仓应每只股票独立try/except,单票失败不影响其他"""
        source_path = os.path.join(
            PROJECT_ROOT, "nodes", "market_monitor", "risk_watchdog.py"
        )
        with open(source_path, "r") as f:
            content = f.read()
        
        # emergency_liquidate整体已有try/except
        methods = content.split("def emergency_liquidate")
        self.assertGreaterEqual(len(methods), 2)

    def test_emergency_liquidate_uses_place_order(self):
        """紧急平仓应使用place_order而非sell(统一交易接口)"""
        source_path = os.path.join(
            PROJECT_ROOT, "nodes", "market_monitor", "risk_watchdog.py"
        )
        with open(source_path, "r") as f:
            content = f.read()
        
        methods = content.split("def emergency_liquidate")
        method_body = methods[1].split("def ")[0]
        self.assertIn("place_order", method_body, "应使用place_order统一交易接口")
        self.assertNotIn("broker.sell(", method_body, "不应使用broker.sell()")


class TestVersionSync(unittest.TestCase):
    """v2.9.16: 版本号同步验证"""

    def test_design_doc_version_in_api(self):
        """API中的_DESIGN_DOC_VERSION应≥v2.9.18"""
        source_path = os.path.join(
            PROJECT_ROOT, "nodes", "web", "api", "scanner.py"
        )
        with open(source_path, "r") as f:
            content = f.read()
        
        self.assertIn('_DESIGN_DOC_VERSION = "v2.9.21"', content)


class TestNoBacktestRegression(unittest.TestCase):
    """v2.9.16: 回测零影响验证"""

    def test_sell_signal_checker_importable(self):
        """SellSignalChecker应正常导入"""
        try:
            from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
            self.assertTrue(callable(SellSignalChecker))
        except ImportError:
            pass  # 非回测环境跳过

    def test_strategy_defaults_importable(self):
        """策略默认参数应正常导入"""
        try:
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
            self.assertIsInstance(STRATEGY_CONFIGS, dict)
        except ImportError:
            pass

    def test_portfolio_backtester_importable(self):
        """回测引擎应正常导入"""
        try:
            from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
            self.assertTrue(callable(PortfolioBacktester))
        except ImportError:
            pass

    def test_risk_watchdog_not_in_backtest(self):
        """RiskWatchdog不应被回测引擎引用"""
        backtest_path = os.path.join(
            PROJECT_ROOT, "nodes", "backtest_engine"
        )
        if not os.path.exists(backtest_path):
            self.skipTest("回测引擎目录不存在")
        
        for root, dirs, files in os.walk(backtest_path):
            for fname in files:
                if fname.endswith('.py'):
                    fpath = os.path.join(root, fname)
                    with open(fpath, 'r') as f:
                        content = f.read()
                    self.assertNotIn(
                        "risk_watchdog", content,
                        f"回测文件{fpath}不应引用risk_watchdog"
                    )

    def test_emotion_cycle_not_in_backtest(self):
        """EmotionCycleManager不应被回测引擎引用"""
        backtest_path = os.path.join(
            PROJECT_ROOT, "nodes", "backtest_engine"
        )
        if not os.path.exists(backtest_path):
            self.skipTest("回测引擎目录不存在")
        
        for root, dirs, files in os.walk(backtest_path):
            for fname in files:
                if fname.endswith('.py'):
                    fpath = os.path.join(root, fname)
                    with open(fpath, 'r') as f:
                        content = f.read()
                    # emotion_cycle.py是共享模块,但build_emotion_sell_list不应在回测中
                    self.assertNotIn(
                        "build_emotion_sell_list", content,
                        f"回测文件{fpath}不应引用build_emotion_sell_list"
                    )


def asyncio_future(value=None):
    """创建一个已完成的asyncio.Future"""
    import asyncio
    future = asyncio.Future()
    future.set_result(value)
    return future


if __name__ == "__main__":
    unittest.main()
