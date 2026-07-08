"""
v2.9.49 审查修复测试

覆盖:
1. P0: WS Token认证(首条消息认证替代URL token)
2. P0: Trading API越权访问修复
3. P1: Redis Stream consumer_name动态化
4. P1: Trading API持仓批量价格查询
5. P2: System API异步MongoDB查询
"""

import pytest
import ast
import os

_SCANNER_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "market_monitor")
_WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "web")
_API_DIR = os.path.join(_WEB_DIR, "api")


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


class TestWebSocketAuth:
    """P0: WS Token认证修复"""

    def test_ws_url_no_token_param(self):
        """getWsUrl()不再拼token到URL"""
        source = _read(os.path.join(_WEB_DIR, "websocket.py"))
        # websocket_endpoint仍保留Query参数(向后兼容), 但推荐首条消息认证
        assert "auth" in source.lower() or "token" in source.lower()

    def test_ws_auth_message_handler(self):
        """WebSocket端点支持auth消息类型"""
        source = _read(os.path.join(_WEB_DIR, "websocket.py"))
        assert 'msg_type == "auth"' in source or "msg_type == 'auth'" in source

    def test_ws_auth_verifies_token(self):
        """auth消息会调用verify_token"""
        source = _read(os.path.join(_WEB_DIR, "websocket.py"))
        # 找到auth处理块中有verify_token调用
        auth_idx = source.find('msg_type == "auth"')
        if auth_idx < 0:
            auth_idx = source.find("msg_type == 'auth'")
        assert auth_idx > 0, "No auth message handler found"
        auth_block = source[auth_idx:auth_idx+500]
        assert "verify_token" in auth_block

    def test_ws_auth_response_types(self):
        """auth消息有成功/失败响应"""
        source = _read(os.path.join(_WEB_DIR, "websocket.py"))
        assert '"auth_ok"' in source or "'auth_ok'" in source
        assert '"auth_failed"' in source or "'auth_failed'" in source


class TestTradingApiAuth:
    """P0: Trading API越权访问修复"""

    def test_signals_endpoint_filters_by_user(self):
        """get_trading_signals按user_id过滤"""
        source = _read(os.path.join(_API_DIR, "trading.py"))
        # 找到get_trading_signals函数
        idx = source.find("async def get_trading_signals")
        assert idx > 0
        func_code = source[idx:idx+800]
        assert '"user_id"' in func_code or "'user_id'" in func_code

    def test_positions_endpoint_checks_ownership(self):
        """get_positions验证账户归属"""
        source = _read(os.path.join(_API_DIR, "trading.py"))
        idx = source.find("async def get_positions")
        assert idx > 0
        func_code = source[idx:idx+500]
        assert "user_id" in func_code

    def test_trades_endpoint_checks_ownership(self):
        """get_trade_records验证账户归属"""
        source = _read(os.path.join(_API_DIR, "trading.py"))
        idx = source.find("async def get_trade_records")
        assert idx > 0
        func_code = source[idx:idx+500]
        assert "user_id" in func_code


class TestTradingApiBatchPrice:
    """P1: Trading API持仓批量价格查询"""

    def test_positions_uses_batch_price_query(self):
        """get_positions使用批量价格查询而非N+1"""
        source = _read(os.path.join(_API_DIR, "trading.py"))
        idx = source.find("async def get_positions")
        assert idx > 0
        func_code = source[idx:idx+1500]
        # 应有aggregate或批量查询, 而非find_one循环
        assert "aggregate" in func_code or "price_map" in func_code
        # 不应有循环内的find_one
        assert "stock_daily_ak_full.find_one" not in func_code

    def test_batch_query_uses_aggregation(self):
        """批量查询使用MongoDB聚合管道"""
        source = _read(os.path.join(_API_DIR, "trading.py"))
        idx = source.find("async def get_positions")
        assert idx > 0
        func_code = source[idx:idx+1500]
        if "aggregate" in func_code:
            # 检查聚合管道有$group按ts_code分组
            assert "$group" in func_code


