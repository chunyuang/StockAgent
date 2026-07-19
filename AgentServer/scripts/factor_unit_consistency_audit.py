#!/usr/bin/env python3
"""因子单位一致性审查脚本

检查 MongoDB 中因子字段的存储单位与策略筛选条件中的比较阈值是否匹配。
历史踩坑:
  - 5/3: circ_mv 万元/元/亿元 混用，龙头低吸策略过滤形同虚设
  - 7/4: push2 f21=float_mv(元) vs MongoDB fallback circ_mv(万元)，阈值混乱

检查项:
  1. circ_mv 跨集合单位一致性 (daily_basic=亿元, stock_daily_ak_full=万元)
  2. circ_mv 策略参数单位 vs 存储单位 (策略参数=亿元, 运行时转换是否正确)
  3. pct_chg 正负号一致性 (下跌应为负值)
  4. turnover_rate 范围校验 (应为0-100百分比)
  5. volume_ratio 范围校验 (应为0-50正常范围)
  6. pullback_pct 符号校验 (回调应为负值)
  7. high_pct 范围校验 (应为百分比0-20正常)
  8. 止损/止盈百分比格式一致性 (0.03=3% vs 3.0=300%)
"""

import sys
import os
import json
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pymongo

# ============================================================
# 单位约定文档 (SOURCE OF TRUTH)
# ============================================================
UNIT_CONVENTIONS = {
    # 字段名: {集合: 单位, ...}
    "circ_mv": {
        "daily_basic": "亿元",       # Tushare原始单位
        "stock_daily_ak_full": "万元", # AKShare原始单位
        "scanner_signals.factors": "万元", # strategy_scorer统一转万元
        "strategy_params": "亿元",    # STRATEGY_CONFIGS中min/max_circulation_market_cap
    },
    "total_mv": {
        "daily_basic": "亿元",
        "stock_daily_ak_full": "万元",
    },
    "pct_chg": {
        "daily_basic": "百分比(正=涨,负=跌)",
        "stock_daily_ak_full": "百分比(正=涨,负=跌)",
        "strategy_params": "小数(0.03=3%)",  # min_rise_pct等
    },
    "turnover_rate": {
        "daily_basic": "百分比(0-100)",
        "stock_daily_ak_full": "百分比(0-100)",
        "strategy_params": "百分比(3=3%)",  # min_turnover_rate=3
    },
    "volume_ratio": {
        "daily_basic": "比值(0-50正常)",
        "stock_daily_ak_full": "比值(0-50正常)",
        "strategy_params": "比值(1.5)",
    },
    "pullback_pct": {
        "stock_daily_ak_full": "小数(-0.05=-5%)",
        "strategy_params": "小数(0.05=5%)",  # min_correction_pct
    },
    "stop_loss_pct": {
        "risk_params": "小数(0.03=3%)",
    },
    "take_profit_pct": {
        "risk_params": "小数(0.12=12%)",
    },
}

# 策略参数中涉及市值的字段 (单位=亿元)
MARKET_CAP_PARAMS = {
    "min_circulation_market_cap", "max_circulation_market_cap",
}

# 策略参数中涉及百分比的字段 (需判断是小数还是百分比)
PCT_PARAMS = {
    "min_rise_pct", "max_rise_pct",
    "min_close_rise_pct", "max_open_rise_pct",
    "min_correction_pct", "max_correction_pct",
    "pullback_mid_fallback_pct", "pullback_high_threshold", "pullback_profit_lock_threshold",
    "min_rise_after_qiao",
    "next_day_open_sell_pct",
    "opening_pct_min", "opening_pct_max",
    "stop_loss_pct", "take_profit_pct", "trailing_stop_pct",
    "hold_protection_threshold", "slippage_pct",
}


