#!/usr/bin/env python3
"""
业绩跟踪模块 - 每日更新净值和月度收益统计
功能：
1. 每日盘后计算并记录账户净值（NAV）
2. 生成净值曲线数据
3. 月度收益统计（收益率/最大回撤/胜率/交易次数）
4. 支持多账户并行跟踪
5. 输出Markdown格式的净值与月度收益报告

数据持久化：
- nav_history/{account_id}_nav.json — 每日净值序列
- monthly_stats/{account_id}_monthly.json — 月度收益统计
"""
import sys
import logging

logger = logging.getLogger(__name__)
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field

# 项目路径配置
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', 'workspace', 'StockAgent'))
REAL_TRADING_DIR = os.path.join(PROJECT_ROOT, 'real_trading')

sys.path.insert(0, os.path.join(PROJECT_ROOT, 'AgentServer'))
sys.path.insert(0, REAL_TRADING_DIR)

from paper_trading import PaperTradingEngine, PaperAccount
from position_manager import PositionManager


# ============ 数据模型 ============

@dataclass
class NavRecord:
    """单日净值记录
    
    Attributes:
        date: 交易日（YYYYMMDD）
        nav: 单位净值（基于初始资金=1.0）
        total_equity: 总权益 = 可用余额 + 持仓市值
        cash: 可用余额
        market_value: 持仓市值（按收盘价/成本价估算）
        daily_return: 当日收益率（%）
        cumulative_return: 累计收益率（%）
        position_count: 持仓股票数
        position_ratio: 仓位比例（%）
    """
    date: str
    nav: float
    total_equity: float
    cash: float
    market_value: float
    daily_return: float
    cumulative_return: float
    position_count: int
    position_ratio: float


@dataclass
class MonthlyStats:
    """月度收益统计
    
    Attributes:
        month: 月份（YYYYMM）
        start_nav: 月初净值
        end_nav: 月末净值
        monthly_return: 月度收益率（%）
        max_nav: 月内最高净值
        min_nav: 月内最低净值
        max_drawdown: 月内最大回撤（%）
        trading_days: 交易天数
        win_days: 盈利天数
        loss_days: 亏损天数
        win_day_rate: 日胜率（%）
        total_trades: 当月交易次数（从交易历史获取）
    """
    month: str
    start_nav: float
    end_nav: float
    monthly_return: float
    max_nav: float
    min_nav: float
    max_drawdown: float
    trading_days: int
    win_days: int
    loss_days: int
    win_day_rate: float
    total_trades: int = 0


# ============ 净值跟踪器 ============

