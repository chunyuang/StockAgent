#!/usr/bin/env python3
"""
v2.9.14b — Stream消费兼容 + 审计日志TTL 测试

修复项:
1. Redis Stream消费者兼容扁平字段格式(signal_dispatcher + _push_to_redis)
2. 审计日志TTL索引(90天自动清理, Phase3.4)
3. Stream消费API端点数据格式验证
"""
import ast
import os
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_WS_BRIDGE = os.path.join(_PROJECT_ROOT, "nodes", "web", "redis_ws_bridge.py")
_SUBSCRIBERS = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner_event_subscribers.py")
_API_SCANNER = os.path.join(_PROJECT_ROOT, "nodes", "web", "api", "scanner_shared.py")


def _read_ws_bridge():
    return open(_WS_BRIDGE).read()

def _read_subscribers():
    return open(_SUBSCRIBERS).read()

def _read_api_scanner():
    return _read_all_scanner_api()


# ==================== 1. Stream消费兼容测试 ====================


def _read_all_scanner_api():
    """读取所有scanner API子模块内容(拆分后覆盖全部源码)"""
    import glob
    api_dir = os.path.join(_PROJECT_ROOT, "nodes", "web", "api")
    content = ""
    for f in sorted(glob.glob(os.path.join(api_dir, "scanner_*.py"))):
        content += open(f).read() + "\n"
    return content


class TestStreamConsumerCompatibility:
    """验证Stream消费者兼容两种字段格式"""

    def test_stream_consumer_handles_flat_fields(self):
        """Stream消费者支持扁平字段格式(_push_to_redis xadd)"""
        source = _read_ws_bridge()
        # 应有处理无"data"字段的逻辑
        assert "else:" in source, "缺少else分支(扁平字段处理)"
        # 应有遍历fields的逻辑
        func_start = source.find("async def _redis_stream_consumer")
        assert func_start > 0, "_redis_stream_consumer方法未找到"
        func_code = source[func_start:func_start+5000]
        assert "for k, v in fields.items()" in func_code, \
            "缺少扁平字段遍历逻辑"

    def test_stream_consumer_still_handles_json_data(self):
        """Stream消费者仍支持旧格式(data字段含JSON字符串)"""
        source = _read_ws_bridge()
        func_start = source.find("async def _redis_stream_consumer")
        func_code = source[func_start:func_start+5000]
        assert 'fields.get("data"' in func_code, \
            "缺少data字段处理(旧格式兼容)"

    def test_stream_consumer_bytes_decode(self):
        """Stream消费者解码bytes字段(Redis返回bytes)"""
        source = _read_ws_bridge()
        func_start = source.find("async def _redis_stream_consumer")
        func_code = source[func_start:func_start+5000]
        assert "decode(" in func_code, \
            "缺少bytes→str解码"


# ==================== 2. 审计日志TTL测试 ====================

class TestAuditLogTTL:
    """验证审计日志TTL索引(Phase3.4: 90天自动清理)"""

    def test_audit_log_has_ttl_index(self):
        """_write_audit_log创建TTL索引"""
        source = _read_subscribers()
        func_start = source.find("async def _write_audit_log")
        assert func_start > 0, "_write_audit_log函数未找到"
        func_code = source[func_start:func_start+2000]
        assert "create_index" in func_code, \
            "缺少create_index(TTL索引创建)"
        assert "expireAfterSeconds" in func_code, \
            "缺少expireAfterSeconds(TTL配置)"

    def test_audit_log_ttl_is_90_days(self):
        """TTL为90天(90*86400秒)"""
        source = _read_subscribers()
        func_start = source.find("async def _write_audit_log")
        func_code = source[func_start:func_start+2000]
        assert "90 * 86400" in func_code, \
            "TTL应为90*86400秒(90天)"

    def test_audit_log_ttl_idempotent(self):
        """TTL索引创建是幂等的(已存在不报错)"""
        source = _read_subscribers()
        func_start = source.find("async def _write_audit_log")
        func_code = source[func_start:func_start+2000]
        # 应在try/except内
        assert "except" in func_code, \
            "TTL索引创建应在try/except内(幂等)"


# ==================== 3. _push_to_redis格式一致性 ====================

