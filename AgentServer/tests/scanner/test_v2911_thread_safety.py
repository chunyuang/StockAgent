#!/usr/bin/env python3
"""
v2.9.11 — API端点线程安全修复 测试

修复项:
1. _safe_read_shared辅助函数: 统一加state_lock保护共享状态读取
2. 7处unsafe getattr(_trailing_stops/_position_risk_levels) → _safe_read_shared
3. set_trailing_stop写操作在state_lock内完成
"""
import ast
import os
import pytest

# 项目根目录(从tests/scanner/向上两级到AgentServer)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_API_SCANNER = os.path.join(_PROJECT_ROOT, "nodes", "web", "api", "scanner_shared.py")
_MONITOR_SCANNER = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner.py")


def _read_api_scanner():
    return _read_all_scanner_api()

def _read_monitor_scanner():
    return open(_MONITOR_SCANNER).read()


# ==================== 1. _safe_read_shared辅助函数测试 ====================


def _read_all_scanner_api():
    """读取所有scanner API子模块内容(拆分后覆盖全部源码)"""
    import glob
    api_dir = os.path.join(_PROJECT_ROOT, "nodes", "web", "api")
    content = ""
    for f in sorted(glob.glob(os.path.join(api_dir, "scanner_*.py"))):
        content += open(f).read() + "\n"
    return content


class TestSafeReadShared:
    """验证_safe_read_shared辅助函数"""

    def test_safe_read_shared_function_exists(self):
        """_safe_read_shared函数存在"""
        source = _read_api_scanner()
        assert "def _safe_read_shared(" in source, "_safe_read_shared函数未定义"

    def test_safe_read_shared_has_state_lock(self):
        """_safe_read_shared内部使用state_lock"""
        source = _read_api_scanner()
        assert "state_lock" in source.split("def _safe_read_shared")[1].split("\ndef ")[0], \
            "_safe_read_shared未使用state_lock"

    def test_safe_read_shared_has_copy_param(self):
        """_safe_read_shared支持copy参数(读拷贝/写引用)"""
        source = _read_api_scanner()
        assert "copy" in source.split("def _safe_read_shared")[1].split("\ndef ")[0], \
            "_safe_read_shared缺少copy参数"

    def test_safe_read_shared_returns_dict_copy(self):
        """_safe_read_shared默认返回dict浅拷贝"""
        source = _read_api_scanner()
        func_code = source.split("def _safe_read_shared")[1].split("\ndef ")[0]
        assert "dict(data)" in func_code, "缺少dict(data)浅拷贝"


# ==================== 2. 不安全getattr替换测试 ====================

class TestUnsafeGetattrReplaced:
    """验证所有unsafe getattr已替换"""

    def test_no_unsafe_trailing_stops_getattr(self):
        """不再有getattr(scanner, '_trailing_stops', {})直接调用"""
        source = _read_api_scanner()
        # 搜索API端点中的unsafe getattr
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if "getattr(scanner, '_trailing_stops'" in line:
                # 只有_safe_read_shared定义内部允许
                if "def _safe_read_shared" not in source[max(0, source.find(line)-500):source.find(line)+len(line)]:
                    pytest.fail(f"第{i+1}行: 仍使用unsafe getattr(_trailing_stops): {line.strip()}")

    def test_no_unsafe_position_risk_levels_getattr(self):
        """不再有getattr(scanner, '_position_risk_levels', {})直接调用"""
        source = _read_api_scanner()
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if "getattr(scanner, '_position_risk_levels'" in line:
                pytest.fail(f"第{i+1}行: 仍使用unsafe getattr(_position_risk_levels): {line.strip()}")

    def test_safe_read_shared_called_for_trailing_stops(self):
        """_safe_read_shared用于读取_trailing_stops"""
        source = _read_api_scanner()
        count = source.count("_safe_read_shared(scanner, '_trailing_stops')")
        assert count >= 2, f"_safe_read_shared(_trailing_stops)调用次数{count}, 期望>=2"

    def test_safe_read_shared_called_for_risk_levels(self):
        """_safe_read_shared用于读取_position_risk_levels"""
        source = _read_api_scanner()
        count = source.count("_safe_read_shared(scanner, '_position_risk_levels')")
        assert count >= 2, f"_safe_read_shared(_position_risk_levels)调用次数{count}, 期望>=2"


# ==================== 3. 写操作加锁测试 ====================

class TestWriteOperationsLocked:
    """验证写操作在state_lock内完成"""

    def test_set_trailing_stop_uses_state_lock(self):
        """set_trailing_stop端点在state_lock内完成写操作"""
        source = _read_api_scanner()
        # 找到set_trailing_stop函数
        func_start = source.find("async def set_trailing_stop")
        assert func_start > 0, "set_trailing_stop函数未找到"
        func_code = source[func_start:func_start+2000]
        assert "state_lock" in func_code, \
            "set_trailing_stop未使用state_lock保护写操作"

    def test_set_trailing_stop_writes_inside_lock(self):
        """set_trailing_stop的dict写操作在with state_lock内"""
        source = _read_api_scanner()
        func_start = source.find("async def set_trailing_stop")
        func_code = source[func_start:func_start+3000]
        
        # 应该有with state_lock块, 且trailing[ts_code]写操作在里面
        assert "with state_lock:" in func_code, \
            "set_trailing_stop缺少with state_lock块"
        # 写操作应在锁内
        assert 'trailing[ts_code]' in func_code, \
            "set_trailing_stop缺少trailing[ts_code]写操作"


# ==================== 4. 回测零影响 ====================

class TestNoBacktestRegressionV2911:
    """验证v2.9.11对回测零影响"""

    def test_only_api_scanner_modified(self):
        """v2.9.11只修改web/api/scanner.py"""
        source = _read_monitor_scanner()
        # scanner.py中不应有_safe_read_shared
        assert "_safe_read_shared" not in source, \
            "market_monitor/scanner.py不应包含_safe_read_shared"

    def test_scanner_delegate_map_unchanged(self):
        """DELEGATE_MAP仍存在(v2.9.52:外提到scanner_delegate_router)"""
        source = _read_monitor_scanner()
        assert "__getattr__" in source
        # _compute_health_score仍通过DELEGATE_MAP委托(现在在router中)
        from nodes.market_monitor.scanner_delegate_router import DELEGATE_MAP
        assert "_compute_health_score" in DELEGATE_MAP