class NavTracker:
    """净值跟踪器
    
    核心职责：
    1. 每日盘后调用 update_daily_nav() 计算并记录当日净值
    2. 查询历史净值序列
    3. 计算月度收益统计
    4. 生成净值/月度收益Markdown报告
    
    净值计算规则：
    - 初始净值 = 1.0（对应初始资金）
    - 每日净值 = 总权益 / 初始资金
    - 总权益 = 可用余额 + 持仓市值
    - 持仓市值暂按成本价估算（可扩展接入实时行情）
    - 当日收益率 = (今日净值 / 昨日净值 - 1) × 100%
    """
    
    def __init__(self, account_id: str = None, data_dir: str = None):
        """初始化净值跟踪器
        
        Args:
            account_id: 模拟账户ID，None则使用第一个活跃账户
            data_dir: 数据存储目录，默认 real_trading/nav_history
        """
        self.engine = PaperTradingEngine()
        
        if account_id:
            self.account_id = account_id
        else:
            self.account_id = next(
                (acc_id for acc_id, acc in self.engine.accounts.items() if acc.status == "active"),
                None
            )
        
        if not self.account_id:
            raise ValueError("无可用活跃模拟账户")
        
        self.account = self.engine.accounts[self.account_id]
        self.pos_manager = self.engine.position_managers[self.account_id]
        
        # 数据存储目录
        if data_dir:
            self.data_dir = data_dir
        else:
            self.data_dir = os.path.join(REAL_TRADING_DIR, "nav_history")
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 加载历史净值
        self.nav_file = os.path.join(self.data_dir, f"{self.account_id}_nav.json")
        self.nav_records: List[NavRecord] = self._load_nav_history()
    
    # ============ 核心方法：每日更新净值 ============
    
    def update_daily_nav(self, trade_date: str = None) -> NavRecord:
        """每日盘后更新净值
        
        计算流程：
        1. 获取账户余额和持仓
        2. 计算持仓市值和总权益
        3. 计算当日净值和收益率
        4. 追加到净值历史序列
        5. 持久化到JSON文件
        
        Args:
            trade_date: 交易日（YYYYMMDD），默认当天
        
        Returns:
            NavRecord: 当日净值记录
        """
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")
        
        # 检查是否已有当日记录，有则更新而非追加
        existing_idx = next(
            (i for i, r in enumerate(self.nav_records) if r.date == trade_date),
            None
        )
        
        # 计算持仓市值
        positions = self.pos_manager.get_positions()
        market_value = sum(p["shares"] * p.get("current_price", p["buy_price"]) for p in positions)
        
        # 计算总权益
        total_equity = self.account.current_balance + market_value
        
        # 计算净值
        nav = total_equity / self.account.initial_balance if self.account.initial_balance > 0 else 1.0
        
        # 计算当日收益率
        if self.nav_records and existing_idx is None:
            prev_nav = self.nav_records[-1].nav
        elif existing_idx is not None and existing_idx > 0:
            prev_nav = self.nav_records[existing_idx - 1].nav
        else:
            prev_nav = 1.0
        
        daily_return = (nav / prev_nav - 1) * 100 if prev_nav > 0 else 0.0
        
        # 累计收益率
        cumulative_return = (nav - 1.0) * 100
        
        # 仓位比例
        position_ratio = (market_value / total_equity * 100) if total_equity > 0 else 0.0
        
        record = NavRecord(
            date=trade_date,
            nav=round(nav, 6),
            total_equity=round(total_equity, 2),
            cash=round(self.account.current_balance, 2),
            market_value=round(market_value, 2),
            daily_return=round(daily_return, 4),
            cumulative_return=round(cumulative_return, 4),
            position_count=len(positions),
            position_ratio=round(position_ratio, 2),
        )
        
        # 更新或追加
        if existing_idx is not None:
            self.nav_records[existing_idx] = record
            logger.info(f"✅ 更新 {trade_date} 净值：NAV={record.nav:.4f}，日收益={record.daily_return:.2f}%")
        else:
            self.nav_records.append(record)
            logger.info(f"✅ 记录 {trade_date} 净值：NAV={record.nav:.4f}，日收益={record.daily_return:.2f}%")
        
        # 按日期排序
        self.nav_records.sort(key=lambda r: r.date)
        
        # 持久化
        self._save_nav_history()
        
        return record
    
    # ============ 月度统计 ============
    
    def compute_monthly_stats(self) -> List[MonthlyStats]:
        """计算月度收益统计
        
        基于已有的净值记录，按月汇总：
        - 月度收益率 = 月末净值/月初净值 - 1
        - 月内最大回撤 = 峰值法
        - 日胜率 = 盈利天数/交易天数
        - 交易次数从交易历史文件获取
        
        Returns:
            List[MonthlyStats]: 按月份升序排列的统计列表
        """
        if not self.nav_records:
            return []
        
        # 按月分组
        monthly_navs: Dict[str, List[NavRecord]] = {}
        for record in self.nav_records:
            month = record.date[:6]
            if month not in monthly_navs:
                monthly_navs[month] = []
            monthly_navs[month].append(record)
        
        # 加载交易历史获取每月交易次数
        trade_count_by_month = self._get_trade_count_by_month()
        
        result = []
        for month in sorted(monthly_navs.keys()):
            records = monthly_navs[month]
            
            start_nav = records[0].nav
            end_nav = records[-1].nav
            monthly_return = (end_nav / start_nav - 1) * 100 if start_nav > 0 else 0
            
            max_nav = max(r.nav for r in records)
            min_nav = min(r.nav for r in records)
            
            # 月内最大回撤（峰值法）
            peak = records[0].nav
            max_dd = 0.0
            for r in records:
                if r.nav > peak:
                    peak = r.nav
                dd = (peak - r.nav) / peak * 100 if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
            
            trading_days = len(records)
            win_days = len([r for r in records if r.daily_return > 0])
            loss_days = len([r for r in records if r.daily_return < 0])
            flat_days = trading_days - win_days - loss_days
            win_day_rate = win_days / trading_days * 100 if trading_days > 0 else 0
            
            total_trades = trade_count_by_month.get(month, 0)
            
            stats = MonthlyStats(
                month=month,
                start_nav=round(start_nav, 6),
                end_nav=round(end_nav, 6),
                monthly_return=round(monthly_return, 4),
                max_nav=round(max_nav, 6),
                min_nav=round(min_nav, 6),
                max_drawdown=round(max_dd, 4),
                trading_days=trading_days,
                win_days=win_days,
                loss_days=loss_days,
                win_day_rate=round(win_day_rate, 2),
                total_trades=total_trades,
            )
            result.append(stats)
        
        return result
    
    # ============ 报告生成 ============
    
    def generate_report(self, trade_date: str = None, output_dir: str = None) -> str:
        """生成净值与月度收益统计Markdown报告
        
        Args:
            trade_date: 报告日期（YYYYMMDD），默认当天
            output_dir: 报告输出目录
        
        Returns:
            str: Markdown格式报告
        """
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")
        
        monthly_stats = self.compute_monthly_stats()
        
        lines = [
            f"# 📈 净值与月度收益统计报告 - {self._format_date(trade_date)}",
            "",
            f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"> 账户：{self.account.name}（{self.account_id}）",
            f"> 初始资金：{self.account.initial_balance:,.2f} 元",
            "",
            "---",
            "",
            "## 1️⃣ 最新净值",
            "",
        ]
        
        if self.nav_records:
            latest = self.nav_records[-1]
            lines.extend([
                "| 指标 | 数值 |",
                "|------|------|",
                f"| 日期 | {self._format_date(latest.date)} |",
                f"| 单位净值 | {latest.nav:.4f} |",
                f"| 总权益 | {latest.total_equity:,.2f} 元 |",
                f"| 可用余额 | {latest.cash:,.2f} 元 |",
                f"| 持仓市值 | {latest.market_value:,.2f} 元 |",
                f"| 当日收益率 | {latest.daily_return:.2f}% |",
                f"| 累计收益率 | {latest.cumulative_return:.2f}% |",
                f"| 仓位比例 | {latest.position_ratio:.1f}% |",
                f"| 持仓股票数 | {latest.position_count} 只 |",
                "",
            ])
        else:
            lines.extend([
                "> 暂无净值记录，请先执行 update_daily_nav()",
                "",
            ])
        
        # === 净值曲线数据 ===
        lines.extend([
            "## 2️⃣ 历史净值曲线",
            "",
        ])
        
        if self.nav_records:
            lines.extend([
                "| 日期 | 净值 | 日收益率 | 累计收益率 | 仓位比例 |",
                "|------|------|----------|------------|----------|",
            ])
            # 显示最近30条或全部
            display_records = self.nav_records[-30:] if len(self.nav_records) > 30 else self.nav_records
            for r in display_records:
                ret_icon = "📈" if r.daily_return > 0 else ("📉" if r.daily_return < 0 else "➖")
                lines.append(
                    f"| {self._format_date(r.date)} | {r.nav:.4f} | "
                    f"{ret_icon} {r.daily_return:.2f}% | {r.cumulative_return:.2f}% | "
                    f"{r.position_ratio:.1f}% |"
                )
            if len(self.nav_records) > 30:
                lines.append(f"\n> 仅显示最近30条，共{len(self.nav_records)}条记录")
            lines.append("")
        else:
            lines.extend([
                "> 暂无净值数据",
                "",
            ])
        
        # === 月度收益统计 ===
        lines.extend([
            "## 3️⃣ 月度收益统计",
            "",
        ])
        
        if monthly_stats:
            lines.extend([
                "| 月份 | 月初净值 | 月末净值 | 月度收益率 | 月内最大回撤 | 交易日数 | 盈利天数 | 亏损天数 | 日胜率 | 交易次数 |",
                "|------|----------|----------|------------|--------------|----------|----------|----------|--------|----------|",
            ])
            for m in monthly_stats:
                ret_icon = "📈" if m.monthly_return >= 0 else "📉"
                lines.append(
                    f"| {m.month} | {m.start_nav:.4f} | {m.end_nav:.4f} | "
                    f"{ret_icon} {m.monthly_return:.2f}% | {m.max_drawdown:.2f}% | "
                    f"{m.trading_days} | {m.win_days} | {m.loss_days} | "
                    f"{m.win_day_rate:.1f}% | {m.total_trades} |"
                )
            lines.append("")
        else:
            lines.extend([
                "> 暂无月度统计数据",
                "",
            ])
        
        # === 月度汇总 ===
        if monthly_stats:
            total_months = len(monthly_stats)
            avg_monthly_return = sum(m.monthly_return for m in monthly_stats) / total_months
            best_month = max(monthly_stats, key=lambda m: m.monthly_return)
            worst_month = min(monthly_stats, key=lambda m: m.monthly_return)
            avg_win_rate = sum(m.win_day_rate for m in monthly_stats) / total_months
            
            lines.extend([
                "## 4️⃣ 月度表现汇总",
                "",
                "| 指标 | 数值 |",
                "|------|------|",
                f"| 统计月数 | {total_months} 个月 |",
                f"| 平均月度收益率 | {avg_monthly_return:.2f}% |",
                f"| 最佳月份 | {best_month.month}（{best_month.monthly_return:.2f}%） |",
                f"| 最差月份 | {worst_month.month}（{worst_month.monthly_return:.2f}%） |",
                f"| 平均日胜率 | {avg_win_rate:.1f}% |",
                "",
            ])
        
        # === 页脚 ===
        lines.extend([
            "---",
            "",
            f"*报告由 StockAgent NavTracker 自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        report_content = "\n".join(lines)
        
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            filename = f"nav_report_{trade_date}.md"
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report_content)
            logger.info(f"✅ 净值报告已保存到：{filepath}")
        
        return report_content
    
    # ============ 查询方法 ============
    
    def get_nav_history(self, start_date: str = None, end_date: str = None) -> List[NavRecord]:
        """查询净值历史
        
        Args:
            start_date: 起始日期（YYYYMMDD）
            end_date: 结束日期（YYYYMMDD）
        
        Returns:
            List[NavRecord]: 净值记录列表
        """
        if not start_date and not end_date:
            return self.nav_records
        
        return [
            r for r in self.nav_records
            if (not start_date or r.date >= start_date)
            and (not end_date or r.date <= end_date)
        ]
    
    def get_latest_nav(self) -> Optional[NavRecord]:
        """获取最新净值记录"""
        return self.nav_records[-1] if self.nav_records else None
    
    def get_nav_at(self, date: str) -> Optional[NavRecord]:
        """获取指定日期的净值"""
        return next((r for r in self.nav_records if r.date == date), None)
    
    def export_nav_csv(self, output_path: str = None) -> str:
        """导出净值序列为CSV格式
        
        Args:
            output_path: 输出文件路径，None则返回CSV字符串
        
        Returns:
            str: CSV内容或文件路径提示
        """
        if not self.nav_records:
            return ""
        
        header = "date,nav,total_equity,cash,market_value,daily_return,cumulative_return,position_count,position_ratio"
        rows = [
            f"{r.date},{r.nav},{r.total_equity},{r.cash},{r.market_value},"
            f"{r.daily_return},{r.cumulative_return},{r.position_count},{r.position_ratio}"
            for r in self.nav_records
        ]
        csv_content = header + "\n" + "\n".join(rows)
        
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(csv_content)
            logger.info(f"✅ CSV已导出到：{output_path}")
        
        return csv_content
    
    # ============ 内部方法 ============
    
    def _load_nav_history(self) -> List[NavRecord]:
        """加载历史净值记录"""
        if not os.path.exists(self.nav_file):
            return []
        
        try:
            with open(self.nav_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                logger.error(f"⚠️  净值数据格式异常，初始化空")
                return []
            records = []
            for item in data:
                try:
                    records.append(NavRecord(**item))
                except (TypeError, KeyError) as e:
                    logger.error(f"⚠️  跳过异常净值记录: {e}")
            logger.info(f"✅ 加载净值历史成功，共{len(records)}条记录")
            return records
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"❌ 加载净值历史失败: {e}")
            return []
    
    def _save_nav_history(self):
        """保存净值历史到JSON"""
        try:
            data = [asdict(r) for r in self.nav_records]
            with open(self.nav_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError) as e:
            logger.error(f"❌ 保存净值历史失败: {e}")
    
    def _get_trade_count_by_month(self) -> Dict[str, int]:
        """从交易历史文件获取每月交易次数
        
        Returns:
            Dict[str, int]: {YYYYMM: count}
        """
        trade_history_file = os.path.join(
            REAL_TRADING_DIR,
            f"paper_trade_history_{self.account_id}.json"
        )
        
        if not os.path.exists(trade_history_file):
            # 也尝试通用的trade_history.json
            trade_history_file = os.path.join(REAL_TRADING_DIR, "trade_history.json")
        
        if not os.path.exists(trade_history_file):
            return {}
        
        try:
            with open(trade_history_file, "r", encoding="utf-8") as f:
                trades = json.load(f)
            if not isinstance(trades, list):
                return {}
            
            count_map = {}
            for t in trades:
                sell_date = t.get("sell_date", "")
                if sell_date and len(sell_date) >= 6:
                    month = sell_date[:6]
                    count_map[month] = count_map.get(month, 0) + 1
            return count_map
        except (json.JSONDecodeError, OSError, KeyError):
            return {}
    
    @staticmethod
    def _format_date(date_str: str) -> str:
        """格式化日期：YYYYMMDD → YYYY-MM-DD"""
        if not date_str or len(date_str) != 8:
            return date_str
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description="净值跟踪与月度收益统计")
    parser.add_argument("--action", required=True,
                        choices=["update", "report", "history", "export-csv"],
                        help="操作类型")
    parser.add_argument("--date", help="交易日期(YYYYMMDD)")
    parser.add_argument("--account", help="模拟账户ID")
    parser.add_argument("--output-dir", help="报告输出目录")
    parser.add_argument("--output-path", help="CSV输出路径")
    parser.add_argument("--start", help="查询起始日期")
    parser.add_argument("--end", help="查询结束日期")
    args = parser.parse_args()
    
    tracker = NavTracker(args.account)
    
    if args.action == "update":
        tracker.update_daily_nav(args.date)
    
    elif args.action == "report":
        report = tracker.generate_report(args.date, args.output_dir)
        logger.info(report)
    
    elif args.action == "history":
        records = tracker.get_nav_history(args.start, args.end)
        if not records:
            logger.info("暂无净值记录")
        else:
            for r in records:
                icon = "📈" if r.daily_return > 0 else ("📉" if r.daily_return < 0 else "➖")
                logger.info(f"{r.date} {icon} NAV={r.nav:.4f} 日收益={r.daily_return:.2f}% 累计={r.cumulative_return:.2f}%")
    
    elif args.action == "export-csv":
        tracker.export_nav_csv(args.output_path)


if __name__ == "__main__":
    main()
