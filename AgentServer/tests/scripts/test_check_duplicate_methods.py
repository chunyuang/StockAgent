"""
Unit tests for scripts/check_duplicate_methods.py

测试同名方法 lint 脚本的正确性:
- 能识别普通同名方法重复
- 不误报 @property + @property.setter
- 不误报 @overload 装饰的重载
- 跨类的同名方法不算重复
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "scripts", "check_duplicate_methods.py"
)
SCRIPT = os.path.abspath(SCRIPT)


def run_lint(tmp_root: str) -> tuple[int, str]:
    """运行 lint 脚本，返回 (exit_code, stdout)"""
    proc = subprocess.run(
        [sys.executable, SCRIPT, tmp_root],
        capture_output=True, text=True, timeout=30,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_no_duplicate_returns_zero(tmp_path: Path) -> None:
    """无重复方法 → exit 0"""
    (tmp_path / "clean.py").write_text("""
class Foo:
    def bar(self):
        pass
    def baz(self):
        pass
""")
    code, out = run_lint(str(tmp_path))
    assert code == 0, f"应该 exit 0, 实际 {code}\n{out}"
    assert "没有发现" in out


def test_duplicate_method_detected(tmp_path: Path) -> None:
    """同名方法重复 → exit 1 + 报告"""
    (tmp_path / "dup.py").write_text("""
class Foo:
    def bar(self):
        return 1
    def bar(self):
        return 2
""")
    code, out = run_lint(str(tmp_path))
    assert code == 1, f"应该 exit 1, 实际 {code}\n{out}"
    assert "Foo.bar" in out


def test_property_setter_not_flagged(tmp_path: Path) -> None:
    """@property + @property.setter 是合法重复 → 不报告"""
    (tmp_path / "prop.py").write_text("""
class Foo:
    @property
    def value(self):
        return self._x
    @value.setter
    def value(self, v):
        self._x = v
""")
    code, out = run_lint(str(tmp_path))
    assert code == 0, f"property setter 不应被识别为重复\n{out}"


def test_property_deleter_not_flagged(tmp_path: Path) -> None:
    """@property + setter + deleter 都是合法的 → 不报告"""
    (tmp_path / "prop2.py").write_text("""
class Foo:
    @property
    def value(self):
        return self._x
    @value.setter
    def value(self, v):
        self._x = v
    @value.deleter
    def value(self):
        del self._x
""")
    code, out = run_lint(str(tmp_path))
    assert code == 0, f"property deleter 不应被识别为重复\n{out}"


def test_overload_not_flagged(tmp_path: Path) -> None:
    """@overload 装饰的重载 → 不报告"""
    (tmp_path / "overload.py").write_text("""
from typing import overload

class Foo:
    @overload
    def bar(self, x: int) -> int: ...
    @overload
    def bar(self, x: str) -> str: ...
    def bar(self, x):
        return x
""")
    code, out = run_lint(str(tmp_path))
    assert code == 0, f"@overload 不应被识别为重复\n{out}"


def test_different_class_same_method_ok(tmp_path: Path) -> None:
    """不同类里同名方法 → 不报告(类作用域不同)"""
    (tmp_path / "two.py").write_text("""
class Foo:
    def bar(self):
        return 1
class Baz:
    def bar(self):
        return 2
""")
    code, out = run_lint(str(tmp_path))
    assert code == 0, f"不同类的同名方法不应报告\n{out}"


def test_async_method_duplicate_detected(tmp_path: Path) -> None:
    """async 方法重复也要识别(还原 P0 事故场景: load_timeline 是 async)"""
    (tmp_path / "async_dup.py").write_text("""
class Foo:
    async def bar(self):
        return 1
    async def bar(self):
        return 2
""")
    code, out = run_lint(str(tmp_path))
    assert code == 1, f"async 同名方法应被识别\n{out}"
    assert "Foo.bar" in out


def test_runtime_persistence_clean() -> None:
    """实战回归: 修复后的 runtime_persistence.py 应该 lint 通过"""
    target = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "nodes", "market_monitor"
    )
    target = os.path.abspath(target)
    code, out = run_lint(target)
    assert code == 0, f"runtime_persistence 应已修复, 仍有重复:\n{out}"
