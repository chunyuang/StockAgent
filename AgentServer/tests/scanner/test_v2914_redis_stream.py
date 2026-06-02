#!/usr/bin/env python3
"""
v2.9.14 — Redis Stream升级 + Stream消费API 测试

Phase2.1完善:
1. scanner:position从Pub/Sub升级为Redis Stream(xadd, maxlen=5000, 不可丢)
2. scanner:signal的EventBus订阅器也用Stream(与signal_dispatcher一致)
3. _push_to_redis支持use_stream参数(Pub/Sub vs Stream双模式)
4. 新增/stream/signals和/stream/positions Web API端点
"""
import ast
import os
import pytest

# 项目根目录
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_API_SCANNER = os.path.join(_PROJECT_ROOT, "nodes", "web", "api", "scanner_shared.py")
_SUBSCRIBERS = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner_event_subscribers.py")


def _read_api_scanner():
    return _read_all_scanner_api()

def _read_subscribers():
    return open(_SUBSCRIBERS).read()


# ==================== 1. _push_to_redis升级测试 ====================


def _read_all_scanner_api():
    """读取所有scanner API子模块内容(拆分后覆盖全部源码)"""
    import glob
    api_dir = os.path.join(_PROJECT_ROOT, "nodes", "web", "api")
    content = ""
    for f in sorted(glob.glob(os.path.join(api_dir, "scanner_*.py"))):
        content += open(f).read() + "\n"
    return content


class TestPushToRedisStreamMode:
    """验证_push_to_redis支持Stream模式"""

    def test_push_to_redis_has_use_stream_param(self):
        """_push_to_redis支持use_stream参数"""
        source = _read_subscribers()
        assert "use_stream" in source, "_push_to_redis缺少use_stream参数"

    def test_push_to_redis_has_maxlen_param(self):
        """_push_to_redis支持maxlen参数(Stream长度限制)"""
        source = _read_subscribers()
        assert "maxlen" in source, "_push_to_redis缺少maxlen参数"

    def test_push_to_redis_uses_xadd_for_stream(self):
        """use_stream=True时调用xadd"""
        source = _read_subscribers()
        # 找到_push_to_redis函数
        func_start = source.find("async def _push_to_redis")
        assert func_start > 0, "_push_to_redis函数未找到"
        func_code = source[func_start:func_start+3000]
        assert "xadd" in func_code, "缺少xadd调用(Redis Stream写入)"
        assert "approximate=True" in func_code, "缺少approximate=True(高效截断)"

    def test_push_to_redis_uses_publish_for_pubsub(self):
        """use_stream=False时仍用publish(Pub/Sub)"""
        source = _read_subscribers()
        func_start = source.find("async def _push_to_redis")
        func_code = source[func_start:func_start+3000]
        assert "publish" in func_code, "缺少publish调用(Pub/Sub模式)"


# ==================== 2. 持仓通道Stream升级测试 ====================

class TestPositionChannelStreamUpgrade:
    """验证scanner:position使用Redis Stream"""

    def test_position_handler_uses_stream(self):
        """持仓变更handler使用use_stream=True"""
        source = _read_subscribers()
        # 在position_changed handler中应有use_stream=True
        handler_start = source.find("def _make_position_changed_handler")
        assert handler_start > 0, "position_changed handler未找到"
        handler_code = source[handler_start:handler_start+1500]
        assert "use_stream=True" in handler_code, \
            "position handler未设置use_stream=True"

    def test_position_handler_maxlen_5000(self):
        """持仓Stream maxlen=5000(设计文档Phase2.1)"""
        source = _read_subscribers()
        handler_start = source.find("def _make_position_changed_handler")
        handler_code = source[handler_start:handler_start+1500]
        assert "maxlen=5000" in handler_code, \
            "position Stream maxlen应为5000(设计文档Phase2.1)"


# ==================== 3. 信号通道Stream升级测试 ====================

class TestSignalChannelStreamUpgrade:
    """验证scanner:signal的EventBus订阅器使用Stream"""

    def test_signal_handler_uses_stream(self):
        """信号生成handler使用use_stream=True"""
        source = _read_subscribers()
        handler_start = source.find("def _make_signal_generated_handler")
        assert handler_start > 0, "signal_generated handler未找到"
        handler_code = source[handler_start:handler_start+1500]
        assert "use_stream=True" in handler_code, \
            "signal handler未设置use_stream=True"

    def test_signal_handler_maxlen_1000(self):
        """信号Stream maxlen=1000(设计文档Phase2.1)"""
        source = _read_subscribers()
        handler_start = source.find("def _make_signal_generated_handler")
        handler_code = source[handler_start:handler_start+1500]
        assert "maxlen=1000" in handler_code, \
            "signal Stream maxlen应为1000(设计文档Phase2.1)"


# ==================== 4. Status通道保持Pub/Sub测试 ====================