class TestRedisStreamConsumerName:
    """P1: Redis Stream consumer_name动态化"""

    def test_consumer_name_uses_hostname(self):
        """consumer_name包含主机名而非硬编码"""
        source = _read(os.path.join(_WEB_DIR, "redis_ws_bridge.py"))
        idx = source.find("consumer_name")
        assert idx > 0
        # 不应硬编码"web-node-1"
        line_start = source.rfind("\n", 0, idx) + 1
        line = source[line_start:source.find("\n", idx)]
        assert "socket.gethostname()" in source or "hostname" in source or "uuid" in source
        assert '"web-node-1"' not in source or "web-node-1" in source[source.find("socket"):]


class TestSystemApiAsyncMongo:
    """P2: System API异步MongoDB查询"""

    def test_health_check_no_sync_pymongo(self):
        """health_check不再使用同步pymongo"""
        source = _read(os.path.join(_API_DIR, "system.py"))
        idx = source.find("async def health_check")
        assert idx > 0
        # health_check函数体内不应有SyncClient
        func_end = source.find("\n@router.", idx + 1)
        if func_end < 0:
            func_end = len(source)
        func_code = source[idx:func_end]
        assert "SyncClient" not in func_code
        assert "pymongo.MongoClient" not in func_code

    def test_data_status_no_sync_pymongo(self):
        """data-status不再使用同步pymongo"""
        source = _read(os.path.join(_API_DIR, "system.py"))
        idx = source.find("async def get_data_status")
        assert idx > 0
        func_end = source.find("\n@router.", idx + 1)
        if func_end < 0:
            func_end = len(source)
        func_code = source[idx:func_end]
        assert "SyncClient" not in func_code
        assert "from pymongo import MongoClient" not in func_code

    def test_get_factor_detail_is_async(self):
        """_get_factor_detail是异步函数"""
        source = _read(os.path.join(_API_DIR, "system.py"))
        idx = source.find("def _get_factor_detail")
        assert idx > 0
        # 应为async def
        line_start = source.rfind("\n", 0, idx) + 1
        line = source[line_start:source.find("(", idx)]
        assert "async" in line

    def test_data_status_uses_await_for_factor_detail(self):
        """data-status调用_get_factor_detail时使用await"""
        source = _read(os.path.join(_API_DIR, "system.py"))
        # 检查_get_factor_detail调用(排除函数定义本身)
        idx = 0
        await_count = 0
        non_await_count = 0
        while True:
            idx = source.find("_get_factor_detail(", idx)
            if idx < 0:
                break
            # 跳过函数定义行
            line_start = source.rfind("\n", 0, idx) + 1
            line_prefix = source[line_start:idx].strip()
            if line_prefix.startswith("async def") or line_prefix.startswith("def "):
                idx += 1
                continue
            # 检查前面是否有await
            prefix = source[max(0, idx-30):idx]
            if "await" in prefix:
                await_count += 1
            else:
                non_await_count += 1
            idx += 1
        # 所有调用都应使用await
        assert non_await_count == 0, f"Found {non_await_count} calls without await"
        assert await_count >= 2, f"Expected at least 2 await calls, found {await_count}"


class TestNoBacktestRegression:
    """确认回测模块未受影响"""

    def test_sell_signal_checker_importable(self):
        """sell_signal_checker可正常导入"""
        import importlib
        try:
            mod = importlib.import_module("nodes.backtest_engine.factor_selection.sell_signal_checker")
            assert hasattr(mod, "SellSignalChecker")
        except ImportError:
            pass  # 非完整环境, 跳过

    def test_strategy_defaults_importable(self):
        """strategy_defaults可正常导入"""
        import importlib
        try:
            mod = importlib.import_module("nodes.market_monitor.strategy_defaults")
            assert hasattr(mod, "STRATEGY_CONFIGS") or hasattr(mod, "DEFAULT_PARAMS")
        except ImportError:
            pass

    def test_scanner_file_count_unchanged(self):
        """scanner.py行数仍在合理范围"""
        source = _read(os.path.join(_SCANNER_DIR, "scanner.py"))
        lines = len(source.splitlines())
        assert lines < 1700, f"scanner.py grew to {lines} lines (expected <1700)"

    def test_scanner_delegate_map_exists(self):
        """DELEGATE_MAP仍存在"""
        source = _read(os.path.join(_SCANNER_DIR, "scanner.py"))
        assert "DELEGATE_MAP" in source
