#!/usr/bin/env python3
"""
绩效指标计算模块
功能：基于净值序列和交易历史，计算完整的专业级绩效指标

指标包括：
1. 收益类：总收益率、年化收益率、超额收益率
2. 风险类：波动率、下行波动率、最大回撤、最大回撤持续期
3. 风险调整收益：夏普比率、索提诺比率、卡玛比率、信息比率
4. 交易统计：胜率、盈亏比、平均盈利/亏损、平均持仓天数
5. 分布特征：收益偏度、峰度、VaR、CVaR
6. 分策略绩效归因
"""
import sys
import logging

logger = logging.getLogger(__name__)
import os
import json
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# 项目路径配置
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', 'workspace', 'StockAgent'))
REAL_TRADING_DIR = os.path.join(PROJECT_ROOT, 'real_trading')

sys.path.insert(0, os.path.join(PROJECT_ROOT, 'AgentServer'))
sys.path.insert(0, REAL_TRADING_DIR)

from performance_analyzer import PerformanceAnalyzer


@dataclass
class PerformanceMetrics:
    """完整绩效指标集合
    
    Attributes:
        # 收益类
        total_return: 总收益率(%)
        annualized_return: 年化收益率(%)
        excess_return: 超额收益率(%)，相对无风险利率
        
        # 风险类
        annualized_volatility: 年化波动率(%)
        downside_volatility: 下行波动率(%)
        max_drawdown: 最大回撤(%)
        max_drawdown_duration: 最大回撤持续期(天)
        max_drawdown_start: 最大回撤起始日
        max_drawdown_end: 最大回撤结束日
        
        # 风险调整收益
        sharpe_ratio: 夏普比率
        sortino_ratio: 索提诺比率
        calmar_ratio: 卡玛比率
        
        # 交易统计
        total_trades: 总交易次数
        win_trades: 盈利次数
        lose_trades: 亏损次数
        win_rate: 胜率(%)
        profit_loss_ratio: 盈亏比
        avg_profit: 平均盈利金额
        avg_loss: 平均亏损金额
        avg_profit_pct: 平均盈利比例(%)
        avg_loss_pct: 平均亏损比例(%)
        avg_hold_days: 平均持仓天数
        max_consecutive_wins: 最大连续盈利次数
        max_consecutive_losses: 最大连续亏损次数
        
        # 分布特征
        return_skewness: 收益偏度
        return_kurtosis: 收益峰度
        var_95: 95% VaR(%)
        cvar_95: 95% CVaR/ES(%)
        
        # 统计区间
        start_date: 统计起始日
        end_date: 统计结束日
        trading_days: 交易天数
    """
    # 收益类
    total_return: float = 0.0
    annualized_return: float = 0.0
    excess_return: float = 0.0
    
    # 风险类
    annualized_volatility: float = 0.0
    downside_volatility: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    max_drawdown_start: str = ""
    max_drawdown_end: str = ""
    
    # 风险调整收益
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    
    # 交易统计
    total_trades: int = 0
    win_trades: int = 0
    lose_trades: int = 0
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    avg_profit_pct: float = 0.0
    avg_loss_pct: float = 0.0
    avg_hold_days: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    
    # 分布特征
    return_skewness: float = 0.0
    return_kurtosis: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    
    # 统计区间
    start_date: str = ""
    end_date: str = ""
    trading_days: int = 0