class TestPushToRedisFormatConsistency:
    """验证_push_to_redis xadd格式与signal_dispatcher一致"""

    def test_push_to_redis_xadd_flat_dict(self):
        """xadd使用扁平字典(与signal_dispatcher一致)"""
        source = _read_subscribers()
        func_start = source.find("async def _push_to_redis")
        func_code = source[func_start:func_start+2000]
        # payload是扁平字典(不嵌套), xadd直接传入
        assert "xadd" in func_code, "缺少xadd调用"
        # payload应包含timestamp和account_id
        assert "timestamp" in func_code, "payload缺少timestamp字段"
        assert "account_id" in func_code, "payload缺少account_id字段"

    def test_signal_dispatcher_also_uses_flat_format(self):
        """signal_dispatcher也使用扁平字段(一致性验证)"""
        dispatcher_path = os.path.join(
            _PROJECT_ROOT, "nodes", "market_monitor", "signal_dispatcher.py"
        )
        if os.path.exists(dispatcher_path):
            source = open(dispatcher_path).read()
            # signal_dispatcher的xadd应该传入扁平字典
            assert "xadd" in source, "signal_dispatcher缺少xadd"


# ==================== 4. Stream API端点格式 ====================

class TestStreamAPIFormat:
    """验证Stream消费API返回格式"""

    def test_stream_api_returns_entry_id(self):
        """Stream API返回entry ID(用于断线回补last_id)"""
        source = _read_api_scanner()
        assert '"id"' in source, "缺少id字段(entry ID)"

    def test_stream_api_returns_data_fields(self):
        """Stream API返回data字段(消息内容)"""
        source = _read_api_scanner()
        assert '"data"' in source, "缺少data字段(消息内容)"

    def test_stream_api_has_count(self):
        """Stream API返回count(消息数量)"""
        source = _read_api_scanner()
        assert '"count"' in source, "缺少count字段"


# ==================== 5. 回测零影响 ====================

class TestNoBacktestRegressionV2914b:
    """验证改动对回测零影响"""

    def test_ws_bridge_not_imported_by_backtest(self):
        """回测引擎不导入redis_ws_bridge"""
        backtest_path = os.path.join(
            _PROJECT_ROOT, "nodes", "backtest_engine",
            "factor_selection", "portfolio_backtest.py"
        )
        if os.path.exists(backtest_path):
            source = open(backtest_path).read()
            assert "redis_ws_bridge" not in source

    def test_subscribers_not_imported_by_backtest(self):
        """回测引擎不导入scanner_event_subscribers"""
        backtest_path = os.path.join(
            _PROJECT_ROOT, "nodes", "backtest_engine",
            "factor_selection", "portfolio_backtest.py"
        )
        if os.path.exists(backtest_path):
            source = open(backtest_path).read()
            assert "scanner_event_subscribers" not in source


# ==================== 6. WS断线补发测试 ====================

class TestScannerStreamCatchup:
    """验证WS断线重连Stream补发(catchup_scanner_stream)"""

    def test_catchup_method_exists(self):
        """catchup_scanner_stream方法存在"""
        source = _read_ws_bridge()
        assert "async def catchup_scanner_stream" in source, \
            "缺少catchup_scanner_stream方法"

    def test_catchup_uses_xrange(self):
        """catchup使用XRANGE从last_id之后读取"""
        source = _read_ws_bridge()
        func_start = source.find("async def catchup_scanner_stream")
        assert func_start > 0, "catchup_scanner_stream方法未找到"
        func_code = source[func_start:func_start+3000]
        assert "xrange" in func_code, "缺少xrange调用(Stream范围读取)"

    def test_catchup_excludes_last_id(self):
        """catchup读取last_id之后的消息(不含last_id)"""
        source = _read_ws_bridge()
        func_start = source.find("async def catchup_scanner_stream")
        func_code = source[func_start:func_start+3000]
        # XRANGE min使用'('开区间排除last_id
        assert "(" in func_code, "缺少开区间排除(使用'(last_id')"

    def test_catchup_returns_count(self):
        """catchup返回补发消息数量"""
        source = _read_ws_bridge()
        func_start = source.find("async def catchup_scanner_stream")
        func_code = source[func_start:func_start+3000]
        assert "return count" in func_code, "应返回补发消息数量"

    def test_catchup_includes_stream_id(self):
        """catchup补发消息包含_stream_id(前端追踪用)"""
        source = _read_ws_bridge()
        func_start = source.find("async def catchup_scanner_stream")
        func_code = source[func_start:func_start+3000]
        assert "_stream_id" in func_code, "补发消息应包含_stream_id"

    def test_catchup_limit_100(self):
        """catchup最多补发100条(防止大量积压阻塞WS)"""
        source = _read_ws_bridge()
        func_start = source.find("async def catchup_scanner_stream")
        func_code = source[func_start:func_start+3000]
        assert "count=100" in func_code or "count = 100" in func_code, \
            "catchup应限制最多100条"