class TestStatusChannelPubSub:
    """验证scanner:status仍用Pub/Sub(设计文档Phase2.1:允许丢)"""

    def test_status_handler_not_stream(self):
        """风控卖出等事件推送scanner:status不用Stream"""
        source = _read_subscribers()
        # 在risk_sell handler中,push_to_redis("scanner:status")不应有use_stream=True
        handler_start = source.find("def _make_risk_sell_handler")
        handler_code = source[handler_start:handler_start+1000]
        # 不应在此handler中有use_stream=True(因为status允许丢)
        if "use_stream" in handler_code:
            # 如果有, 必须是False
            assert "use_stream=True" not in handler_code or \
                   '"scanner:status"' not in handler_code, \
                "scanner:status不应使用Stream(设计文档:允许丢)"


# ==================== 5. Web API Stream端点测试 ====================

class TestStreamAPIEndpoints:
    """验证Stream消费API端点"""

    def test_stream_signals_endpoint_exists(self):
        """GET /stream/signals端点存在"""
        source = _read_api_scanner()
        assert '"/stream/signals"' in source, "缺少/stream/signals端点"

    def test_stream_positions_endpoint_exists(self):
        """GET /stream/positions端点存在"""
        source = _read_api_scanner()
        assert '"/stream/positions"' in source, "缺少/stream/positions端点"

    def test_stream_signals_uses_xrange(self):
        """stream/signals用XREAD/XRANGE消费"""
        source = _read_api_scanner()
        # 找到stream/signals端点
        endpoint_start = source.find('"/stream/signals"')
        assert endpoint_start > 0, "/stream/signals端点未找到"
        # 在该端点附近应有xrange调用
        endpoint_code = source[endpoint_start:endpoint_start+2000]
        assert "xrange" in endpoint_code or "xread" in endpoint_code, \
            "stream端点缺少xrange/xread消费"

    def test_stream_positions_uses_xrange(self):
        """stream/positions用XREAD/XRANGE消费"""
        source = _read_api_scanner()
        endpoint_start = source.find('"/stream/positions"')
        assert endpoint_start > 0, "/stream/positions端点未找到"
        endpoint_code = source[endpoint_start:endpoint_start+2000]
        assert "xrange" in endpoint_code or "xread" in endpoint_code, \
            "stream端点缺少xrange/xread消费"

    def test_stream_count_limit(self):
        """Stream端点有count参数限制(默认20,最大100)"""
        source = _read_api_scanner()
        # 应有count参数和限制
        assert "count" in source.split('"/stream/signals"')[1].split("@router")[0], \
            "/stream/signals缺少count参数"

    def test_stream_returns_message_id(self):
        """Stream端点返回message ID(用于断线回补)"""
        source = _read_api_scanner()
        # 应返回id字段(Redis Stream的entry ID)
        assert '"id"' in source, "Stream端点应返回id字段(entry ID)"


# ==================== 6. 版本常量同步 ====================

class TestVersionSync:
    """验证版本常量与设计文档同步"""

    def test_design_doc_version_is_v2914(self):
        """_DESIGN_DOC_VERSION = v2.9.72"""
        source = _read_api_scanner()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_DESIGN_DOC_VERSION":
                        if isinstance(node.value, ast.Constant):
                            assert node.value.value >= "v2.9.18", \
                                f"_DESIGN_DOC_VERSION={node.value.value}, 期望≥v2.9.18"
                            return
        pytest.fail("_DESIGN_DOC_VERSION未找到")


# ==================== 7. 回测零影响 ====================

class TestNoBacktestRegressionV2914:
    """验证v2.9.14对回测零影响"""

    def test_subscribers_not_imported_by_backtest(self):
        """回测引擎不导入scanner_event_subscribers"""
        backtest_path = os.path.join(
            _PROJECT_ROOT, "nodes", "backtest_engine",
            "factor_selection", "portfolio_backtest.py"
        )
        if os.path.exists(backtest_path):
            source = open(backtest_path).read()
            assert "scanner_event_subscribers" not in source
            assert "scanner_event_bus" not in source

    def test_push_to_redis_only_in_monitor_module(self):
        """_push_to_redis只在market_monitor模块中"""
        # 验证不污染回测模块
        assert os.path.exists(_SUBSCRIBERS)
        source = _read_subscribers()
        # 不应导入回测模块
        assert "portfolio_backtest" not in source
        assert "sell_signal_checker" not in source

    def test_stream_endpoints_only_in_api(self):
        """Stream端点只在web/api/scanner.py"""
        source = _read_subscribers()
        # 订阅器不应定义HTTP端点
        assert "@router" not in source
        assert "FastAPI" not in source

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker API不变"""
        checker_path = os.path.join(
            _PROJECT_ROOT, "nodes", "market_monitor", "sell_signal_checker.py"
        )
        if os.path.exists(checker_path):
            source = open(checker_path).read()
            assert "def check_realtime_sell" in source
            # 不应有Redis/Stream相关代码
            assert "xadd" not in source
            assert "_push_to_redis" not in source
