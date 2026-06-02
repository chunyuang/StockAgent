"""测试辅助: 合并读取scanner.py及其mixin文件源码

v2.9.67将scanner.py拆分为多个mixin文件:
- scanner_initializer.py (初始化)
- scan_loop_runner.py (扫描循环)
- risk_loop_runner.py (风控循环)
- market_phase.py (市场阶段)

测试中搜索方法定义/源码内容时，需要同时搜索所有mixin文件。
"""

import os

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCANNER_DIR = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor")

# scanner.py及其mixin文件
SCANNER_FILES = [
    os.path.join(_SCANNER_DIR, "scanner.py"),
    os.path.join(_SCANNER_DIR, "scanner_initializer.py"),
    os.path.join(_SCANNER_DIR, "scan_loop_runner.py"),
    os.path.join(_SCANNER_DIR, "risk_loop_runner.py"),
    os.path.join(_SCANNER_DIR, "market_phase.py"),
]

SCANNER_PATH = SCANNER_FILES[0]  # 主文件，保持向后兼容


def read_scanner_source() -> str:
    """只读取scanner.py源码"""
    with open(SCANNER_PATH) as f:
        return f.read()


def read_all_scanner_sources() -> str:
    """合并读取scanner.py及所有mixin文件源码"""
    parts = []
    for path in SCANNER_FILES:
        if os.path.exists(path):
            with open(path) as f:
                parts.append(f.read())
    return "\n".join(parts)


def parse_all_scanner_sources():
    """解析所有scanner源码为AST节点列表(每个文件独立解析)"""
    import ast
    results = []
    for path in SCANNER_FILES:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            source = f.read()
        try:
            tree = ast.parse(source)
            results.append((tree, source, path))
        except SyntaxError:
            pass
    return results


def find_method_ast(method_name: str, method_type: str = "any"):
    """在所有scanner源码中查找方法定义的AST节点+源码
    
    Args:
        method_name: 方法名
        method_type: 'any'|'async'|'sync'
    Returns:
        (ast_node, source_code, file_path) 或 (None, None, None)
    """
    import ast
    for tree, source, path in parse_all_scanner_sources():
        for node in ast.walk(tree):
            is_target = False
            if method_type == 'async' and isinstance(node, ast.AsyncFunctionDef) and node.name == method_name:
                is_target = True
            elif method_type == 'sync' and isinstance(node, ast.FunctionDef) and node.name == method_name:
                is_target = True
            elif method_type == 'any':
                if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name):
                    is_target = True
            if is_target:
                return node, source, path
    return None, None, None


def find_method_in_scanner_sources(method_name: str) -> tuple:
    """在scanner及其mixin文件中查找方法定义

    Returns: (source_code, file_path) 或 (None, None)
    """
    for path in SCANNER_FILES:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            source = f.read()
        # 检查方法定义 (async def 或 def)
        if f"def {method_name}(" in source:
            return source, path
    return None, None


def scanner_line_count() -> int:
    """scanner.py主文件行数"""
    with open(SCANNER_PATH) as f:
        return sum(1 for _ in f)


def scanner_total_line_count() -> int:
    """scanner.py + 所有mixin文件总行数"""
    total = 0
    for path in SCANNER_FILES:
        if os.path.exists(path):
            with open(path) as f:
                total += sum(1 for _ in f)
    return total
