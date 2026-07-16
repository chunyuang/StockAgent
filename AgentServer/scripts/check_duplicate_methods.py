#!/usr/bin/env python3
"""
同名方法 lint (v2.9.93)

检查所有 .py 文件中是否存在「同一个类里定义了多个同名方法」的情况。
Python 后定义的方法会覆盖前定义的，但通常这是 bug — 早期修复白白被新加的旧逻辑盖过。

【触发原因】
2026-06-15 P0 事故:
  AgentServer/nodes/market_monitor/runtime_persistence.py 同一类里有 2 个 load_timeline:
  - L389 是 v2.9.92f 修过的正确版本(只读今天)
  - L603 是旧版(回退到历史日, bug)
  Python 后定义覆盖前定义 → v2.9.92f 修复白修，导致今早扫描器把 6/9 timeline 复制到 6/15

运行:
  python3 scripts/check_duplicate_methods.py [扫描根目录]
  默认扫描 AgentServer/ 全目录(排除 venv / __pycache__ / tests)

退出码:
  0 = 没有重复定义
  1 = 发现重复定义
"""
import ast
import os
import sys
from collections import defaultdict
from pathlib import Path


# 排除目录(子串匹配)
EXCLUDE_DIRS = {
    "venv", "__pycache__", ".git", "node_modules", ".pytest_cache",
    "tests/snapshots", "scripts/archive",
}

# 允许的重复(白名单) — 形如 "ClassName.method_name" 或 "module.path:ClassName.method_name"
# 例如重载装饰器、Protocol 占位等合法重复
ALLOW_DUPLICATES: set[str] = set()


def find_duplicate_methods(file_path: str) -> list[dict]:
    """扫描单个文件，返回所有重复方法定义"""
    try:
        source = Path(file_path).read_text(encoding="utf-8")
    except Exception:
        return []

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    duplicates = []

    # 遍历所有类
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # class 体内每个 def / async def，统计同名次数
        method_locs: dict[str, list[int]] = defaultdict(list)
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 跳过 @overload / @typing.overload 装饰的
                decorators_full = []
                decorators = set()
                for d in item.decorator_list:
                    if isinstance(d, ast.Name):
                        decorators.add(d.id)
                        decorators_full.append(d.id)
                    elif isinstance(d, ast.Attribute):
                        decorators.add(d.attr)
                        # property setter/getter/deleter 是合法重复：
                        # @propname.setter / @propname.deleter
                        if d.attr in ("setter", "deleter", "getter"):
                            decorators_full.append(f"{getattr(d.value, 'id', '')}.{d.attr}")
                if "overload" in decorators:
                    continue
                # property setter/deleter 不算重复
                if any(".setter" in s or ".deleter" in s or ".getter" in s for s in decorators_full):
                    continue
                method_locs[item.name].append(item.lineno)

        for name, lines in method_locs.items():
            if len(lines) <= 1:
                continue
            key = f"{node.name}.{name}"
            if key in ALLOW_DUPLICATES:
                continue
            duplicates.append({
                "file": file_path,
                "class": node.name,
                "method": name,
                "lines": lines,
            })

    return duplicates


def should_skip(path: str) -> bool:
    return any(part in EXCLUDE_DIRS for part in Path(path).parts)


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), ".."
    )
    root = os.path.abspath(root)

    all_duplicates: list[dict] = []
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # 原地修改 dirnames 跳过排除目录
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            if should_skip(full):
                continue
            file_count += 1
            dups = find_duplicate_methods(full)
            all_duplicates.extend(dups)

    print(f"扫描 {file_count} 个 .py 文件")

    if not all_duplicates:
        print("✅ 没有发现同一类里同名方法重复定义")
        return 0

    print(f"\n❌ 发现 {len(all_duplicates)} 处同名方法重复定义:\n")
    for d in all_duplicates:
        rel = os.path.relpath(d["file"], root)
        lines_str = ", ".join(f"L{ln}" for ln in d["lines"])
        print(f"  {rel}")
        print(f"    class {d['class']}.{d['method']}  →  定义于 {lines_str}")
        print("    后定义会覆盖前定义。如确为意图，请加到 ALLOW_DUPLICATES 白名单。")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
