#!/usr/bin/env python3
"""
智能复盘模块
功能：自动分析交易历史，识别盈亏原因、策略问题、操作习惯问题，给出针对性优化建议
"""
import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))
sys.path.insert(0, os.path.dirname(__file__))

from performance_analyzer import PerformanceAnalyzer

class SmartReviewer:
    """智能复盘分析器"""
    
    def __init__(self, trade_history_file: str = "trade_history.json"):
        self.analyzer = PerformanceAnalyzer(trade_history_file)
        self.trades = self.analyzer._load_trades()
    
    def generate_review_report(self, period_days: int = 30, output_file: str = None) -> str:
        """生成智能复盘报告"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)
        start_date_str = start_date.strftime("%Y%m%d")
        
        stats = self.analyzer.get_basic_stats(start_date_str)
        if not stats or stats["total_trades"] == 0:
            return "ℹ️  最近{period_days}天无交易记录，无法生成复盘报告"
        
        monthly_stats = self.analyzer.get_monthly_stats()
        strategy_analysis = self.analyzer.get_strategy_analysis()
        recent_trades = self.analyzer.get_trade_history(20)
        
        report_lines = [
            "# 🧠 智能交易复盘报告",
            "",
            f"## 📅 统计周期：最近{period_days}天（{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}）",
            "",
            "### 📊 核心表现",
            "| 指标 | 数值 | 评价 |",
            "|------|------|------|",
        ]
        
        # 核心指标评价
        report_lines.append(self._eval_metric("总交易次数", f"{stats['total_trades']}次", self._eval_trade_count(stats['total_trades'])))
        report_lines.append(self._eval_metric("胜率", f"{stats['win_rate']}%", self._eval_win_rate(stats['win_rate'])))
        report_lines.append(self._eval_metric("总盈利", f"{stats['total_profit']:.2f}元", self._eval_profit(stats['total_profit'])))
        report_lines.append(self._eval_metric("平均每笔收益", f"{stats['avg_profit_pct']:.2f}%", self._eval_avg_profit(stats['avg_profit_pct'])))
        report_lines.append(self._eval_metric("盈亏比", f"{stats['profit_loss_ratio']}:1", self._eval_pl_ratio(stats['profit_loss_ratio'])))
        report_lines.append(self._eval_metric("最大回撤", f"{stats['max_drawdown']:.2f}%", self._eval_max_drawdown(stats['max_drawdown'])))
        report_lines.append(self._eval_metric("平均持仓天数", f"{stats['avg_hold_days']}天", self._eval_hold_days(stats['avg_hold_days'])))
        
        # 分时间段分析
        if len(monthly_stats) >= 2:
            report_lines.extend([
                "",
                "### 📈 趋势分析",
                self._analyze_trend(monthly_stats),
            ])
        
        # 策略分析
        good_strategies = [s for s in strategy_analysis if s["total_profit"] > 0 and s["win_rate"] >= 40]
        bad_strategies = [s for s in strategy_analysis if s["total_profit"] < 0 or s["win_rate"] < 35]
        
        report_lines.extend([
            "",
            "### 🎯 策略表现分析",
        ])
        
        if good_strategies:
            report_lines.append(f"✅ **表现优秀策略（建议加大仓位）：** {', '.join([s['strategy'] for s in good_strategies])}")
            for s in good_strategies:
                report_lines.append(f"   - {s['strategy']}：{s['total_trades']}次交易，胜率{s['win_rate']}%，总盈利{s['total_profit']:.2f}元，平均收益{s['avg_profit_pct']:.2f}%")
        
        if bad_strategies:
            report_lines.append(f"❌ **表现不佳策略（建议暂停优化）：** {', '.join([s['strategy'] for s in bad_strategies])}")
            for s in bad_strategies:
                report_lines.append(f"   - {s['strategy']}：{s['total_trades']}次交易，胜率{s['win_rate']}%，总盈利{s['total_profit']:.2f}元，平均收益{s['avg_profit_pct']:.2f}%")
        
        # 盈亏分析
        win_trades = [t for t in self.trades if t["sell_date"] >= start_date_str and t["profit"] > 0]
        lose_trades = [t for t in self.trades if t["sell_date"] >= start_date_str and t["profit"] <= 0]
        
        report_lines.extend([
            "",
            "### 💰 盈亏原因分析",
            self._analyze_profit_reasons(win_trades),
            self._analyze_loss_reasons(lose_trades),
        ])
        
        # 操作习惯分析
        report_lines.extend([
            "",
            "### 🖐️ 操作习惯分析",
            self._analyze_trading_habits(),
        ])
        
        # 优化建议
        report_lines.extend([
            "",
            "### 💡 针对性优化建议",
            self._generate_optimization_suggestions(stats, good_strategies, bad_strategies),
        ])
        
        # 近期交易回顾
        if recent_trades:
            report_lines.extend([
                "",
                "### 📝 最近20笔交易回顾",
                "| 日期 | 股票 | 方向 | 盈利 | 收益率 | 持仓天数 | 原因 |",
                "|------|------|------|------|--------|----------|------|",
            ])
            
            for t in recent_trades:
                if t["sell_date"] < start_date_str:
                    continue
                icon = "✅" if t["profit"] > 0 else "❌"
                report_lines.append(f"| {t['sell_date']} | {t['name']}({t['ts_code']}) | {icon} | {t['profit']:.2f}元 | {t['profit_pct']:.2f}% | {t['hold_days']}天 | {t['reason']} |")
        
        report_lines.extend([
            "",
            f"*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
        ])
        
        report = "\n".join(report_lines)
        
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"✅ 复盘报告已保存到：{output_file}")
        
        return report
    
    def _eval_metric(self, name: str, value: str, comment: str) -> str:
        """评估指标并生成表格行"""
        return f"| {name} | {value} | {comment} |"
    
    def _eval_trade_count(self, count: int) -> str:
        """评估交易次数"""
        if count > 50:
            return "⚠️ 交易过于频繁，建议降低交易频率"
        elif count < 5:
            return "ℹ️  交易次数较少，参考意义有限"
        else:
            return "✅ 交易频率合理"
    
    def _eval_win_rate(self, win_rate: float) -> str:
        """评估胜率"""
        if win_rate >= 55:
            return "✅ 胜率优秀，选股能力强"
        elif win_rate >= 40:
            return "✅ 胜率良好，符合预期"
        elif win_rate >= 30:
            return "⚠️ 胜率偏低，建议提高选股标准"
        else:
            return "❌ 胜率过低，需要优化选股逻辑"
    
    def _eval_profit(self, profit: float) -> str:
        """评估盈利"""
        if profit > 10000:
            return "✅ 盈利丰厚，表现优秀"
        elif profit > 0:
            return "✅ 实现正收益，继续保持"
        elif profit > -5000:
            return "⚠️ 小幅亏损，及时调整"
        else:
            return "❌ 亏损较大，需要严格风控"
    
    def _eval_avg_profit(self, avg_pct: float) -> str:
        """评估平均每笔收益"""
        if avg_pct >= 1:
            return "✅ 平均每笔收益优秀，盈利能力强"
        elif avg_pct > 0:
            return "✅ 平均每笔正收益，符合预期"
        else:
            return "❌ 平均每笔亏损，需要优化止盈止损"
    
    def _eval_pl_ratio(self, ratio: float) -> str:
        """评估盈亏比"""
        if ratio >= 2:
            return "✅ 盈亏比优秀，利润覆盖亏损能力强"
        elif ratio >= 1.2:
            return "✅ 盈亏比良好，可持续"
        else:
            return "⚠️ 盈亏比偏低，建议提高止盈比例或收紧止损"
    
    def _eval_max_drawdown(self, dd: float) -> str:
        """评估最大回撤"""
        if dd <= 10:
            return "✅ 回撤控制优秀，风险控制能力强"
        elif dd <= 20:
            return "✅ 回撤控制良好，在可接受范围"
        else:
            return "❌ 回撤过大，建议降低仓位或增加空仓规则"
    
    def _eval_hold_days(self, days: float) -> str:
        """评估平均持仓天数"""
        if days <= 1:
            return "ℹ️  高频交易，以隔日为主"
        elif days <= 3:
            return "✅ 符合超短策略持仓期限"
        else:
            return "⚠️ 持仓时间偏长，注意持仓超时风险"
    
    def _analyze_trend(self, monthly_stats: List[Dict]) -> str:
        """分析收益趋势"""
        if len(monthly_stats) < 2:
            return ""
        
        recent = monthly_stats[-1]
        previous = monthly_stats[-2] if len(monthly_stats) >=2 else recent
        
        lines = []
        profit_change = recent["total_profit"] - previous["total_profit"]
        win_rate_change = recent["win_rate"] - previous["win_rate"]
        
        if profit_change > 0 and win_rate_change > 0:
            lines.append(f"✅ **收益趋势向好**：本月盈利{recent['total_profit']:.2f}元，较上月增加{profit_change:.2f}元，胜率提升{win_rate_change:.2f}%，策略效果提升")
        elif profit_change < 0 and win_rate_change < 0:
            lines.append(f"⚠️ **收益趋势下滑**：本月盈利{recent['total_profit']:.2f}元，较上月减少{abs(profit_change):.2f}元，胜率下降{abs(win_rate_change):.2f}%，建议调整策略")
        else:
            lines.append(f"ℹ️  收益趋势平稳：本月盈利{recent['total_profit']:.2f}元，胜率{recent['win_rate']}%，表现稳定")
        
        return "\n".join(lines)
    
    def _analyze_profit_reasons(self, win_trades: List[Dict]) -> str:
        """分析盈利原因"""
        if not win_trades:
            return ""
        
        # 按策略统计
        strategy_counts = {}
        reason_counts = {}
        hold_days = []
        
        for t in win_trades:
            s = t.get("strategy", "未知")
            strategy_counts[s] = strategy_counts.get(s, 0) + 1
            
            reason = t.get("reason", "未知")
            if "止盈" in reason or "获利" in reason:
                reason_counts["止盈"] = reason_counts.get("止盈", 0) + 1
            elif "止损" in reason:
                reason_counts["止损"] = reason_counts.get("止损", 0) + 1
            else:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            
            hold_days.append(t["hold_days"])
        
        best_strategy = max(strategy_counts.items(), key=lambda x: x[1])[0] if strategy_counts else "未知"
        avg_hold = np.mean(hold_days) if hold_days else 0
        
        lines = [
            "#### 盈利原因分析：",
            f"- 盈利最多的策略：**{best_strategy}**",
            f"- 平均持仓天数：**{avg_hold:.1f}天**",
        ]
        
        if reason_counts:
            top_reason = max(reason_counts.items(), key=lambda x: x[1])[0]
            lines.append(f"- 主要盈利原因：**{top_reason}**")
        
        return "\n".join(lines)
    
    def _analyze_loss_reasons(self, lose_trades: List[Dict]) -> str:
        """分析亏损原因"""
        if not lose_trades:
            return "#### 亏损原因分析：\n- 近期无亏损交易，表现优秀"
        
        # 按策略统计
        strategy_counts = {}
        reason_counts = {}
        hold_days = []
        
        for t in lose_trades:
            s = t.get("strategy", "未知")
            strategy_counts[s] = strategy_counts.get(s, 0) + 1
            
            reason = t.get("reason", "未知")
            if "止损" in reason or "亏损" in reason:
                reason_counts["止损"] = reason_counts.get("止损", 0) + 1
            elif "超期" in reason or "超时" in reason:
                reason_counts["持仓超期"] = reason_counts.get("持仓超期", 0) + 1
            elif "止盈" in reason:
                reason_counts["止盈回落"] = reason_counts.get("止盈回落", 0) + 1
            else:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            
            hold_days.append(t["hold_days"])
        
        worst_strategy = max(strategy_counts.items(), key=lambda x: x[1])[0] if strategy_counts else "未知"
        avg_hold = np.mean(hold_days) if hold_days else 0
        
        lines = [
            "#### 亏损原因分析：",
            f"- 亏损最多的策略：**{worst_strategy}**",
            f"- 平均持仓天数：**{avg_hold:.1f}天**",
        ]
        
        if reason_counts:
            top_reason = max(reason_counts.items(), key=lambda x: x[1])[0]
            lines.append(f"- 主要亏损原因：**{top_reason}**")
        
        return "\n".join(lines)
    
    def _analyze_trading_habits(self) -> str:
        """分析操作习惯"""
        if not self.trades:
            return ""
        
        # 分析卖出时间分布（简化版，后续可扩展）
        # 分析止损止盈执行情况
        stop_loss_count = 0
        take_profit_count = 0
        force_close_count = 0
        manual_count = 0
        
        for t in self.trades:
            reason = t.get("reason", "")
            if "止损" in reason:
                stop_loss_count += 1
            elif "止盈" in reason:
                take_profit_count += 1
            elif "超期" in reason or "强制平仓" in reason:
                force_close_count += 1
            else:
                manual_count += 1
        
        total = len(self.trades)
        lines = []
        
        if total > 0:
            sl_pct = stop_loss_count / total * 100
            tp_pct = take_profit_count / total * 100
            fc_pct = force_close_count / total * 100
            manual_pct = manual_count / total * 100
            
            lines.append(f"- 止损执行率：{sl_pct:.1f}%（{stop_loss_count}次）")
            lines.append(f"- 止盈执行率：{tp_pct:.1f}%（{take_profit_count}次）")
            lines.append(f"- 强制平仓率：{fc_pct:.1f}%（{force_close_count}次）")
            lines.append(f"- 手动平仓率：{manual_pct:.1f}%（{manual_count}次）")
            
            if sl_pct > 30:
                lines.append("⚠️ 止损次数偏多，建议优化买点或适当放宽止损幅度")
            if tp_pct < 20:
                lines.append("⚠️ 止盈次数偏少，建议优化卖点策略，及时落袋为安")
        
        return "\n".join(lines)
    
    def _generate_optimization_suggestions(self, stats: Dict, good_strategies: List, bad_strategies: List) -> str:
        """生成优化建议"""
        suggestions = []
        
        # 风控建议
        if stats["max_drawdown"] > 20:
            suggestions.append("1. **风控优化**：最大回撤超过20%，建议降低总仓位上限到50%，或增加强制空仓规则")
        elif stats["max_drawdown"] > 10:
            suggestions.append("1. **风控优化**：最大回撤在10-20%区间，可考虑行情不好时适当降低仓位")
        
        # 胜率建议
        if stats["win_rate"] < 40:
            suggestions.append("2. **选股优化**：胜率低于40%，建议提高选股标准，增加过滤条件，减少无效信号")
        
        # 盈亏比建议
        if stats["profit_loss_ratio"] < 1.2:
            suggestions.append("3. **止盈止损优化**：盈亏比低于1.2，建议适当提高止盈比例，或收紧止损幅度，提升盈亏比")
        
        # 策略建议
        if good_strategies:
            good_names = ", ".join([s["strategy"] for s in good_strategies])
            suggestions.append(f"4. **策略优化**：加大{good_names}等优秀策略的仓位占比，提升盈利贡献")
        if bad_strategies:
            bad_names = ", ".join([s["strategy"] for s in bad_strategies])
            suggestions.append(f"5. **策略优化**：暂停{bad_names}等表现不佳的策略，或进行参数优化")
        
        # 交易频率建议
        if stats["total_trades"] > 50:
            suggestions.append("6. **交易频率优化**：近30天交易超过50次，过于频繁，建议减少交易次数，提高信号质量")
        
        if not suggestions:
            suggestions.append("✅ 各方面表现均衡，继续保持当前策略")
        
        return "\n".join([f"- {s}" for s in suggestions])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="智能复盘工具")
    parser.add_argument("--period", type=int, default=30, help="复盘最近N天，默认30天")
    parser.add_argument("--output", help="输出报告文件路径")
    
    args = parser.parse_args()
    
    reviewer = SmartReviewer()
    report = reviewer.generate_review_report(args.period, args.output)
    
    if not args.output:
        print("\n" + "="*80)
        print(report)
        print("="*80)