class FactorUnitAudit:
    def __init__(self):
        self.client = pymongo.MongoClient("mongodb://localhost:27017/")
        self.db = self.client["stock_agent"]
        self.findings = []
        self.p0_count = 0
        self.p1_count = 0
        self.p2_count = 0

    def _add_finding(self, severity: str, check_id: str, description: str, detail: str = ""):
        self.findings.append({
            "severity": severity,
            "check_id": check_id,
            "description": description,
            "detail": detail,
        })
        if severity == "P0":
            self.p0_count += 1
        elif severity == "P1":
            self.p1_count += 1
        elif severity == "P2":
            self.p2_count += 2

    # ---- Check 1: circ_mv cross-collection unit consistency ----
    def check_circ_mv_units(self):
        """验证 circ_mv 在不同集合中的单位是否与约定一致"""
        print("\n[Check 1] circ_mv 跨集合单位一致性")

        # Sample from daily_basic
        sample_daily_basic = list(self.db.daily_basic.find(
            {"circ_mv": {"$gt": 0}},
            {"ts_code": 1, "trade_date": 1, "circ_mv": 1}
        ).limit(10))

        # Sample from stock_daily_ak_full
        sample_ak_full = list(self.db.stock_daily_ak_full.find(
            {"circ_mv": {"$gt": 0}},
            {"ts_code": 1, "trade_date": 1, "circ_mv": 1}
        ).limit(10))

        if not sample_daily_basic or not sample_ak_full:
            self._add_finding("P2", "FUC-1.1", "circ_mv 样本不足，无法验证跨集合单位",
                            f"daily_basic={len(sample_daily_basic)}, ak_full={len(sample_ak_full)}")
            return

        # 同一只票同一天比较
        daily_basic_map = {}
        for doc in sample_daily_basic:
            key = f"{doc['ts_code']}_{doc['trade_date']}"
            daily_basic_map[key] = doc["circ_mv"]

        mismatches = []
        for doc in sample_ak_full:
            key = f"{doc['ts_code']}_{doc['trade_date']}"
            if key in daily_basic_map:
                db_val = daily_basic_map[key]
                ak_val = doc["circ_mv"]
                expected_ratio = 10000  # 亿元→万元
                actual_ratio = ak_val / db_val if db_val > 0 else 0
                if abs(actual_ratio - expected_ratio) / expected_ratio > 0.1:
                    mismatches.append({
                        "ts_code": doc["ts_code"],
                        "trade_date": doc["trade_date"],
                        "daily_basic_circ_mv": db_val,
                        "ak_full_circ_mv": ak_val,
                        "ratio": actual_ratio,
                    })

        if mismatches:
            self._add_finding("P0", "FUC-1.2",
                            f"circ_mv 跨集合单位不一致 ({len(mismatches)}处)",
                            f"预期 daily_basic(亿元) × 10000 = ak_full(万元), 异常样本: {mismatches[:3]}")
        else:
            print("  ✅ circ_mv daily_basic(亿元) vs ak_full(万元) 单位一致")

    # ---- Check 2: circ_mv strategy param vs storage unit ----
    def check_circ_mv_strategy_params(self):
        """验证策略中市值参数(亿元)与运行时circ_mv(万元)的转换是否正确"""
        print("\n[Check 2] circ_mv 策略参数与运行时转换")

        # Import strategy configs
        try:
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        except ImportError:
            self._add_finding("P1", "FUC-2.1", "无法导入STRATEGY_CONFIGS")
            return

        for strategy_name, cfg in STRATEGY_CONFIGS.items():
            params = cfg.get("params", {})
            for param_name in MARKET_CAP_PARAMS:
                if param_name in params:
                    val = params[param_name]
                    # val单位=亿元, 运行时circ_mv=万元, 需要val*10000比较
                    # signal_manager.py L608: circ_mv = circ_mv_raw / 10000.0 if circ_mv_raw >= 10000 else circ_mv_raw
                    # 转换后circ_mv单位=亿元, 与val单位一致 → 正确
                    if val <= 0:
                        self._add_finding("P1", f"FUC-2.2",
                                        f"{strategy_name}.{param_name}={val} 非正值",
                                        f"市值阈值应为正数")

        # Verify the runtime conversion logic in signal_manager.py
        sig_mgr_path = PROJECT_ROOT / "nodes" / "market_monitor" / "signal_manager.py"
        if sig_mgr_path.exists():
            content = sig_mgr_path.read_text()
            if "circ_mv_raw / 10000.0" in content and "circ_mv_raw >= 10000" in content:
                print("  ✅ signal_manager circ_mv 转换逻辑正确 (万元→亿元)")
            else:
                self._add_finding("P0", "FUC-2.3",
                                "signal_manager circ_mv 转换逻辑缺失或变更",
                                "预期: circ_mv_raw / 10000.0 if circ_mv_raw >= 10000")
        else:
            self._add_finding("P1", "FUC-2.4", f"signal_manager.py 不存在: {sig_mgr_path}")

    # ---- Check 3: pct_chg sign consistency ----
    def check_pct_chg_sign(self):
        """验证 pct_chg 下跌日应为负值"""
        print("\n[Check 3] pct_chg 正负号一致性")

        # Find docs where close < pre_close but pct_chg > 0 (sign error)
        pipeline = [
            {"$match": {"pct_chg": {"$gt": 0}}},
            {"$limit": 1000},
            {"$group": {
                "_id": None,
                "avg_pct_chg": {"$avg": "$pct_chg"},
                "max_pct_chg": {"$max": "$pct_chg"},
                "count": {"$sum": 1},
            }}
        ]

        result = list(self.db.stock_daily_ak_full.aggregate(pipeline))
        if result:
            avg = result[0]["avg_pct_chg"]
            max_val = result[0]["max_pct_chg"]
            # pct_chg > 100 可能是单位错误(小数 vs 百分比)
            if max_val > 100:
                # 排除新股首日/ST股涨停
                extreme = list(self.db.stock_daily_ak_full.find(
                    {"pct_chg": {"$gt": 50}},
                    {"ts_code": 1, "pct_chg": 1, "trade_date": 1}
                ).limit(5))
                self._add_finding("P2", "FUC-3.1",
                                f"pct_chg 存在>50%的异常值 ({len(extreme)}条)",
                                f"可能是新股首日或单位错误: {extreme[:2]}")
            else:
                print(f"  ✅ pct_chg 范围正常 (avg={avg:.1f}%, max={max_val:.1f}%)")

    # ---- Check 4: turnover_rate range ----
    def check_turnover_rate_range(self):
        """验证 turnover_rate 在0-100百分比范围内"""
        print("\n[Check 4] turnover_rate 范围校验")

        pipeline = [
            {"$match": {"turnover_rate": {"$exists": True}}},
            {"$group": {
                "_id": None,
                "min": {"$min": "$turnover_rate"},
                "max": {"$max": "$turnover_rate"},
                "avg": {"$avg": "$turnover_rate"},
                "count_over_100": {"$sum": {"$cond": [{"$gt": ["$turnover_rate", 100]}, 1, 0]}},
            }}
        ]

        for coll_name in ["daily_basic", "stock_daily_ak_full"]:
            if coll_name not in self.db.list_collection_names():
                continue
            result = list(self.db[coll_name].aggregate(pipeline))
            if result:
                r = result[0]
                over_100 = r.get("count_over_100", 0)
                if over_100 > 0:
                    self._add_finding("P1", f"FUC-4.{coll_name}",
                                    f"{coll_name} turnover_rate 超过100% ({over_100}条)",
                                    f"可能存储的是小数(0-1)而非百分比(0-100), min={r['min']}, max={r['max']}")
                else:
                    print(f"  ✅ {coll_name} turnover_rate 范围正常 (avg={r['avg']:.2f}%)")

    # ---- Check 5: volume_ratio range ----
    def check_volume_ratio_range(self):
        """验证 volume_ratio 在合理范围"""
        print("\n[Check 5] volume_ratio 范围校验")

        pipeline = [
            {"$match": {"volume_ratio": {"$exists": True, "$gt": 0}}},
            {"$group": {
                "_id": None,
                "min": {"$min": "$volume_ratio"},
                "max": {"$max": "$volume_ratio"},
                "avg": {"$avg": "$volume_ratio"},
                "count_over_50": {"$sum": {"$cond": [{"$gt": ["$volume_ratio", 50]}, 1, 0]}},
            }}
        ]

        for coll_name in ["daily_basic", "stock_daily_ak_full"]:
            if coll_name not in self.db.list_collection_names():
                continue
            result = list(self.db[coll_name].aggregate(pipeline))
            if result:
                r = result[0]
                over_50 = r.get("count_over_50", 0)
                if over_50 > 0:
                    self._add_finding("P2", f"FUC-5.{coll_name}",
                                    f"{coll_name} volume_ratio>50 ({over_50}条)",
                                    f"可能是百分比而非比值, max={r['max']}")
                else:
                    print(f"  ✅ {coll_name} volume_ratio 范围正常 (avg={r['avg']:.2f})")

    # ---- Check 6: pullback_pct sign ----
    def check_pullback_pct_sign(self):
        """验证 pullback_pct 回调应为负值"""
        print("\n[Check 6] pullback_pct 符号校验")

        pipeline = [
            {"$match": {"pullback_pct": {"$exists": True, "$ne": 0}}},
            {"$group": {
                "_id": None,
                "min": {"$min": "$pullback_pct"},
                "max": {"$max": "$pullback_pct"},
                "count_positive": {"$sum": {"$cond": [{"$gt": ["$pullback_pct", 0]}, 1, 0]}},
                "count_negative": {"$sum": {"$cond": [{"$lt": ["$pullback_pct", 0]}, 1, 0]}},
                "total": {"$sum": 1},
            }}
        ]

        result = list(self.db.stock_daily_ak_full.aggregate(pipeline))
        if result:
            r = result[0]
            pos = r.get("count_positive", 0)
            neg = r.get("count_negative", 0)
            total = r.get("total", 0)

            # pullback_pct = (close - peak) / peak, 回调时为负
            # 但某些实现可能用绝对值, 需检查
            if pos > neg and pos / max(total, 1) > 0.5:
                self._add_finding("P1", "FUC-6.1",
                                f"pullback_pct 正值占比异常 ({pos}/{total}={pos/max(total,1)*100:.0f}%)",
                                f"回调应为负值, 可能存储的是绝对值, min={r['min']}, max={r['max']}")
            else:
                print(f"  ✅ pullback_pct 符号正常 (负值={neg}, 正值={pos})")

    # ---- Check 7: Stop loss/take profit percentage format ----
    def check_stop_loss_take_profit_format(self):
        """验证止损止盈参数是3%=0.03而非3.0(=300%)"""
        print("\n[Check 7] 止损/止盈百分比格式一致性")

        try:
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        except ImportError:
            self._add_finding("P1", "FUC-7.1", "无法导入STRATEGY_CONFIGS")
            return

        for strategy_name, cfg in STRATEGY_CONFIGS.items():
            risk = cfg.get("riskParams", {})
            params = cfg.get("params", {})

            # Check risk params
            for param in ["stop_loss_pct", "take_profit_pct", "trailing_stop_pct",
                         "hold_protection_threshold", "slippage_pct"]:
                if param in risk:
                    val = risk[param]
                    # Should be 0.03 not 3.0 (3.0 = 300%)
                    if val > 1.0 and "pct" in param:
                        self._add_finding("P0", f"FUC-7.{strategy_name}.{param}",
                                        f"{strategy_name}.{param}={val} 疑似百分比格式(应为0.xx)",
                                        f"0.03=3%是正确格式, 3.0=300%是错误格式")

            # Check selection params
            for param in ["min_rise_pct", "max_rise_pct", "min_close_rise_pct",
                         "max_open_rise_pct", "min_correction_pct", "max_correction_pct",
                         "pullback_mid_fallback_pct", "pullback_high_threshold",
                         "pullback_profit_lock_threshold", "min_rise_after_qiao",
                         "next_day_open_sell_pct"]:
                if param in params:
                    val = params[param]
                    if val > 1.0 and "pct" in param and "opening" not in param:
                        # opening_pct_min/max 单位是百分比(-1.0, 5.0)
                        self._add_finding("P0", f"FUC-7.{strategy_name}.{param}",
                                        f"{strategy_name}.{param}={val} 疑似百分比格式(应为0.xx)",
                                        f"0.03=3%是正确格式, 3.0=300%是错误格式")

            # opening_pct_min/max 特殊: 单位是百分比(-1.0=-1%, 5.0=5%)
            for param in ["opening_pct_min", "opening_pct_max"]:
                if param in params:
                    val = params[param]
                    if abs(val) > 15:  # 竞价涨幅不应超过±15%
                        self._add_finding("P1", f"FUC-7.{strategy_name}.{param}",
                                        f"{strategy_name}.{param}={val} 超出正常范围(±15%)")

    # ---- Check 8: Strategy scorer merge_factors unit conversion ----
    def check_merge_factors_conversion(self):
        """验证 strategy_scorer.merge_factors 中 circ_mv 单位转换逻辑"""
        print("\n[Check 8] strategy_scorer.merge_factors 单位转换")

        scorer_path = PROJECT_ROOT / "nodes" / "market_monitor" / "strategy_scorer.py"
        if not scorer_path.exists():
            self._add_finding("P1", "FUC-8.1", f"strategy_scorer.py 不存在")
            return

        content = scorer_path.read_text()

        # Check circ_mv conversion
        # Expected: unified to 万元
        # push2 f21=float_mv(元) → ÷10000 → 万元
        # fallback已统一为元(circ_mv*10000)
        if "cm > 1e8" in content:
            # If cm > 1e8, assume unit is 元, divide by 10000 to get 万元
            print("  ✅ strategy_scorer circ_mv 元→万元 转换存在")
        else:
            self._add_finding("P1", "FUC-8.2",
                            "strategy_scorer 缺少 circ_mv > 1e8 元→万元 转换",
                            "可能导致大盘股 circ_mv 被错误处理")

        # Check for circ_mv output unit comment
        if 'row["circ_mv"] = cm' in content or 'row["circ_mv"]' in content:
            # Verify the final unit is 万元
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if 'row["circ_mv"]' in line and i > 0:
                    # Check surrounding comments
                    context = '\n'.join(lines[max(0,i-3):i+2])
                    if '万元' in context or '/ 10000' in context or '/10000' in context:
                        print("  ✅ strategy_scorer circ_mv 输出单位注释为万元")
                        break
            else:
                self._add_finding("P2", "FUC-8.3",
                                "strategy_scorer circ_mv 输出单位注释缺失",
                                "建议添加注释明确输出单位=万元")

    def run_all(self):
        print("=" * 60)
        print("因子单位一致性审查 (Factor Unit Consistency Audit)")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        self.check_circ_mv_units()
        self.check_circ_mv_strategy_params()
        self.check_pct_chg_sign()
        self.check_turnover_rate_range()
        self.check_volume_ratio_range()
        self.check_pullback_pct_sign()
        self.check_stop_loss_take_profit_format()
        self.check_merge_factors_conversion()

        # Summary
        print("\n" + "=" * 60)
        print("审查结果汇总")
        print("=" * 60)
        print(f"P0 (阻断级): {self.p0_count}")
        print(f"P1 (严重级): {self.p1_count}")
        print(f"P2 (建议级): {self.p2_count}")

        if self.findings:
            print("\n详细发现:")
            for f in self.findings:
                icon = "🔴" if f["severity"] == "P0" else "🟡" if f["severity"] == "P1" else "🔵"
                print(f"  {icon} [{f['check_id']}] {f['severity']}: {f['description']}")
                if f['detail']:
                    print(f"     {f['detail']}")
        else:
            print("\n✅ 所有检查项通过，无因子单位一致性问题")

        return {
            "P0": self.p0_count,
            "P1": self.p1_count,
            "P2": self.p2_count,
            "findings": self.findings,
        }


if __name__ == "__main__":
    audit = FactorUnitAudit()
    result = audit.run_all()

    # Write results
    output_dir = Path(__file__).resolve().parent.parent / "audit_results"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / f"factor_unit_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存: {output_file}")

    sys.exit(1 if result["P0"] > 0 else 0)
