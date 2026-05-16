#!/usr/bin/env python3
"""
策略参数同步脚本：后端 strategy_defaults.py → 前端 strategyDefaults.ts

读取后端 Python 的 GLOBAL_RISK + STRATEGY_CONFIGS，
生成前端 TypeScript 文件，确保前后端默认值一致。

用法: cd AgentServer && python3 scripts/sync_strategy_defaults.py
"""

import os
import sys

# 确保能 import strategy_defaults
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK, STRATEGY_CONFIGS


def python_val_to_ts(val):
    """Python 值转 TypeScript 字面量"""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        # 保留原始精度
        if isinstance(val, float):
            s = repr(val)
            # Python repr 可能产生 0.1 → 0.1, 0.001 → 0.001
            return s
        return str(val)
    if isinstance(val, str):
        return f"'{val}'"
    raise ValueError(f"Unsupported type: {type(val)} for {val}")


def gen_object_ts(data: dict, indent: int = 2) -> str:
    """递归生成 TypeScript 对象字面量"""
    prefix = " " * indent
    lines = []
    for k, v in data.items():
        if isinstance(v, dict):
            inner = gen_object_ts(v, indent + 2)
            lines.append(f"{prefix}{k}: {inner},")
        else:
            lines.append(f"{prefix}{k}: {python_val_to_ts(v)},")
    inner_text = "\n".join(lines)
    return f"{{\n{inner_text}\n{' ' * (indent - 2)}}}"


def main():
    # 生成前端 strategyDefaults.ts
    ts_content = f"""/**
 * 策略参数单一来源（前端版本）
 * 
 * ⚠️ 此文件由 scripts/sync_strategy_defaults.py 自动生成！
 * 请勿手动修改！修改策略参数请改后端 strategy_defaults.py，然后重新运行同步脚本。
 * 
 * 同步命令: cd AgentServer && python3 scripts/sync_strategy_defaults.py
 */

// 全局风控参数 — 与后端 strategy_defaults.py GLOBAL_RISK 完全一致
export const GLOBAL_RISK = {gen_object_ts(GLOBAL_RISK)}

// 策略配置 — 与后端 strategy_defaults.py STRATEGY_CONFIGS 完全对齐
export const STRATEGY_CONFIGS = {gen_object_ts(STRATEGY_CONFIGS)}
"""

    # 写入前端文件
    frontend_path = os.path.join(
        os.path.dirname(__file__),
        '..', '..', 'frontend', 'src', 'config', 'strategyDefaults.ts'
    )
    frontend_path = os.path.normpath(frontend_path)

    with open(frontend_path, 'w', encoding='utf-8') as f:
        f.write(ts_content)

    print(f"✅ 已同步到: {frontend_path}")
    print(f"   GLOBAL_RISK.stop_loss_pct = {GLOBAL_RISK['stop_loss_pct']}")
    print(f"   GLOBAL_RISK.take_profit_pct = {GLOBAL_RISK['take_profit_pct']}")
    print(f"   策略数量: {len(STRATEGY_CONFIGS)}")


if __name__ == "__main__":
    main()
