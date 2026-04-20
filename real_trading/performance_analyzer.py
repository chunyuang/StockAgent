#!/usr/bin/env python3
"""
实盘绩效分析模块
自动生成日/周/月/年度绩效报告、策略效果分析、实盘vs回测对比
"""
import os
import json
from datetime import datetime, timedelta
from typing import List, Dict

class PerformanceAnalyzer:
    """实盘绩效分析器"""
    
    def __init__(self, trade_history_file: str = "trade_history.json"):
        self.history_file = os.path.join(os.path.dirname(__file__), trade_history_file)
        self.trades = self._load_trades()
    
    def _load_trades(self) -> List[Dict]:
        """加载交易历史"""
        if not os.path.exists(self.history_file):
            return []
        
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                trades = json.load(f)
            # 按卖出日期排序
            trades.sort(key=lambda x: x["sell_date"])
            return trades
        except Exception as e:
            print(f"❌ 加载交易历史失败: {e}")
            return []
    
    def get_basic_stats(self, start_date: str = None, end_date: str = None) -> Dict:
        """获取基础统计指标"""
        trades = self._filter_trades_by_date(start_date, end_date)
        if not trades:
            return {}
        
        total_trades = len(trades)
        win_trades = [t for t in trades if t["profit"] > 0]
        lose_trades = [t for t in trades if t["profit"] <= 0]
        win_rate = len(win_trades) / total_trades * 100 if total_trades > 0 else 0
        
        total_profit = sum(t["profit"] for t in trades)
        avg_profit = total_profit / total_trades if total_trades > 0 else 0
        avg_profit_pct = sum(t["profit_pct"] for t in trades) / total_trades if total_trades > 0 else 0
        
        # 盈亏比
        avg_win = sum(t["profit"] for t in win_trades) / len(win_trades) if win_trades else 0
        avg_lose = abs(sum(t["profit"] for t in lose_trades) / len(lose_trades)) if lose_trades else 0
        profit_loss_ratio = avg_win / avg_lose if avg_lose > 0 else 0
        
        # 最大回撤
        balance_series = self._get_balance_series(trades)
        max_drawdown = self._calc_max_drawdown(balance_series)
        
        # 持仓天数统计
        avg_hold_days = sum(t["hold_days"] for t in trades) / total_trades if total_trades > 0 else 0
        max_hold_days = max(t["hold_days"] for t in trades) if trades else 0
        
        # 策略分布
        strategy_stats = {}
        for t in trades:
            strategy = t.get("strategy", "未知")
            if strategy not in strategy_stats:
                strategy_stats[strategy] = {"count": 0, "total_profit": 0, "win_count": 0}
            strategy_stats[strategy]["count"] += 1
            strategy_stats[strategy]["total_profit"] += t["profit"]
            if t["profit"] > 0:
                strategy_stats[strategy]["win_count"] += 1
        
        for s in strategy_stats:
            cnt = strategy_stats[s]["count"]
            strategy_stats[s]["win_rate"] = strategy_stats[s]["win_count"] / cnt * 100 if cnt > 0 else 0
            strategy_stats[s]["avg_profit"] = strategy_stats[s]["total_profit"] / cnt if cnt > 0 else 0
        
        return {
            "period": f"{start_date or '最早'} ~ {end_date or '最新'}",
            "total_trades": total_trades,
            "win_trades": len(win_trades),
            "lose_trades": len(lose_trades),
            "win_rate": round(win_rate, 2),
            "total_profit": round(total_profit, 2),
            "avg_profit": round(avg_profit, 2),
            "avg_profit_pct": round(avg_profit_pct, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "max_drawdown": round(max_drawdown, 2),
            "avg_hold_days": round(avg_hold_days, 1),
            "max_hold_days": max_hold_days,
            "strategy_stats": strategy_stats,
            "first_trade_date": trades[0]["sell_date"] if trades else "",
            "last_trade_date": trades[-1]["sell_date"] if trades else ""
        }
    
    def get_monthly_stats(self) -> List[Dict]:
        """获取按月统计"""
        if not self.trades:
            return []
        
        # 按月份分组
        monthly = {}
        for t in self.trades:
            month = t["sell_date"][:6]  # YYYYMM
            if month not in monthly:
                monthly[month] = []
            monthly[month].append(t)
        
        result = []
        for month in sorted(monthly.keys()):
            trades = monthly[month]
            total = len(trades)
            win = len([t for t in trades if t["profit"] > 0])
            profit = sum(t["profit"] for t in trades)
            result.append({
                "month": month,
                "total_trades": total,
                "win_rate": round(win/total*100, 2) if total > 0 else 0,
                "total_profit": round(profit, 2),
                "avg_profit_pct": round(sum(t["profit_pct"] for t in trades)/total, 2) if total >0 else 0
            })
        
        return result
    
    def get_daily_stats(self, last_n_days: int = 30) -> List[Dict]:
        """获取最近N天的每日统计"""
        if not self.trades:
            return []
        
        # 按日期分组
        daily = {}
        for t in self.trades:
            date = t["sell_date"]
            if date not in daily:
                daily[date] = []
            daily[date].append(t)
        
        # 只保留最近N天
        end_date = datetime.now()
        start_date = end_date - timedelta(days=last_n_days)
        result = []
        
        for date in sorted(daily.keys(), reverse=True):
            dt = datetime.strptime(date, "%Y%m%d")
            if dt < start_date:
                break
            
            trades = daily[date]
            total = len(trades)
            win = len([t for t in trades if t["profit"] > 0])
            profit = sum(t["profit"] for t in trades)
            result.append({
                "date": date,
                "total_trades": total,
                "win_rate": round(win/total*100, 2) if total >0 else 0,
                "total_profit": round(profit, 2)
            })
        
        return result
    
    def get_strategy_analysis(self) -> List[Dict]:
        """分策略分析"""
        if not self.trades:
            return []
        
        strategy_map = {}
        for t in self.trades:
            strategy = t.get("strategy", "未知")
            if strategy not in strategy_map:
                strategy_map[strategy] = []
            strategy_map[strategy].append(t)
        
        result = []
        for strategy, trades in strategy_map.items():
            total = len(trades)
            win = len([t for t in trades if t["profit"] > 0])
            total_profit = sum(t["profit"] for t in trades)
            avg_profit_pct = sum(t["profit_pct"] for t in trades)/total if total>0 else 0
            max_drawdown = self._calc_max_drawdown(self._get_balance_series(trades))
            
            result.append({
                "strategy": strategy,
                "total_trades": total,
                "win_rate": round(win/total*100, 2) if total>0 else 0,
                "total_profit": round(total_profit, 2),
                "avg_profit_pct": round(avg_profit_pct, 2),
                "max_drawdown": round(max_drawdown, 2),
                "avg_hold_days": round(sum(t["hold_days"] for t in trades)/total, 1) if total>0 else 0
            })
        
        # 按总盈利排序
        result.sort(key=lambda x: x["total_profit"], reverse=True)
        return result
    
    def generate_report(self, output_file: str = None, period: str = "all") -> str:
        """生成完整的绩效报告"""
        stats = self.get_basic_stats()
        if not stats:
            report = "ℹ️  暂无交易记录，无法生成绩效报告"
            print(report)
            return report
        
        monthly_stats = self.get_monthly_stats()
        strategy_analysis = self.get_strategy_analysis()
        recent_daily = self.get_daily_stats(7)  # 最近7天
        
        report_lines = [
            "# 📊 StockAgent 实盘绩效报告",
            "",
            f"## 🔹 统计周期：{stats['period']}",
            "",
            "### 📈 核心指标",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 总交易次数 | {stats['total_trades']}次 |",
            f"| 胜率 | {stats['win_rate']}%（{stats['win_trades']}胜{stats['lose_trades']}负） |",
            f"| 总盈利 | {stats['total_profit']:.2f}元 |",
            f"| 平均每笔盈利 | {stats['avg_profit_pct']:.2f}% |",
            f"| 盈亏比 | {stats['profit_loss_ratio']}:1 |",
            f"| 最大回撤 | {stats['max_drawdown']:.2f}% |",
            f"| 平均持仓天数 | {stats['avg_hold_days']}天 |",
            f"| 交易时间段 | {stats['first_trade_date']} ~ {stats['last_trade_date']} |",
            "",
            "### 📅 最近7天交易统计",
            "| 日期 | 交易次数 | 胜率 | 当日盈利 |",
            "|------|----------|------|----------|",
        ]
        
        for day in recent_daily:
            report_lines.append(f"| {day['date']} | {day['total_trades']}次 | {day['win_rate']}% | {day['total_profit']:.2f}元 |")
        
        report_lines.extend([
            "",
            "### 📆 月度统计",
            "| 月份 | 交易次数 | 胜率 | 月度盈利 | 平均收益 |",
            "|------|----------|------|----------|----------|",
        ])
        
        for month in monthly_stats:
            report_lines.append(f"| {month['month']} | {month['total_trades']}次 | {month['win_rate']}% | {month['total_profit']:.2f}元 | {month['avg_profit_pct']:.2f}% |")
        
        report_lines.extend([
            "",
            "### 🎯 分策略表现",
            "| 策略 | 交易次数 | 胜率 | 总盈利 | 平均收益 | 最大回撤 | 平均持仓天数 |",
            "|------|----------|------|----------|----------|----------|--------------|",
        ])
        
        for s in strategy_analysis:
            report_lines.append(f"| {s['strategy']} | {s['total_trades']}次 | {s['win_rate']}% | {s['total_profit']:.2f}元 | {s['avg_profit_pct']:.2f}% | {s['max_drawdown']:.2f}% | {s['avg_hold_days']}天 |")
        
        report_lines.extend([
            "",
            "### 💡 优化建议",
            self._generate_optimization_suggestions(stats, strategy_analysis),
            "",
            f"*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
        ])
        
        report = "\n".join(report_lines)
        
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"✅ 绩效报告已保存到：{output_file}")
        
        return report
    
    def _filter_trades_by_date(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """按日期范围过滤交易"""
        if not start_date and not end_date:
            return self.trades
        
        filtered = []
        for t in self.trades:
            sell_date = t["sell_date"]
            if start_date and sell_date < start_date:
                continue
            if end_date and sell_date > end_date:
                continue
            filtered.append(t)
        return filtered
    
    def _get_balance_series(self, trades: List[Dict]) -> List[float]:
        """获取资金曲线"""
        balance = 0
        series = [0]
        for t in sorted(trades, key=lambda x: x["sell_date"]):
            balance += t["profit"]
            series.append(balance)
        return series
    
    def _calc_max_drawdown(self, balance_series: List[float]) -> float:
        """计算最大回撤"""
        if len(balance_series) < 2:
            return 0
        
        peak = balance_series[0]
        max_dd = 0
        
        for balance in balance_series[1:]:
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        
        return max_dd
    
    def _generate_optimization_suggestions(self, stats: Dict, strategy_analysis: List[Dict]) -> str:
        """生成优化建议"""
        suggestions = []
        
        # 胜率建议
        if stats["win_rate"] < 40:
            suggestions.append("- ⚠️  胜率偏低（<40%），建议提高选股标准，过滤低质量信号")
        elif stats["win_rate"] > 60:
            suggestions.append("✅ 胜率优秀（>60%），可以适当放宽仓位限制")
        else:
            suggestions.append("✅ 胜率处于合理区间（40%-60%），继续保持")
        
        # 盈亏比建议
        if stats["profit_loss_ratio"] < 1.2:
            suggestions.append("- ⚠️  盈亏比偏低（<1.2），建议适当提高止盈比例，或收紧止损幅度")
        elif stats["profit_loss_ratio"] > 2:
            suggestions.append("✅ 盈亏比优秀（>2），利润覆盖亏损能力强")
        else:
            suggestions.append("✅ 盈亏比处于合理区间（1.2-2）")
        
        # 最大回撤建议
        if stats["max_drawdown"] > 20:
            suggestions.append("- ⚠️  最大回撤过大（>20%），建议降低仓位或增加空仓规则")
        elif stats["max_drawdown"] < 10:
            suggestions.append("✅ 最大回撤控制优秀（<10%），风险控制能力强")
        
        # 策略优化建议
        bad_strategies = [s for s in strategy_analysis if s["total_profit"] < 0 or s["win_rate"] < 30]
        good_strategies = [s for s in strategy_analysis if s["total_profit"] > 0 and s["win_rate"] > 50]
        
        if bad_strategies:
            suggestions.append(f"- ⚠️  以下策略表现不佳，建议暂停或优化：{', '.join([s['strategy'] for s in bad_strategies])}")
        if good_strategies:
            suggestions.append(f"✅ 以下策略表现优秀，建议加大仓位：{', '.join([s['strategy'] for s in good_strategies])}")
        
        return "\n".join(suggestions)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="实盘绩效分析工具")
    parser.add_argument("--action", required=True, choices=["stats", "monthly", "strategy", "report"], help="操作类型")
    parser.add_argument("--start", help="开始日期(YYYYMMDD)")
    parser.add_argument("--end", help="结束日期(YYYYMMDD)")
    parser.add_argument("--output", help="输出报告文件路径")
    
    args = parser.parse_args()
    
    analyzer = PerformanceAnalyzer()
    
    if args.action == "stats":
        stats = analyzer.get_basic_stats(args.start, args.end)
        if not stats:
            print("暂无交易记录")
        else:
            print("="*50)
            print("📊 基础绩效统计")
            print("="*50)
            print(f"统计周期：{stats['period']}")
            print(f"总交易次数：{stats['total_trades']}次")
            print(f"胜率：{stats['win_rate']}%（{stats['win_trades']}胜{stats['lose_trades']}负）")
            print(f"总盈利：{stats['total_profit']:.2f}元")
            print(f"平均每笔收益：{stats['avg_profit_pct']:.2f}%")
            print(f"盈亏比：{stats['profit_loss_ratio']}:1")
            print(f"最大回撤：{stats['max_drawdown']:.2f}%")
            print(f"平均持仓天数：{stats['avg_hold_days']}天")
            print("="*50)
    
    elif args.action == "monthly":
        monthly = analyzer.get_monthly_stats()
        print("="*50)
        print("📆 月度统计")
        print("="*50)
        for m in monthly:
            print(f"{m['month']}: {m['total_trades']}次交易，胜率{m['win_rate']}%，盈利{m['total_profit']:.2f}元，平均收益{m['avg_profit_pct']:.2f}%")
        print("="*50)
    
    elif args.action == "strategy":
        strategy = analyzer.get_strategy_analysis()
        print("="*50)
        print("🎯 分策略分析")
        print("="*50)
        for s in strategy:
            print(f"{s['strategy']}: {s['total_trades']}次，胜率{s['win_rate']}%，总盈利{s['total_profit']:.2f}元，平均收益{s['avg_profit_pct']:.2f}%，最大回撤{s['max_drawdown']:.2f}%")
        print("="*50)
    
    elif args.action == "report":
        report = analyzer.generate_report(args.output)
        if not args.output:
            print("\n" + "="*80)
            print(report)
            print("="*80)
