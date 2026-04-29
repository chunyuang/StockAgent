#!/usr/bin/env python3
"""
每日调仓Markdown报告生成器
功能：盘后自动读取当日信号、持仓、交易记录，生成完整调仓决策报告

报告内容：
1. 账户概览（资金余额、总权益、收益率、最大回撤）
2. 市场情绪周期分析
3. 今日调仓操作明细（买入/卖出/持仓不变）
4. 调仓前后持仓对比
5. 风控检查结果
6. 次日交易计划
"""
import sys
import logging

logger = logging.getLogger(__name__)
import os
import json
from datetime import datetime
from typing import Dict, List, Optional

# 项目路径配置
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', 'workspace', 'StockAgent'))
REAL_TRADING_DIR = os.path.join(PROJECT_ROOT, 'real_trading')

sys.path.insert(0, os.path.join(PROJECT_ROOT, 'AgentServer'))
sys.path.insert(0, REAL_TRADING_DIR)

from paper_trading import PaperTradingEngine, PaperAccount
from position_manager import PositionManager, Position
from performance_analyzer import PerformanceAnalyzer


class DailyRebalanceReportGenerator:
    """每日调仓Markdown报告生成器
    
    从模拟交易引擎、持仓管理器、绩效分析器和信号文件中聚合数据，
    生成结构化的调仓决策报告，供交易员/策略师审阅。
    """
    
    def __init__(self, account_id: str = None):
        """初始化报告生成器
        
        Args:
            account_id: 模拟账户ID，None则使用第一个活跃账户
        """
        self.engine = PaperTradingEngine()
        
        if account_id:
            self.account_id = account_id
        else:
            # 默认使用第一个活跃账户
            self.account_id = next(
                (acc_id for acc_id, acc in self.engine.accounts.items() if acc.status == "active"),
                None
            )
        
        if not self.account_id:
            raise ValueError("无可用活跃模拟账户")
    
    def generate(self, trade_date: str = None, output_dir: str = None) -> str:
        """生成每日调仓Markdown报告
        
        Args:
            trade_date: 交易日期（YYYYMMDD），默认当天
            output_dir: 报告输出目录，None则不保存文件
        
        Returns:
            str: Markdown格式的调仓报告
        """
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")
        
        account = self.engine.accounts[self.account_id]
        pos_manager = self.engine.position_managers[self.account_id]
        
        # 加载各类数据
        signal_data = self._load_signal(trade_date)
        current_positions = pos_manager.get_positions()
        analyzer = PerformanceAnalyzer(f"paper_trade_history_{self.account_id}.json")
        basic_stats = analyzer.get_basic_stats()
        monthly_stats = analyzer.get_monthly_stats()
        strategy_analysis = analyzer.get_strategy_analysis()
        
        # 计算持仓市值
        total_market_value = sum(p["shares"] * p["buy_price"] for p in current_positions)
        total_equity = account.current_balance + total_market_value
        
        # === 报告正文 ===
        report_lines = [
            f"# 📋 每日调仓报告 - {self._format_date(trade_date)}",
            "",
            f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"> 账户：{account.name}（{self.account_id}）",
            "",
            "---",
            "",
            "## 1️⃣ 账户概览",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 初始资金 | {account.initial_balance:,.2f} 元 |",
            f"| 可用余额 | {account.current_balance:,.2f} 元 |",
            f"| 持仓市值 | {total_market_value:,.2f} 元 |",
            f"| 总权益 | {total_equity:,.2f} 元 |",
            f"| 累计盈亏 | {account.total_profit:,.2f} 元（{account.total_profit_pct:.2f}%） |",
            f"| 最大回撤 | {account.max_drawdown:.2f}% |",
            f"| 仓位比例 | {total_market_value / total_equity * 100:.1f}% |" if total_equity > 0 else "| 仓位比例 | 0% |",
            f"| 持仓股票数 | {len(current_positions)} 只 |",
            "",
        ]
        
        # === 市场情绪 ===
        if signal_data and signal_data.get("sentiment"):
            sentiment = signal_data["sentiment"]
            level_map = {
                "euphoria": "🟢 贪婪（高位风险区）",
                "optimism": "🟢 乐观（偏多）",
                "neutral": "🟡 中性（震荡）",
                "repair": "🟡 修复期（偏弱）",
                "pessimism": "🔴 悲观（偏空）",
                "panic": "🔴 恐慌（低位机会区）",
            }
            level_text = level_map.get(sentiment.get("level", ""), sentiment.get("level", "未知"))
            
            report_lines.extend([
                "## 2️⃣ 市场情绪周期",
                "",
                "| 指标 | 数值 |",
                "|------|------|",
                f"| 情绪阶段 | {level_text} |",
                f"| 情绪评分 | {sentiment.get('score', 'N/A')} |",
                f"| 仓位上限 | {sentiment.get('position_limit', 0.7) * 100:.0f}% |",
                f"| 允许策略 | {', '.join(sentiment.get('allowed_strategies', []))} |",
                f"| 止损调整系数 | {sentiment.get('stop_loss_adjust', 1.0)} |",
                f"| 止盈调整系数 | {sentiment.get('take_profit_adjust', 1.0)} |",
                "",
            ])
        else:
            report_lines.extend([
                "## 2️⃣ 市场情绪周期",
                "",
                "> ⚠️ 未获取到当日情绪数据",
                "",
            ])
        
        # === 调仓操作 ===
        report_lines.extend([
            "## 3️⃣ 今日调仓操作",
            "",
        ])
        
        # 交易计划
        if signal_data:
            trading_plan = signal_data.get("trading_plan", "未生成交易计划")
            force_empty = signal_data.get("force_empty", False)
            
            report_lines.extend([
                f"**交易计划**：{trading_plan}",
                "",
                f"**强制空仓**：{'是 ✅' if force_empty else '否'}",
                "",
            ])
            
            # 今日信号标的
            signals = signal_data.get("signals", [])
            if signals:
                report_lines.extend([
                    "### 📥 拟买入标的",
                    "",
                    "| 代码 | 名称 | 信号价 | 策略 | 理由 |",
                    "|------|------|--------|------|------|",
                ])
                for sig in signals:
                    report_lines.append(
                        f"| {sig.get('ts_code', '')} | {sig.get('name', '')} | "
                        f"{sig.get('price', 0):.2f} | {sig.get('strategy', '未知')} | "
                        f"{sig.get('reason', '')} |"
                    )
                report_lines.append("")
            else:
                report_lines.extend([
                    "### 📥 拟买入标的",
                    "",
                    "> 今日无符合条件的买入信号",
                    "",
                ])
        else:
            report_lines.extend([
                "> ⚠️ 未找到当日信号文件，无法确定调仓方向",
                "",
            ])
        
        # === 当前持仓详情 ===
        report_lines.extend([
            "## 4️⃣ 当前持仓明细",
            "",
        ])
        
        if current_positions:
            report_lines.extend([
                f"共持有 **{len(current_positions)}** 只股票：",
                "",
                "| 代码 | 名称 | 买入日期 | 成本价 | 持股数 | 总成本 | 止损价 | 止盈价 | 持仓天数 | 策略 |",
                "|------|------|----------|--------|--------|--------|--------|--------|----------|------|",
            ])
            for pos in current_positions:
                report_lines.append(
                    f"| {pos['ts_code']} | {pos['name']} | {self._format_date(pos['buy_date'])} | "
                    f"{pos['buy_price']:.2f} | {pos['shares']} | {pos['total_cost']:,.2f} | "
                    f"{pos['stop_loss_price']:.2f} | {pos['take_profit_price']:.2f} | "
                    f"{pos['hold_days']}天 | {pos['strategy']} |"
                )
            report_lines.extend([
                "",
                f"**持仓总成本**：{sum(p['total_cost'] for p in current_positions):,.2f} 元",
                "",
            ])
        else:
            report_lines.extend([
                "> 当前空仓，无持仓股票",
                "",
            ])
        
        # === 调仓决策分析 ===
        report_lines.extend([
            "## 5️⃣ 调仓决策分析",
            "",
        ])
        
        if signal_data and not signal_data.get("force_empty"):
            signals = signal_data.get("signals", [])
            signal_codes = {s.get("ts_code") for s in signals} if signals else set()
            position_codes = {p["ts_code"] for p in current_positions}
            
            # 需要卖出的（持仓中不在新信号中）
            to_sell = position_codes - signal_codes
            # 需要买入的（新信号中不在持仓中）
            to_buy = signal_codes - position_codes
            # 继续持有的
            to_hold = position_codes & signal_codes
            
            if to_sell:
                report_lines.extend([
                    "### 📤 需卖出（不在新信号中）",
                    "",
                ])
                for pos in current_positions:
                    if pos["ts_code"] in to_sell:
                        report_lines.append(
                            f"- **{pos['name']}**（{pos['ts_code']}）：持仓{pos['hold_days']}天，"
                            f"成本{pos['buy_price']:.2f}元，建议收盘价卖出"
                        )
                report_lines.append("")
            
            if to_buy:
                report_lines.extend([
                    "### 📥 需买入（新信号标的）",
                    "",
                ])
                # 计算每只分配金额
                position_limit = signal_data.get("sentiment", {}).get("position_limit", 0.7)
                investable = account.current_balance + sum(
                    p["total_cost"] for p in current_positions if p["ts_code"] in to_sell
                )
                per_stock = investable * position_limit / max(len(signals), 1) if signals else 0
                
                for sig in signals:
                    if sig.get("ts_code") in to_buy:
                        buy_price = sig.get("price", 0)
                        shares = int(per_stock / buy_price / 100) * 100 if buy_price > 0 else 0
                        report_lines.append(
                            f"- **{sig.get('name', '')}**（{sig.get('ts_code', '')}）："
                            f"信号价{buy_price:.2f}元，建议买入{shares}股（约{per_stock:,.0f}元）"
                        )
                report_lines.append("")
            
            if to_hold:
                report_lines.extend([
                    "### ✅ 继续持有",
                    "",
                ])
                for pos in current_positions:
                    if pos["ts_code"] in to_hold:
                        report_lines.append(
                            f"- **{pos['name']}**（{pos['ts_code']}）：持仓{pos['hold_days']}天，继续持有"
                        )
                report_lines.append("")
            
            if not to_sell and not to_buy:
                report_lines.extend([
                    "> 当前无调仓操作需求",
                    "",
                ])
        elif signal_data and signal_data.get("force_empty"):
            report_lines.extend([
                "### 🚫 强制空仓信号",
                "",
                "> 情绪周期触发强制空仓条件，建议清空所有持仓",
                "",
            ])
            if current_positions:
                for pos in current_positions:
                    report_lines.append(
                        f"- 📤 **{pos['name']}**（{pos['ts_code']}）：持仓{pos['hold_days']}天，建议全部卖出"
                    )
                report_lines.append("")
        
        # === 风控检查 ===
        report_lines.extend([
            "## 6️⃣ 风控检查",
            "",
        ])
        
        if current_positions:
            risk_items = []
            for pos in current_positions:
                risks = []
                # 超期检查
                if pos["hold_days"] >= 3:
                    risks.append(f"⚠️ 持仓超期：{pos['hold_days']}天 ≥ 3天上限")
                # 止损价接近度（模拟）
                risks_text = " | ".join(risks) if risks else "✅ 正常"
                risk_items.append((pos["ts_code"], pos["name"], risks_text))
            
            report_lines.extend([
                "| 代码 | 名称 | 风控状态 |",
                "|------|------|----------|",
            ])
            for code, name, status in risk_items:
                report_lines.append(f"| {code} | {name} | {status} |")
            report_lines.append("")
        else:
            report_lines.extend([
                "> 当前空仓，无风控检查对象",
                "",
            ])
        
        # === 绩效统计摘要 ===
        report_lines.extend([
            "## 7️⃣ 绩效统计摘要",
            "",
        ])
        
        if basic_stats:
            report_lines.extend([
                "| 指标 | 数值 |",
                "|------|------|",
                f"| 总交易次数 | {basic_stats.get('total_trades', 0)} 次 |",
                f"| 胜率 | {basic_stats.get('win_rate', 0):.2f}% |",
                f"| 盈亏比 | {basic_stats.get('profit_loss_ratio', 0):.2f}:1 |",
                f"| 总盈利 | {basic_stats.get('total_profit', 0):,.2f} 元 |",
                f"| 平均每笔收益 | {basic_stats.get('avg_profit_pct', 0):.2f}% |",
                f"| 最大回撤 | {basic_stats.get('max_drawdown', 0):.2f}% |",
                f"| 平均持仓天数 | {basic_stats.get('avg_hold_days', 0):.1f} 天 |",
                "",
            ])
        else:
            report_lines.extend([
                "> 暂无交易记录",
                "",
            ])
        
        # === 月度绩效 ===
        if monthly_stats:
            report_lines.extend([
                "### 📆 月度收益统计",
                "",
                "| 月份 | 交易次数 | 胜率 | 月度盈利 | 平均收益 |",
                "|------|----------|------|----------|----------|",
            ])
            for m in monthly_stats:
                profit_icon = "📈" if m["total_profit"] >= 0 else "📉"
                report_lines.append(
                    f"| {m['month']} | {m['total_trades']}次 | {m['win_rate']}% | "
                    f"{profit_icon} {m['total_profit']:,.2f}元 | {m['avg_profit_pct']:.2f}% |"
                )
            report_lines.append("")
        
        # === 策略分析 ===
        if strategy_analysis:
            report_lines.extend([
                "### 🎯 分策略表现",
                "",
                "| 策略 | 交易次数 | 胜率 | 总盈利 | 平均收益 | 最大回撤 | 平均持仓天数 |",
                "|------|----------|------|--------|----------|----------|--------------|",
            ])
            for s in strategy_analysis:
                report_lines.append(
                    f"| {s['strategy']} | {s['total_trades']}次 | {s['win_rate']}% | "
                    f"{s['total_profit']:,.2f}元 | {s['avg_profit_pct']:.2f}% | "
                    f"{s['max_drawdown']:.2f}% | {s['avg_hold_days']}天 |"
                )
            report_lines.append("")
        
        # === 次日交易计划 ===
        report_lines.extend([
            "## 8️⃣ 次日交易计划",
            "",
        ])
        
        if signal_data:
            signals = signal_data.get("signals", [])
            if signal_data.get("force_empty"):
                report_lines.extend([
                    "### 计划：全仓清空",
                    "",
                    "> 情绪周期触发强制空仓，次日开盘卖出所有持仓",
                    "",
                ])
            elif signals:
                position_limit = signal_data.get("sentiment", {}).get("position_limit", 0.7)
                report_lines.extend([
                    f"### 计划：调仓至 {len(signals)} 只标的（仓位上限{position_limit*100:.0f}%）",
                    "",
                    "**操作步骤**：",
                    "",
                    "1. 竞价阶段观察：确认信号标的开盘价在合理区间",
                    "2. 先卖出不在新信号中的持仓",
                    "3. 回款后按信号顺序买入新标的",
                    f"4. 每只标的分配金额 ≈ 总权益 × {position_limit*100:.0f}% ÷ {len(signals)}",
                    "",
                    "**注意事项**：",
                    "",
                    "- 超短策略严格止损（2%）止盈（7%），持仓不超过3天",
                    "- 竞价高开超过3%的标的放弃买入",
                    "- 滑点按0.2%估算",
                    "",
                ])
            else:
                report_lines.extend([
                    "### 计划：空仓观望",
                    "",
                    "> 今日无符合条件的信号标的，次日保持空仓",
                    "",
                ])
        else:
            report_lines.extend([
                "> ⚠️ 无当日信号数据，请手动确认交易计划",
                "",
            ])
        
        # === 页脚 ===
        report_lines.extend([
            "---",
            "",
            f"*报告由 StockAgent DailyRebalanceReportGenerator 自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        report_content = "\n".join(report_lines)
        
        # 保存文件
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            filename = f"rebalance_report_{trade_date}.md"
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report_content)
            logger.info(f"✅ 调仓报告已保存到：{filepath}")
        
        return report_content
    
    def _load_signal(self, trade_date: str) -> Optional[Dict]:
        """加载当日信号文件
        
        搜索路径：real_trading/signals/{date}.json
        """
        signal_file = os.path.join(REAL_TRADING_DIR, "signals", f"{trade_date}.json")
        if not os.path.exists(signal_file):
            # 尝试找最近的信号文件
            signals_dir = os.path.join(REAL_TRADING_DIR, "signals")
            if os.path.isdir(signals_dir):
                files = sorted(
                    [f for f in os.listdir(signals_dir) if f.endswith(".json")],
                    reverse=True
                )
                if files:
                    latest = os.path.join(signals_dir, files[0])
                    logger.info(f"ℹ️  未找到{trade_date}的信号文件，使用最近的信号文件：{files[0]}")
                    signal_file = latest
                else:
                    logger.warning(f"⚠️  信号目录为空，无可用信号文件")
                    return None
            else:
                logger.warning(f"⚠️  信号目录不存在：{signals_dir}")
                return None
        
        try:
            with open(signal_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"❌ 加载信号文件失败: {e}")
            return None
    
    @staticmethod
    def _format_date(date_str: str) -> str:
        """格式化日期：YYYYMMDD → YYYY-MM-DD"""
        if not date_str or len(date_str) != 8:
            return date_str
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description="每日调仓报告生成器")
    parser.add_argument("--date", help="交易日期(YYYYMMDD)，默认当天")
    parser.add_argument("--account", help="模拟账户ID")
    parser.add_argument("--output-dir", help="报告输出目录")
    args = parser.parse_args()
    
    generator = DailyRebalanceReportGenerator(args.account)
    report = generator.generate(args.date, args.output_dir)
    logger.info(report)


if __name__ == "__main__":
    main()
