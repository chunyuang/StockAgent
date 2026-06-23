#!/usr/bin/env python3
"""
template_render_guard.py
========================
模板渲染一致性守卫 (v2.9.99 新增,夜间审查/重构后必跑)

背景: 2026-06-22 夜间 cron "瘦壳重构"(commit 4ae4592e) 把 MarketMonitorView.vue 的
state/computed/method 全部搬到 useViewHelpers.ts, 但漏了三个关键步骤:
  1. .vue 没有 import useViewHelpers
  2. .vue 没有调用 useViewHelpers({...})
  3. template 里相关的 <div class="sig-hour-header"> / <div class="closed-trades-section">
     / pos-buy-date 等渲染块全被删除
导致用户实际看到的页面回到瘦壳前状态, v17/v18/v19 三天工作的 UI 全部丢失。

本脚本扫描 MarketMonitorView.vue, 验证:
  - 所有 useViewHelpers.ts 返回的 ref/method 都在 .vue 中被解构或在 template 中使用
  - 关键 CSS class (跟踪的 UI 块) 仍在 template 中
  - 如果 useViewHelpers.ts 存在, .vue 必须 import 并调用它

exit 0 = 一致
exit 1 = 发现不一致 (P0, 用户级回归)
"""
import re
import sys
from pathlib import Path

ROOT = Path("/root/.openclaw/workspace/StockAgent/frontend/src/views/monitor")
VUE = ROOT / "MarketMonitorView.vue"
HELPERS = ROOT / "useViewHelpers.ts"

# 跟踪的关键 UI 块 (class 名 -> 描述 + 对应版本)
TRACKED_BLOCKS = [
    ("sig-hour-header", "v17 信号小时分组折叠"),
    ("closed-trades-section", "v19 今日已平仓面板"),
    ("pos-buy-date", "v18 持仓买入日期标签"),
    ("scan-time", "v16 信号扫描时间"),
]

# 重要辅助函数 (必须在 template 中被引用或在 script 中被解构)
TRACKED_FUNCTIONS = [
    "signalsByHour", "signalHourCollapse", "toggleSignalHour",
    "todayClosedTrades", "closedTradesProfitTotal", "closedTradesCollapsed",
    "formatBuyDateDisplay", "formatBuyDateShort", "positionActionLabel",
    "formatPositionTime",
]


def main():
    issues = []

    if not VUE.exists():
        print(f"❌ {VUE} 不存在")
        return 1

    vue_src = VUE.read_text(encoding="utf-8")

    # 1. 检查 useViewHelpers 是否被使用 (如果该文件存在)
    if HELPERS.exists():
        helpers_src = HELPERS.read_text(encoding="utf-8")
        if "useViewHelpers" not in vue_src:
            issues.append(
                f"P0 {VUE.name} 没有 import/use useViewHelpers, 但 {HELPERS.name} 存在 "
                f"(可能是夜间重构搬运了 logic 但忘记接通组件)"
            )
        else:
            # 进一步: 必须既 import 又调用
            has_import = bool(re.search(r"import\s*\{[^}]*useViewHelpers[^}]*\}\s*from", vue_src))
            has_call = "useViewHelpers(" in vue_src
            if not has_import:
                issues.append(f"P0 {VUE.name} 没有 import useViewHelpers")
            if not has_call:
                issues.append(f"P0 {VUE.name} 没有调用 useViewHelpers({{...}})")

        # 检查 helpers.ts export 的关键 ref 是否都被 .vue 解构使用
        # 看 return { ... } 块
        ret_match = re.search(r"return\s*\{([^}]+)\}", helpers_src, re.S)
        if ret_match:
            exported = re.findall(r"\b(\w+)\b", ret_match.group(1))
            exported = [e for e in exported if not e[0].isupper() and len(e) > 2]  # 过滤类型名
            for fn in exported:
                if fn in TRACKED_FUNCTIONS:
                    if fn not in vue_src:
                        issues.append(
                            f"P0 {HELPERS.name} 导出 `{fn}` 但 {VUE.name} 完全没引用 "
                            f"(瘦壳后没接通组件)"
                        )

    # 2. 检查关键 UI 块的 class 在 template 中
    for cls, desc in TRACKED_BLOCKS:
        if cls not in vue_src:
            issues.append(
                f"P0 {VUE.name} template 缺失 `{cls}` ({desc}) "
                f"-- 渲染块被删除, 用户级回归"
            )

    # 3. 检查关键函数在 script 中有定义 (在 .vue 内联 或 在 helpers 调用解构出来)
    for fn in TRACKED_FUNCTIONS:
        if fn not in vue_src:
            # 如果在 helpers 中 export 了, 上面 #1 已经报过, 这里跳过
            if HELPERS.exists() and fn in HELPERS.read_text(encoding="utf-8"):
                continue
            issues.append(
                f"P1 {VUE.name} 没有引用 `{fn}` 且 {HELPERS.name} 也没 export "
                f"(可能是历史功能被误删)"
            )

    # 输出结果
    if issues:
        print(f"❌ 发现 {len(issues)} 个模板渲染一致性问题:")
        for i, msg in enumerate(issues, 1):
            print(f"  {i}. {msg}")
        return 1
    print("✅ MarketMonitorView 模板渲染一致性: 全部通过")
    print(f"   跟踪 {len(TRACKED_BLOCKS)} 个 UI 块 + {len(TRACKED_FUNCTIONS)} 个关键函数")
    return 0


if __name__ == "__main__":
    sys.exit(main())
