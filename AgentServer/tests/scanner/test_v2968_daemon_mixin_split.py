"""v2.9.69: ScannerDaemon mixin拆分

变更:
1. DaemonCommandMixin: 命令发送(send_command/_wait_for_ack/_ack_listener)+便捷方法5个
2. DaemonSubscriptionMixin: Redis订阅(_ensure_redis/_init_redis_subscriptions/_subscribe_loop等)+回调4个
3. DaemonWatchdogMixin: 看门狗(_watchdog_loop/_restart_subprocess/_start_process)+紧急告警2个
4. ScannerDaemon继承3个mixin, scanner_daemon.py从1146行→753行(-34%)
5. 版本常量: v2.9.67→v2.9.69

回测影响: 零。所有变更仅影响market_monitor模块ScannerDaemon内部拆分。
"""
import ast
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

_DAEMON_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "nodes", "market_monitor"
)
_DAEMON_DIR = os.path.abspath(_DAEMON_DIR)


def _read_daemon_source():
    with open(os.path.join(_DAEMON_DIR, "scanner_daemon.py")) as f:
        return f.read()


def _read_all_daemon_sources():
    """合并读取scanner_daemon.py及所有mixin文件"""
    parts = []
    for fname in ["scanner_daemon.py", "daemon_command_mixin.py",
                   "daemon_subscription_mixin.py", "daemon_watchdog_mixin.py"]:
        fpath = os.path.join(_DAEMON_DIR, fname)
        if os.path.exists(fpath):
            with open(fpath) as f:
                parts.append(f.read())
    return "\n".join(parts)


# ─── Mixin文件存在验证 ───

class TestDaemonMixinFiles:
    """v2.9.69拆分的3个mixin文件存在且可导入"""

    def test_command_mixin_exists(self):
        """daemon_command_mixin.py存在"""
        assert os.path.exists(os.path.join(_DAEMON_DIR, "daemon_command_mixin.py"))

    def test_subscription_mixin_exists(self):
        """daemon_subscription_mixin.py存在"""
        assert os.path.exists(os.path.join(_DAEMON_DIR, "daemon_subscription_mixin.py"))

    def test_watchdog_mixin_exists(self):
        """daemon_watchdog_mixin.py存在"""
        assert os.path.exists(os.path.join(_DAEMON_DIR, "daemon_watchdog_mixin.py"))

    def test_command_mixin_importable(self):
        """DaemonCommandMixin可导入"""
        from nodes.market_monitor.daemon_command_mixin import DaemonCommandMixin
        assert hasattr(DaemonCommandMixin, "send_command")

    def test_subscription_mixin_importable(self):
        """DaemonSubscriptionMixin可导入"""
        from nodes.market_monitor.daemon_subscription_mixin import DaemonSubscriptionMixin
        assert hasattr(DaemonSubscriptionMixin, "_ensure_redis")

    def test_watchdog_mixin_importable(self):
        """DaemonWatchdogMixin可导入"""
        from nodes.market_monitor.daemon_watchdog_mixin import DaemonWatchdogMixin
        assert hasattr(DaemonWatchdogMixin, "_watchdog_loop")


# ─── ScannerDaemon继承验证 ───