class PerformanceCalculator:
    """绩效指标计算器
    
    从净值序列（NavRecord）和交易历史（trade_history.json）中
    计算完整的专业级绩效指标。
    
    用法：
        calculator = PerformanceCalculator(account_id="xxx")
        metrics = calculator.calculate(nav_records, start_date, end_date)
        report = calculator.generate_report(metrics, output_dir=...)
    """
    
    # 默认参数
    RISK_FREE_RATE = 0.02       # 无风险利率2%（一年期国债）
    TRADING_DAYS_PER_YEAR = 242  # A股年交易日
    
    def __init__(self, account_id: str = None):
        """初始化计算器
        
        Args:
            account_id: 账户ID，用于加载交易历史
        """
        self.account_id = account_id
    
    def calculate(self, nav_records: List = None, start_date: str = None,
                  end_date: str = None) -> PerformanceMetrics:
        """计算完整绩效指标
        
        Args:
            nav_records: NavRecord列表（从NavTracker获取）
            start_date: 统计起始日
            end_date: 统计结束日
        
        Returns:
            PerformanceMetrics: 完整绩效指标
        """
        metrics = PerformanceMetrics()
        
        # === 加载净值数据 ===
        if nav_records:
            # 过滤日期范围
            filtered = nav_records
            if start_date:
                filtered = [r for r in filtered if r.date >= start_date]
            if end_date:
                filtered = [r for r in filtered if r.date <= end_date]
            
            if filtered:
                nav_series = [r.nav for r in filtered]
                daily_returns = [r.daily_return / 100 for r in filtered]  # 转为小数
                
                metrics.start_date = filtered[0].date
                metrics.end_date = filtered[-1].date
                metrics.trading_days = len(filtered)
                
                # === 收益类指标 ===
                metrics.total_return = (nav_series[-1] / nav_series[0] - 1) * 100
                
                # 年化收益率
                if metrics.trading_days > 1:
                    years = metrics.trading_days / self.TRADING_DAYS_PER_YEAR
                    if nav_series[-1] > 0 and nav_series[0] > 0 and years > 0:
                        metrics.annualized_return = (
                            (nav_series[-1] / nav_series[0]) ** (1 / years) - 1
                        ) * 100
                
                # 超额收益率
                period_years = metrics.trading_days / self.TRADING_DAYS_PER_YEAR
                risk_free_period = self.RISK_FREE_RATE * period_years * 100
                metrics.excess_return = metrics.total_return - risk_free_period
                
                # === 风险类指标 ===
                if len(daily_returns) > 1:
                    # 年化波动率
                    mean_ret = sum(daily_returns) / len(daily_returns)
                    variance = sum((r - mean_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
                    daily_vol = math.sqrt(variance)
                    metrics.annualized_volatility = daily_vol * math.sqrt(self.TRADING_DAYS_PER_YEAR) * 100
                    
                    # 下行波动率
                    below_target = [r for r in daily_returns if r < 0]
                    if below_target:
                        downside_var = sum(r ** 2 for r in below_target) / len(below_target)
                        metrics.downside_volatility = math.sqrt(downside_var) * math.sqrt(self.TRADING_DAYS_PER_YEAR) * 100
                    
                    # 收益偏度
                    if len(daily_returns) > 2:
                        std = math.sqrt(variance) if variance > 0 else 1e-10
                        metrics.return_skewness = sum(
                            ((r - mean_ret) / std) ** 3 for r in daily_returns
                        ) / len(daily_returns)
                        
                        # 收益峰度
                        metrics.return_kurtosis = sum(
                            ((r - mean_ret) / std) ** 4 for r in daily_returns
                        ) / len(daily_returns) - 3
                    
                    # VaR 95%
                    sorted_returns = sorted(daily_returns)
                    var_idx = int(len(sorted_returns) * 0.05)
                    metrics.var_95 = sorted_returns[var_idx] * 100 if var_idx < len(sorted_returns) else 0
                    
                    # CVaR 95%
                    tail_returns = sorted_returns[:var_idx + 1] if var_idx > 0 else sorted_returns[:1]
                    metrics.cvar_95 = (sum(tail_returns) / len(tail_returns)) * 100 if tail_returns else 0
                
                # 最大回撤（含持续期和日期）
                dd_result = self._calc_max_drawdown_detail(filtered)
                metrics.max_drawdown = dd_result["max_drawdown"]
                metrics.max_drawdown_duration = dd_result["duration"]
                metrics.max_drawdown_start = dd_result["start_date"]
                metrics.max_drawdown_end = dd_result["end_date"]
                
                # === 风险调整收益 ===
                if metrics.annualized_volatility > 0:
                    # 夏普比率
                    annualized_rf = self.RISK_FREE_RATE * 100
                    metrics.sharpe_ratio = (
                        (metrics.annualized_return - annualized_rf) / metrics.annualized_volatility
                    )
                
                if metrics.downside_volatility > 0:
                    # 索提诺比率
                    annualized_rf = self.RISK_FREE_RATE * 100
                    metrics.sortino_ratio = (
                        (metrics.annualized_return - annualized_rf) / metrics.downside_volatility
                    )
                
                if metrics.max_drawdown > 0:
                    # 卡玛比率
                    metrics.calmar_ratio = metrics.annualized_return / metrics.max_drawdown
        
        # === 交易统计（从交易历史加载） ===
        trade_stats = self._load_trade_stats(start_date, end_date)
        if trade_stats:
            metrics.total_trades = trade_stats.get("total_trades", 0)
            metrics.win_trades = trade_stats.get("win_trades", 0)
            metrics.lose_trades = trade_stats.get("lose_trades", 0)
            metrics.win_rate = trade_stats.get("win_rate", 0)
            metrics.profit_loss_ratio = trade_stats.get("profit_loss_ratio", 0)
            metrics.avg_profit = trade_stats.get("avg_profit", 0)
            metrics.avg_loss = trade_stats.get("avg_loss", 0)
            metrics.avg_profit_pct = trade_stats.get("avg_profit_pct", 0)
            metrics.avg_loss_pct = trade_stats.get("avg_loss_pct", 0)
            metrics.avg_hold_days = trade_stats.get("avg_hold_days", 0)
            metrics.max_consecutive_wins = trade_stats.get("max_consecutive_wins", 0)
            metrics.max_consecutive_losses = trade_stats.get("max_consecutive_losses", 0)
        
        return metrics
    
    def generate_report(self, metrics: PerformanceMetrics, output_dir: str = None,
                       strategy_analysis: List[Dict] = None) -> str:
        """生成绩效指标Markdown报告
        
        Args:
            metrics: 绩效指标
            output_dir: 报告输出目录
            strategy_analysis: 分策略分析结果（可选）
        
        Returns:
            str: Markdown报告
        """
        lines = [
            "# 📊 绩效指标分析报告",
            "",
            f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"> 统计区间：{self._fmt(metrics.start_date)} ~ {self._fmt(metrics.end_date)}",
            f"> 交易天数：{metrics.trading_days} 天",
            "",
            "---",
            "",
            "## 1️⃣ 收益指标",
            "",
            "| 指标 | 数值 | 说明 |",
            "|------|------|------|",
            f"| 总收益率 | {metrics.total_return:.2f}% | 统计区间内的总收益 |",
            f"| 年化收益率 | {metrics.annualized_return:.2f}% | 折算为年度收益率 |",
            f"| 超额收益率 | {metrics.excess_return:.2f}% | 相对无风险利率({self.RISK_FREE_RATE*100:.1f}%)的超额 |",
            "",
            "## 2️⃣ 风险指标",
            "",
            "| 指标 | 数值 | 说明 |",
            "|------|------|------|",
            f"| 年化波动率 | {metrics.annualized_volatility:.2f}% | 收益率标准差年化 |",
            f"| 下行波动率 | {metrics.downside_volatility:.2f}% | 仅计算亏损日的波动 |",
            f"| 最大回撤 | {metrics.max_drawdown:.2f}% | 峰值法计算 |",
            f"| 最大回撤持续期 | {metrics.max_drawdown_duration} 天 | 从峰值到恢复的天数 |",
            f"| 最大回撤区间 | {self._fmt(metrics.max_drawdown_start)} ~ {self._fmt(metrics.max_drawdown_end)} | 回撤发生的起止日期 |",
            f"| 95% VaR | {metrics.var_95:.2f}% | 95%置信度下的最大日损失 |",
            f"| 95% CVaR | {metrics.cvar_95:.2f}% | 尾部风险期望损失 |",
            "",
            "## 3️⃣ 风险调整收益",
            "",
            "| 指标 | 数值 | 说明 |",
            "|------|------|------|",
            f"| 夏普比率 | {metrics.sharpe_ratio:.3f} | 每单位总风险的超额收益 |",
            f"| 索提诺比率 | {metrics.sortino_ratio:.3f} | 每单位下行风险的超额收益 |",
            f"| 卡玛比率 | {metrics.calmar_ratio:.3f} | 年化收益/最大回撤 |",
            "",
        ]
        
        # 夏普评级
        if metrics.sharpe_ratio >= 2:
            sharper_rating = "⭐⭐⭐ 优秀"
        elif metrics.sharpe_ratio >= 1:
            sharper_rating = "⭐⭐ 良好"
        elif metrics.sharpe_ratio >= 0.5:
            sharper_rating = "⭐ 一般"
        elif metrics.sharpe_ratio >= 0:
            sharper_rating = "较弱"
        else:
            sharper_rating = "❌ 亏损风险"
        
        lines.extend([
            f"> 夏普比率评级：{sharper_rating}（<0亏损, 0~0.5弱, 0.5~1一般, 1~2良好, >2优秀）",
            "",
        ])
        
        # 交易统计
        lines.extend([
            "## 4️⃣ 交易统计",
            "",
            "| 指标 | 数值 | 说明 |",
            "|------|------|------|",
            f"| 总交易次数 | {metrics.total_trades} 次 | 已平仓交易 |",
            f"| 盈利次数 | {metrics.win_trades} 次 | |",
            f"| 亏损次数 | {metrics.lose_trades} 次 | |",
            f"| 胜率 | {metrics.win_rate:.2f}% | 盈利笔数/总笔数 |",
            f"| 盈亏比 | {metrics.profit_loss_ratio:.2f}:1 | 平均盈利/平均亏损 |",
            f"| 平均盈利 | {metrics.avg_profit:,.2f} 元 ({metrics.avg_profit_pct:.2f}%) | |",
            f"| 平均亏损 | {metrics.avg_loss:,.2f} 元 ({metrics.avg_loss_pct:.2f}%) | |",
            f"| 平均持仓天数 | {metrics.avg_hold_days:.1f} 天 | |",
            f"| 最大连续盈利 | {metrics.max_consecutive_wins} 次 | |",
            f"| 最大连续亏损 | {metrics.max_consecutive_losses} 次 | |",
            "",
        ])
        
        # 期望值分析
        if metrics.win_rate > 0 and metrics.profit_loss_ratio > 0:
            # Kelly公式: f* = (p*b - q) / b, p=胜率, q=1-p, b=盈亏比
            p = metrics.win_rate / 100
            q = 1 - p
            b = metrics.profit_loss_ratio
            kelly = (p * b - q) / b if b > 0 else 0
            # 期望值 = p*avg_win - q*avg_loss（百分比）
            expected_value = p * metrics.avg_profit_pct - q * abs(metrics.avg_loss_pct)
            
            lines.extend([
                "## 5️⃣ 期望值与仓位建议",
                "",
                "| 指标 | 数值 | 说明 |",
                "|------|------|------|",
                f"| 每笔期望值 | {expected_value:.2f}% | 胜率×平均盈利 - 败率×平均亏损 |",
                f"| Kelly仓位比例 | {kelly*100:.1f}% | Kelly公式最优仓位（理论值，实际应打折） |",
                f"| 建议仓位 | {max(kelly*100*0.5, 0):.1f}% | 半Kelly策略（更安全） |",
                "",
            ])
        
        # 分布特征
        lines.extend([
            "## 6️⃣ 收益分布特征",
            "",
            "| 指标 | 数值 | 说明 |",
            "|------|------|------|",
            f"| 偏度 | {metrics.return_skewness:.3f} | >0右偏（大盈多），<0左偏（大亏多） |",
            f"| 峰度 | {metrics.return_kurtosis:.3f} | >0厚尾（极端收益多），<0薄尾 |",
            "",
        ])
        
        # 分策略分析（如有）
        if strategy_analysis:
            lines.extend([
                "## 7️⃣ 分策略绩效归因",
                "",
                "| 策略 | 交易次数 | 胜率 | 总盈利 | 平均收益 | 最大回撤 |",
                "|------|----------|------|--------|----------|----------|",
            ])
            for s in strategy_analysis:
                lines.append(
                    f"| {s['strategy']} | {s['total_trades']}次 | {s['win_rate']}% | "
                    f"{s['total_profit']:,.2f}元 | {s['avg_profit_pct']:.2f}% | "
                    f"{s['max_drawdown']:.2f}% |"
                )
            lines.append("")
        
        # 综合评价
        lines.extend([
            "## 8️⃣ 综合评价",
            "",
            self._generate_evaluation(metrics),
            "",
            "---",
            "",
            f"*报告由 StockAgent PerformanceCalculator 自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        report_content = "\n".join(lines)
        
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            filename = f"performance_metrics_{metrics.end_date or datetime.now().strftime('%Y%m%d')}.md"
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report_content)
            logger.info(f"✅ 绩效指标报告已保存到：{filepath}")
        
        return report_content
    
    # ============ 内部计算方法 ============
    
    def _calc_max_drawdown_detail(self, nav_records: List) -> Dict:
        """计算最大回撤详情（含持续期和起止日期）
        
        Args:
            nav_records: NavRecord列表
        
        Returns:
            Dict: {max_drawdown, duration, start_date, end_date}
        """
        if not nav_records:
            return {"max_drawdown": 0, "duration": 0, "start_date": "", "end_date": ""}
        
        peak = nav_records[0].nav
        peak_date = nav_records[0].date
        max_dd = 0
        dd_start = ""
        dd_end = ""
        max_duration = 0
        current_dd_start = ""
        
        for i, record in enumerate(nav_records):
            if record.nav > peak:
                # 新峰值，如果之前在回撤中则结束
                if current_dd_start:
                    duration = i - next(
                        j for j, r in enumerate(nav_records) if r.date == current_dd_start
                    )
                    if duration > max_duration:
                        max_duration = duration
                peak = record.nav
                peak_date = record.date
                current_dd_start = ""
            else:
                # 在回撤中
                if not current_dd_start:
                    current_dd_start = peak_date
                
                dd = (peak - record.nav) / peak * 100 if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
                    dd_start = peak_date
                    dd_end = record.date
        
        # 计算最大回撤持续期
        if dd_start and dd_end:
            try:
                start_dt = datetime.strptime(dd_start, "%Y%m%d")
                end_dt = datetime.strptime(dd_end, "%Y%m%d")
                duration = (end_dt - start_dt).days
            except ValueError:
                duration = 0
        else:
            duration = 0
        
        return {
            "max_drawdown": round(max_dd, 4),
            "duration": duration,
            "start_date": dd_start,
            "end_date": dd_end,
        }
    
    def _load_trade_stats(self, start_date: str = None, end_date: str = None) -> Optional[Dict]:
        """从交易历史文件加载交易统计
        
        Returns:
            Dict: 交易统计指标
        """
        # 查找交易历史文件
        trade_file = None
        if self.account_id:
            candidate = os.path.join(REAL_TRADING_DIR, f"paper_trade_history_{self.account_id}.json")
            if os.path.exists(candidate):
                trade_file = candidate
        
        if not trade_file:
            candidate = os.path.join(REAL_TRADING_DIR, "trade_history.json")
            if os.path.exists(candidate):
                trade_file = candidate
        
        if not trade_file:
            return None
        
        try:
            with open(trade_file, "r", encoding="utf-8") as f:
                trades = json.load(f)
            if not isinstance(trades, list):
                return None
            
            # 日期过滤
            if start_date:
                trades = [t for t in trades if t.get("sell_date", "") >= start_date]
            if end_date:
                trades = [t for t in trades if t.get("sell_date", "") <= end_date]
            
            if not trades:
                return None
            
            total = len(trades)
            win_trades = [t for t in trades if t.get("profit", 0) > 0]
            lose_trades = [t for t in trades if t.get("profit", 0) <= 0]
            
            win_rate = len(win_trades) / total * 100 if total > 0 else 0
            
            avg_profit = sum(t["profit"] for t in win_trades) / len(win_trades) if win_trades else 0
            avg_loss = abs(sum(t["profit"] for t in lose_trades) / len(lose_trades)) if lose_trades else 0
            avg_profit_pct = sum(t.get("profit_pct", 0) for t in win_trades) / len(win_trades) if win_trades else 0
            avg_loss_pct = abs(sum(t.get("profit_pct", 0) for t in lose_trades) / len(lose_trades)) if lose_trades else 0
            
            profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else 0
            avg_hold_days = sum(t.get("hold_days", 0) for t in trades) / total if total > 0 else 0
            
            # 最大连续盈亏
            max_consec_win = 0
            max_consec_loss = 0
            current_win = 0
            current_loss = 0
            for t in sorted(trades, key=lambda x: x.get("sell_date", "")):
                if t.get("profit", 0) > 0:
                    current_win += 1
                    current_loss = 0
                    max_consec_win = max(max_consec_win, current_win)
                else:
                    current_loss += 1
                    current_win = 0
                    max_consec_loss = max(max_consec_loss, current_loss)
            
            return {
                "total_trades": total,
                "win_trades": len(win_trades),
                "lose_trades": len(lose_trades),
                "win_rate": round(win_rate, 2),
                "profit_loss_ratio": round(profit_loss_ratio, 2),
                "avg_profit": round(avg_profit, 2),
                "avg_loss": round(avg_loss, 2),
                "avg_profit_pct": round(avg_profit_pct, 2),
                "avg_loss_pct": round(avg_loss_pct, 2),
                "avg_hold_days": round(avg_hold_days, 1),
                "max_consecutive_wins": max_consec_win,
                "max_consecutive_losses": max_consec_loss,
            }
        except (json.JSONDecodeError, OSError, KeyError, ZeroDivisionError) as e:
            logger.error(f"⚠️  加载交易统计失败: {e}")
            return None
    
    def _generate_evaluation(self, m: PerformanceMetrics) -> str:
        """生成综合评价文本
        
        基于关键指标的阈值规则引擎
        """
        evals = []
        
        # 收益评价
        if m.annualized_return > 20:
            evals.append("✅ 年化收益率优秀（>20%），策略盈利能力强")
        elif m.annualized_return > 10:
            evals.append("✅ 年化收益率良好（10%-20%），跑赢大部分主动基金")
        elif m.annualized_return > 0:
            evals.append("⚠️ 年化收益率一般（0%-10%），需评估是否覆盖交易成本")
        else:
            evals.append("❌ 年化收益率为负，策略需要改进")
        
        # 夏普评价
        if m.sharpe_ratio >= 1:
            evals.append("✅ 夏普比率≥1，风险调整后收益优秀")
        elif m.sharpe_ratio >= 0.5:
            evals.append("⚠️ 夏普比率0.5-1，风险调整后收益一般")
        elif m.sharpe_ratio >= 0:
            evals.append("⚠️ 夏普比率<0.5，承担的风险未得到足够补偿")
        else:
            evals.append("❌ 夏普比率为负，策略亏损风险大")
        
        # 回撤评价
        if m.max_drawdown < 10:
            evals.append("✅ 最大回撤<10%，风控能力优秀")
        elif m.max_drawdown < 20:
            evals.append("⚠️ 最大回撤10%-20%，风控一般，建议加强")
        else:
            evals.append("❌ 最大回撤>20%，风控能力不足，需降低仓位或优化止损")
        
        # 胜率+盈亏比评价
        if m.win_rate > 0 and m.profit_loss_ratio > 0:
            expected = m.win_rate / 100 * m.profit_loss_ratio - (1 - m.win_rate / 100)
            if expected > 0:
                evals.append(f"✅ 正期望策略（期望值={expected:.2f}），长期可盈利")
            else:
                evals.append(f"❌ 负期望策略（期望值={expected:.2f}），长期将亏损，需调整")
        
        # 索提诺 vs 夏普
        if m.sortino_ratio > m.sharpe_ratio * 1.5 and m.sharpe_ratio > 0:
            evals.append("✅ 索提诺比率显著高于夏普比率，上行捕获能力强，亏损日波动可控")
        elif m.sortino_ratio < m.sharpe_ratio * 0.5:
            evals.append("⚠️ 索提诺比率低于夏普比率，下行风险集中，需关注大额亏损日")
        
        return "\n".join(evals)
    
    @staticmethod
    def _fmt(date_str: str) -> str:
        """格式化日期"""
        if not date_str or len(date_str) != 8:
            return date_str or "N/A"
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description="绩效指标计算器")
    parser.add_argument("--account", help="模拟账户ID")
    parser.add_argument("--start", help="统计起始日期(YYYYMMDD)")
    parser.add_argument("--end", help="统计结束日期(YYYYMMDD)")
    parser.add_argument("--output-dir", help="报告输出目录")
    args = parser.parse_args()
    
    # 从NavTracker加载净值数据
    from nav_tracker import NavTracker
    
    tracker = NavTracker(args.account)
    nav_records = tracker.get_nav_history(args.start, args.end)
    
    # 加载分策略分析
    strategy_analysis = None
    try:
        analyzer = PerformanceAnalyzer(f"paper_trade_history_{tracker.account_id}.json")
        strategy_analysis = analyzer.get_strategy_analysis()
    except Exception:
        pass
    
    calculator = PerformanceCalculator(tracker.account_id)
    metrics = calculator.calculate(nav_records, args.start, args.end)
    report = calculator.generate_report(metrics, args.output_dir, strategy_analysis)
    logger.info(report)


if __name__ == "__main__":
    main()
