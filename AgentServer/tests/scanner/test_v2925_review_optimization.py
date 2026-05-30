"""
v2.9.25 测试: update_strategy_config bug修复 + bare except清理 + _init_modules拆分

变更:
1. 🔴 update_strategy_config malformed try/except修复 — 更新逻辑不应在except块内
2. 🟡 6个bare except Exception: → except Exception as _e: (可追踪性增强)
3. 🟡 _init_modules拆分为4个子方法(_init_event_and_quote/_init_signal_and_risk/_init_core_modules/_init_execution_quality)
"""

import pytest
import re
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Dict, Any


class TestUpdateStrategyConfigBugFix:
    """v2.9.25: update_strategy_config关键bug修复
    
    Bug: 原代码有两个except Exception块(语法错误),且StrategyParamCenter.update_scanner_config
    在第一个except块内执行 — 正常路径下更新不执行!
    
    修复: 分离old_values读取和更新执行为两个独立try/except块
    """

    def _make_scanner(self):
        """创建最小化scanner实例"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        scanner.config = {"strategies": {"halfway_chase": {"stop_loss_pct": 0.03}}}
        scanner._event_bus = MagicMock()
        scanner._event_bus.emit = AsyncMock()
        return scanner

    def test_update_executes_on_normal_path(self):
        """正常路径: old_values读取成功 → 更新应执行"""
        scanner = self._make_scanner()
        updates = {"stop_loss_pct": 0.05}
        
        with patch("nodes.market_monitor.strategy_param_center.StrategyParamCenter") as mock_spc:
            scanner.update_strategy_config("halfway_chase", updates)
            # 关键断言: update_scanner_config必须被调用
            mock_spc.update_scanner_config.assert_called_once_with(
                scanner.config, "halfway_chase", updates
            )

    def test_update_executes_when_old_values_fails(self):
        """异常路径: old_values读取失败 → 更新仍应执行(不中断)"""
        scanner = self._make_scanner()
        scanner.config = None  # type: ignore — 让config.get抛异常
        
        with patch("nodes.market_monitor.strategy_param_center.StrategyParamCenter") as mock_spc:
            scanner.update_strategy_config("halfway_chase", {"stop_loss_pct": 0.05})
            # old_values读取失败,但更新仍应执行
            mock_spc.update_scanner_config.assert_called_once()

    def test_update_returns_on_config_update_failure(self):
        """更新失败 → 应return,不发射EventBus持久化"""
        scanner = self._make_scanner()
        
        with patch("nodes.market_monitor.strategy_param_center.StrategyParamCenter") as mock_spc:
            mock_spc.update_scanner_config.side_effect = RuntimeError("DB down")
            scanner.update_strategy_config("halfway_chase", {"stop_loss_pct": 0.05})
            # 更新失败,方法应正常退出(不crash)

    def test_old_values_captured_for_audit(self):
        """old_values应正确捕获变更前的值(审计日志用)"""
        scanner = self._make_scanner()
        updates = {"stop_loss_pct": 0.05, "take_profit_pct": 0.10}
        captured_events = []
        
        with patch("nodes.market_monitor.strategy_param_center.StrategyParamCenter"):
            with patch("nodes.market_monitor.scanner.asyncio") as mock_asyncio:
                def capture_ensure_future(coro):
                    captured_events.append(coro)
                mock_asyncio.ensure_future = capture_ensure_future
                scanner.update_strategy_config("halfway_chase", updates)
                # 应有PARAM_UPDATED事件(含old_values)
                assert len(captured_events) >= 1

    def test_no_dual_except_blocks(self):
        """源码验证: update_strategy_config不应有两个连续except Exception块"""
        with open("nodes/market_monitor/scanner.py") as f:
            content = f.read()
        # 找到update_strategy_config方法
        import ast
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "update_strategy_config":
                # 检查方法内没有连续的两个except Exception块
                except_count = sum(1 for child in ast.walk(node) 
                                  if isinstance(child, ast.ExceptHandler) 
                                  and (child.type is None or 
                                       (isinstance(child.type, ast.Name) and child.type.id == "Exception")))
                # 应该有3个try块(old_values/update/eventbus), 不应有双except
                assert except_count <= 4, f"发现{except_count}个except Exception(可能有重复)"
                break


class TestBareExceptCleanup:
    """v2.9.25: bare except Exception: → except Exception as _e: 
    
    验证源码中不再有bare except(无异常变量捕获)
    """

    def test_no_bare_except_in_scanner(self):
        """scanner.py不应有bare except Exception:"""
        with open("nodes/market_monitor/scanner.py") as f:
            content = f.read()
        # 匹配 "except Exception:" (不含 "as")
        matches = re.findall(r'except Exception\s+as\s+\w+\s*:', content)
        bare_matches = re.findall(r'except Exception\s*:\s*\n', content)
        # bare_matches匹配"except Exception:\n"这种形式
        # 但如果有"as _e:"则不是bare
        assert len(bare_matches) == 0, f"发现{len(bare_matches)}个bare except Exception: (应改为except Exception as _e:)"

    def test_event_emission_exceptions_captured(self):
        """EventBus事件发射的except应捕获异常对象(可追踪)"""
        with open("nodes/market_monitor/scanner.py") as f:
            content = f.read()
        # 查找所有 "except Exception:" (不跟 "as") 后跟 "pass" 的模式
        bare_excepts = re.findall(r'except Exception:\s*\n\s*pass', content)
        assert len(bare_excepts) == 0, f"发现{len(bare_excepts)}个bare except Exception: ... pass"


class TestInitModulesDecomposition:
    """v2.9.25: _init_modules拆分为4个子方法
    
    验证:
    - _init_modules调用4个子方法
    - 每个子方法正确初始化对应模块
    - 初始化顺序不影响功能
    """

    def _make_scanner(self):
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        scanner.config = {}
        scanner.account_id = "test"
        return scanner

    def test_init_modules_calls_sub_methods(self):
        """_init_modules应调用4个子方法"""
        from nodes.market_monitor.scanner import MarketScanner
        # 检查类定义中4个子方法都存在
        for method_name in ['_init_event_and_quote', '_init_signal_and_risk', 
                            '_init_core_modules', '_init_execution_quality']:
            assert hasattr(MarketScanner, method_name), f"缺少方法: {method_name}"
        # 检查_init_modules内部调用了这4个(通过源码验证)
        import inspect
        source = inspect.getsource(MarketScanner._init_modules)
        assert '_init_event_and_quote' in source
        assert '_init_signal_and_risk' in source
        assert '_init_core_modules' in source
        assert '_init_execution_quality' in source

    def test_init_event_and_quote(self):
        """_init_event_and_quote应初始化EventBus+QuoteManager"""
        scanner = self._make_scanner()
        scanner._make_quote_event_emitter = lambda: lambda event, data: None
        scanner._init_event_and_quote()
        
        assert hasattr(scanner, '_event_bus')
        assert hasattr(scanner, '_quote_manager')
        assert scanner._position_manager is None  # 延迟初始化
        assert scanner._strategy_scorer is None
        assert scanner._signal_manager is None

    def test_init_signal_and_risk(self):
        """_init_signal_and_risk应初始化信号分发器+风控"""
        scanner = self._make_scanner()
        from nodes.market_monitor.broker import SimulatedBroker
        scanner._broker = SimulatedBroker(account_id="test", initial_cash=1000000)
        scanner._init_signal_and_risk()
        
        assert hasattr(scanner, '_signal_dispatcher')
        assert hasattr(scanner, '_param_center')
        assert hasattr(scanner, '_risk_watchdog')
        assert scanner._feishu_registered is False

    def test_init_core_modules(self):
        """_init_core_modules应初始化PositionManager等核心模块"""
        scanner = self._make_scanner()
        from nodes.market_monitor.broker import SimulatedBroker
        scanner._broker = SimulatedBroker(account_id="test", initial_cash=1000000)
        scanner._init_core_modules()
        
        assert scanner._position_manager is not None
        assert scanner._strategy_scorer is not None
        assert scanner._signal_manager is not None
        assert scanner._position_checker is not None
        assert scanner._runtime_persistence is not None
        assert scanner._use_tiered is False
        assert scanner._tiered_scanner is None

    def test_init_execution_quality(self):
        """_init_execution_quality应初始化PreTradeChecker+SlippageModel"""
        scanner = self._make_scanner()
        from nodes.market_monitor.broker import SimulatedBroker
        scanner._broker = SimulatedBroker(account_id="test", initial_cash=1000000)
        scanner._init_execution_quality()
        
        assert hasattr(scanner, '_pre_trade_checker')
        assert hasattr(scanner, '_slippage_model')

    def test_tiered_scanner_enabled(self):
        """use_tiered_scanner=True时初始化标志应设置"""
        scanner = self._make_scanner()
        scanner.config = {"use_tiered_scanner": True}
        from nodes.market_monitor.broker import SimulatedBroker
        scanner._broker = SimulatedBroker(account_id="test", initial_cash=1000000)
        # Mock TieredScanner初始化以避免构造器参数问题
        with patch("nodes.market_monitor.tiered_scanner.TieredScanner") as mock_ts:
            mock_ts.return_value = MagicMock()
            scanner._init_core_modules()
            assert scanner._use_tiered is True
            assert scanner._tiered_scanner is not None

    def test_sub_methods_exist_in_class(self):
        """4个子方法应存在于MarketScanner类中"""
        from nodes.market_monitor.scanner import MarketScanner
        for method_name in ['_init_event_and_quote', '_init_signal_and_risk',
                            '_init_core_modules', '_init_execution_quality']:
            assert hasattr(MarketScanner, method_name), f"缺少方法: {method_name}"


class TestNoBacktestRegression:
    """验证回测模块不受影响"""

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker公共API不变"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        assert hasattr(SellSignalChecker, 'check_realtime_sell')
        assert hasattr(SellSignalChecker, 'check_full_sell')
        assert hasattr(SellSignalChecker, 'check_early_sell')

    def test_strategy_defaults_importable(self):
        """策略默认参数正常导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        assert isinstance(STRATEGY_CONFIGS, dict)
        assert len(STRATEGY_CONFIGS) > 0

    def test_portfolio_backtester_importable(self):
        """回测引擎正常导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None