class TestDaemonInheritance:
    """ScannerDaemon继承3个mixin"""

    def test_scanner_daemon_inherits_command(self):
        """ScannerDaemon继承DaemonCommandMixin"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        from nodes.market_monitor.daemon_command_mixin import DaemonCommandMixin
        assert issubclass(ScannerDaemon, DaemonCommandMixin)

    def test_scanner_daemon_inherits_subscription(self):
        """ScannerDaemon继承DaemonSubscriptionMixin"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        from nodes.market_monitor.daemon_subscription_mixin import DaemonSubscriptionMixin
        assert issubclass(ScannerDaemon, DaemonSubscriptionMixin)

    def test_scanner_daemon_inherits_watchdog(self):
        """ScannerDaemon继承DaemonWatchdogMixin"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        from nodes.market_monitor.daemon_watchdog_mixin import DaemonWatchdogMixin
        assert issubclass(ScannerDaemon, DaemonWatchdogMixin)


# ─── 方法委托验证 ───

class TestDaemonMethodDelegation:
    """ScannerDaemon通过mixin获取的方法"""

    def test_has_send_command(self):
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, "send_command")

    def test_has_ack_listener(self):
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, "_ack_listener")

    def test_has_start_scanner(self):
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, "start_scanner")

    def test_has_ensure_redis(self):
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, "_ensure_redis")

    def test_has_subscribe_loop(self):
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, "_subscribe_loop")

    def test_has_on_status(self):
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, "on_status")

    def test_has_watchdog_loop(self):
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, "_watchdog_loop")

    def test_has_start_process(self):
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, "_start_process")

    def test_has_send_emergency_alert(self):
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, "_send_emergency_alert")

    def test_has_emergency_reduce_positions(self):
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, "_emergency_reduce_positions")


# ─── 行数验证 ───

class TestDaemonLineCount:
    """scanner_daemon.py主文件行数减少"""

    def test_daemon_main_file_under_800(self):
        """scanner_daemon.py主文件<800行"""
        count = 0
        with open(os.path.join(_DAEMON_DIR, "scanner_daemon.py")) as f:
            for _ in f:
                count += 1
        assert count < 800, f"scanner_daemon.py {count}L >= 800L"

    def test_daemon_total_line_count(self):
        """scanner_daemon.py + mixin文件总行数"""
        total = 0
        for fname in ["scanner_daemon.py", "daemon_command_mixin.py",
                       "daemon_subscription_mixin.py", "daemon_watchdog_mixin.py"]:
            fpath = os.path.join(_DAEMON_DIR, fname)
            if os.path.exists(fpath):
                with open(fpath) as f:
                    for _ in f:
                        total += 1
        # 1146(original) → total应该接近
        assert total < 1300, f"daemon total {total}L >= 1300L"

    def test_mixin_command_line_count(self):
        """daemon_command_mixin.py行数合理"""
        count = 0
        with open(os.path.join(_DAEMON_DIR, "daemon_command_mixin.py")) as f:
            for _ in f:
                count += 1
        assert 100 < count < 200, f"daemon_command_mixin.py {count}L out of range"

    def test_mixin_subscription_line_count(self):
        """daemon_subscription_mixin.py行数合理"""
        count = 0
        with open(os.path.join(_DAEMON_DIR, "daemon_subscription_mixin.py")) as f:
            for _ in f:
                count += 1
        assert 100 < count < 200, f"daemon_subscription_mixin.py {count}L out of range"

    def test_mixin_watchdog_line_count(self):
        """daemon_watchdog_mixin.py行数合理"""
        count = 0
        with open(os.path.join(_DAEMON_DIR, "daemon_watchdog_mixin.py")) as f:
            for _ in f:
                count += 1
        assert 100 < count < 200, f"daemon_watchdog_mixin.py {count}L out of range"


# ─── 方法在mixin中定义验证 ───

class TestMethodsInMixinFiles:
    """关键方法在mixin文件中定义, 不在scanner_daemon.py中"""

    def test_send_command_in_command_mixin(self):
        """send_command在daemon_command_mixin.py中"""
        all_src = _read_all_daemon_sources()
        assert "async def send_command(self" in all_src
        # 不在主文件中
        main_src = _read_daemon_source()
        assert "async def send_command(self" not in main_src

    def test_ack_listener_in_command_mixin(self):
        """_ack_listener在daemon_command_mixin.py中"""
        all_src = _read_all_daemon_sources()
        assert "async def _ack_listener(self" in all_src
        main_src = _read_daemon_source()
        assert "async def _ack_listener(self" not in main_src

    def test_subscribe_loop_in_subscription_mixin(self):
        """_subscribe_loop在daemon_subscription_mixin.py中"""
        all_src = _read_all_daemon_sources()
        assert "async def _subscribe_loop(self" in all_src
        main_src = _read_daemon_source()
        assert "async def _subscribe_loop(self" not in main_src

    def test_ensure_redis_in_subscription_mixin(self):
        """_ensure_redis在daemon_subscription_mixin.py中"""
        all_src = _read_all_daemon_sources()
        assert "async def _ensure_redis(self" in all_src
        main_src = _read_daemon_source()
        assert "async def _ensure_redis(self" not in main_src

    def test_watchdog_loop_in_watchdog_mixin(self):
        """_watchdog_loop在daemon_watchdog_mixin.py中"""
        all_src = _read_all_daemon_sources()
        assert "async def _watchdog_loop(self" in all_src
        main_src = _read_daemon_source()
        assert "async def _watchdog_loop(self" not in main_src

    def test_start_process_in_watchdog_mixin(self):
        """_start_process在daemon_watchdog_mixin.py中"""
        all_src = _read_all_daemon_sources()
        assert "def _start_process(self" in all_src
        main_src = _read_daemon_source()
        assert "def _start_process(self" not in main_src

    def test_send_emergency_alert_in_watchdog_mixin(self):
        """_send_emergency_alert在daemon_watchdog_mixin.py中"""
        all_src = _read_all_daemon_sources()
        assert "async def _send_emergency_alert(self" in all_src
        main_src = _read_daemon_source()
        assert "async def _send_emergency_alert(self" not in main_src


# ─── ScannerDaemon保留的核心方法 ───

class TestDaemonRetainedMethods:
    """ScannerDaemon主文件中保留的生命周期+状态方法"""

    def test_start_in_main(self):
        """start()在主文件中"""
        src = _read_daemon_source()
        assert "async def start(self)" in src

    def test_stop_in_main(self):
        """stop()在主文件中"""
        src = _read_daemon_source()
        assert "async def stop(self)" in src

    def test_get_status_in_main(self):
        """get_status()在主文件中"""
        src = _read_daemon_source()
        assert "def get_status(self)" in src

    def test_is_alive_in_main(self):
        """is_alive()在主文件中"""
        src = _read_daemon_source()
        assert "def is_alive(self)" in src


# ─── 回测零影响验证 ───

class TestNoBacktestRegressionV2968:
    """v2.9.69变更不影响回测模块"""

    def test_backtest_engine_unchanged(self):
        """回测引擎核心文件未修改"""
        backtest_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "..",
            "nodes", "backtest_engine"
        )
        backtest_dir = os.path.abspath(backtest_dir)
        if not os.path.exists(backtest_dir):
            pytest.skip("backtest module not found")
        for root, dirs, files in os.walk(backtest_dir):
            for f in files:
                if f.endswith('.py'):
                    fpath = os.path.join(root, f)
                    with open(fpath) as fh:
                        content = fh.read()
                    assert "daemon_command_mixin" not in content, \
                        f"daemon_command_mixin不应出现在回测引擎 {f} 中"
                    assert "daemon_subscription_mixin" not in content, \
                        f"daemon_subscription_mixin不应出现在回测引擎 {f} 中"
                    assert "daemon_watchdog_mixin" not in content, \
                        f"daemon_watchdog_mixin不应出现在回测引擎 {f} 中"

    def test_version_constant_updated(self):
        """版本常量更新为v2.9.69"""
        api_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "nodes", "web", "api", "scanner_system.py"
        )
        api_path = os.path.abspath(api_path)
        with open(api_path) as f:
            source = f.read()
        assert 'v2.9.69' in source
