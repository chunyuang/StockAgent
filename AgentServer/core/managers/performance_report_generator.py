"""
绩效报告生成器

自动计算账户绩效指标，生成标准化的日/周/月/年度绩效报告。
"""

import uuid
import math
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional


from core.constants import C
from core.managers import mongo_manager

logger = logging.getLogger("performance_report_generator")

class PerformanceReportGenerator:
    """绩效报告生成器"""
    
    async def generate_daily_report(self, account_id: str, date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        生成指定账户的每日绩效报告
        
        Args:
            account_id: 模拟账户ID
            date: 报告日期，格式YYYYMMDD，默认今日
        
        Returns:
            生成的报告文档
        """
        if not date:
            date = datetime.now().strftime("%Y%m%d")
        
        logger.info(f"生成账户 {account_id} {date} 绩效报告...")
        
        try:
            # 获取账户信息
            account = await mongo_manager.find_one(
                "sim_accounts",
                {"account_id": account_id}
            )
            
            if not account:
                logger.error(f"账户 {account_id} 不存在")
                return None
            
            # 获取该日所有交易记录
            start_dt = datetime.strptime(date, "%Y%m%d")
            end_dt = start_dt + timedelta(days=1)
            
            trades = await mongo_manager.find_many(
                "trade_records",
                {
                    "account_id": account_id,
                    "trade_time": {"$gte": start_dt, "$lt": end_dt}
                }
            )
            
            # 获取账户持仓
            positions = await mongo_manager.find_many(
                C.POSITIONS,
                {"account_id": account_id}
            )
            
            # 计算各项指标
            total_trades = len(trades)
            winning_trades = 0
            losing_trades = 0
            total_profit = 0.0
            total_loss = 0.0
            
            for trade in trades:
                if trade["direction"] == "sell":
                    # 计算平仓盈亏
                    profit = (trade["price"] - trade.get("cost_price", 0)) * trade["quantity"]
                    if profit > 0:
                        winning_trades += 1
                        total_profit += profit
                    else:
                        losing_trades += 1
                        total_loss += abs(profit)
            
            # 计算收益指标
            initial_cash = account["initial_cash"]
            total_assets = account["available_cash"] + sum(
                pos["quantity"] * pos.get("current_price", pos["avg_cost"]) for pos in positions
            )
            total_return = total_assets - initial_cash
            total_return_pct = total_return / initial_cash if initial_cash > 0 else 0
            
            # 计算最大回撤（需要历史净值数据）
            max_drawdown_pct = await self._calculate_max_drawdown(account_id)
            
            # 计算夏普比率（需要至少30天数据）
            sharpe_ratio = await self._calculate_sharpe_ratio(account_id)
            
            # 计算 Sortino 比率
            sortino_ratio = await self._calculate_sortino_ratio(account_id)
            
            # 计算最大连续盈亏
            max_consec_wins, max_consec_losses = await self._calculate_max_consecutive(account_id)
            
            # 构造报告
            report_id = f"rpt_{uuid.uuid4().hex[:12]}"
            now = datetime.now(timezone.utc)
            
            report = {
                "report_id": report_id,
                "account_id": account_id,
                "period": "daily",
                "start_date": date,
                "end_date": date,
                "total_return_pct": total_return_pct,
                "annual_return_pct": total_return_pct * 250,  # 年化，250个交易日
                "max_drawdown_pct": max_drawdown_pct,
                "sharpe_ratio": sharpe_ratio,
                "sortino_ratio": sortino_ratio,
                "win_rate_pct": winning_trades / total_trades if total_trades > 0 else 0,
                "profit_factor": total_profit / total_loss if total_loss > 0 else float("inf"),
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "max_consecutive_wins": max_consec_wins,
                "max_consecutive_losses": max_consec_losses,
                "avg_profit_per_trade": total_profit / winning_trades if winning_trades > 0 else 0,
                "avg_loss_per_trade": total_loss / losing_trades if losing_trades > 0 else 0,
                "created_at": now
            }
            
            # 保存报告到数据库
            await mongo_manager.insert_one("performance_reports", report)
            
            logger.info(f"账户 {account_id} {date} 绩效报告生成成功，收益率 {total_return_pct*100:.2f}%")
            
            return report
            
        except Exception as e:
            logger.exception(f"生成绩效报告失败: {e}")
            return None
    
    async def generate_period_report(
        self,
        account_id: str,
        period: str,  # weekly/monthly/quarterly/yearly
        start_date: str,
        end_date: str
    ) -> Optional[Dict[str, Any]]:
        """
        生成周期绩效报告
        
        Args:
            account_id: 模拟账户ID
            period: 报告周期 (weekly/monthly/quarterly/yearly)
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
        """
        logger.info(f"生成账户 {account_id} {period} 绩效报告 ({start_date}~{end_date})...")
        
        try:
            start_dt = datetime.strptime(start_date, "%Y%m%d")
            end_dt = datetime.strptime(end_date, "%Y%m%d") + timedelta(days=1)
            
            # 获取该周期所有交易记录
            trades = await mongo_manager.find_many(
                "trade_records",
                {
                    "account_id": account_id,
                    "trade_time": {"$gte": start_dt, "$lt": end_dt}
                }
            )
            
            if not trades:
                logger.warning(f"账户 {account_id} 在 {start_date}~{end_date} 无交易记录")
                return None
            
            # 统计交易结果
            total_trades = len(trades)
            winning_trades = 0
            losing_trades = 0
            total_profit = 0.0
            total_loss = 0.0
            daily_returns = []
            
            for trade in trades:
                if trade["direction"] == "sell":
                    profit = (trade["price"] - trade.get("cost_price", 0)) * trade["quantity"]
                    if profit > 0:
                        winning_trades += 1
                        total_profit += profit
                    else:
                        losing_trades += 1
                        total_loss += abs(profit)
            
            # 获取账户信息计算收益率
            account = await mongo_manager.find_one("sim_accounts", {"account_id": account_id})
            if not account:
                logger.error(f"账户 {account_id} 不存在")
                return None
            
            initial_cash = account.get("initial_cash", 0)
            positions = await mongo_manager.find_many(C.POSITIONS, {"account_id": account_id})
            total_assets = account.get("available_cash", 0) + sum(
                pos["quantity"] * pos.get("current_price", pos.get("avg_cost", 0)) for pos in positions
            )
            total_return_pct = (total_assets - initial_cash) / initial_cash if initial_cash > 0 else 0
            
            # 计算交易日数
            trading_days = max(1, (end_dt - start_dt).days)
            annual_return_pct = total_return_pct * (250 / trading_days)
            
            # 构造报告
            report_id = f"rpt_{uuid.uuid4().hex[:12]}"
            now = datetime.now(timezone.utc)
            
            max_consec_wins, max_consec_losses = await self._calculate_max_consecutive(account_id)
            
            report = {
                "report_id": report_id,
                "account_id": account_id,
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
                "total_return_pct": total_return_pct,
                "annual_return_pct": annual_return_pct,
                "max_drawdown_pct": await self._calculate_max_drawdown(account_id),
                "sharpe_ratio": await self._calculate_sharpe_ratio(account_id),
                "sortino_ratio": await self._calculate_sortino_ratio(account_id),
                "win_rate_pct": winning_trades / total_trades if total_trades > 0 else 0,
                "profit_factor": total_profit / total_loss if total_loss > 0 else float("inf"),
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "max_consecutive_wins": max_consec_wins,
                "max_consecutive_losses": max_consec_losses,
                "avg_profit_per_trade": total_profit / winning_trades if winning_trades > 0 else 0,
                "avg_loss_per_trade": total_loss / losing_trades if losing_trades > 0 else 0,
                "created_at": now
            }
            
            await mongo_manager.insert_one("performance_reports", report)
            logger.info(f"账户 {account_id} {period} 绩效报告生成成功")
            return report
            
        except Exception as e:
            logger.exception(f"生成周期绩效报告失败: {e}")
            return None
    
    async def _get_equity_curve(self, account_id: str, days: int = 30) -> List[float]:
        """
        获取账户净值曲线
        
        Returns:
            每日总资产列表 (按时间升序)
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            
            # 从交易记录中构建每日收益
            trades = await mongo_manager.find_many(
                "trade_records",
                {
                    "account_id": account_id,
                    "trade_time": {"$gte": cutoff}
                },
                sort=[("trade_time", 1)]
            )
            
            if not trades:
                return []
            
            # 按日聚合收益
            daily_pnl = {}
            for trade in trades:
                trade_date = trade["trade_time"].strftime("%Y%m%d")
                if trade["direction"] == "sell":
                    pnl = (trade["price"] - trade.get("cost_price", 0)) * trade["quantity"]
                    daily_pnl[trade_date] = daily_pnl.get(trade_date, 0) + pnl
            
            if not daily_pnl:
                return []
            
            # 获取初始资金
            account = await mongo_manager.find_one("sim_accounts", {"account_id": account_id})
            initial_cash = account.get("initial_cash", 1000000) if account else 1000000
            
            # 构建净值曲线
            equity = initial_cash
            equity_curve = [equity]
            for date_key in sorted(daily_pnl.keys()):
                equity += daily_pnl[date_key]
                equity_curve.append(equity)
            
            return equity_curve
            
        except Exception as e:
            logger.error(f"获取净值曲线失败: {e}")
            return []
    
    async def _calculate_max_drawdown(self, account_id: str, days: int = 30) -> float:
        """
        计算最大回撤
        
        最大回撤 = (peak - trough) / peak
        """
        equity_curve = await self._get_equity_curve(account_id, days)
        
        if len(equity_curve) < 2:
            return 0.0
        
        max_drawdown = 0.0
        peak = equity_curve[0]
        
        for equity in equity_curve[1:]:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak if peak > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)
        
        return max_drawdown
    
    async def _calculate_sharpe_ratio(self, account_id: str, days: int = 30) -> float:
        """
        计算夏普比率
        
        Sharpe = (mean_return - risk_free_rate) / std_return
        年化: Sharpe * sqrt(250)
        risk_free_rate 年化约 2% → 日化约 0.02/250 = 0.00008
        """
        equity_curve = await self._get_equity_curve(account_id, days)
        
        if len(equity_curve) < 2:
            return 0.0
        
        # 计算每日收益率
        daily_returns = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i - 1] > 0:
                daily_returns.append(equity_curve[i] / equity_curve[i - 1] - 1)
        
        if len(daily_returns) < 2:
            return 0.0
        
        # 计算均值和标准差
        mean_return = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_return) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        std_return = math.sqrt(variance)
        
        if std_return < 1e-10:
            return 0.0
        
        risk_free_daily = 0.02 / 250  # 年化2%无风险利率
        sharpe = (mean_return - risk_free_daily) / std_return
        
        # 年化
        annualized_sharpe = sharpe * math.sqrt(250)
        return annualized_sharpe
    
    async def _calculate_sortino_ratio(self, account_id: str, days: int = 30) -> float:
        """
        计算 Sortino 比率
        
        Sortino = (mean_return - risk_free_rate) / downside_std_return
        只惩罚下行波动
        """
        equity_curve = await self._get_equity_curve(account_id, days)
        
        if len(equity_curve) < 2:
            return 0.0
        
        daily_returns = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i - 1] > 0:
                daily_returns.append(equity_curve[i] / equity_curve[i - 1] - 1)
        
        if len(daily_returns) < 2:
            return 0.0
        
        mean_return = sum(daily_returns) / len(daily_returns)
        
        # 只计算下行标准差 (负收益)
        downside_returns = [min(0, r) for r in daily_returns]
        downside_variance = sum(r ** 2 for r in downside_returns) / len(downside_returns)
        downside_std = math.sqrt(downside_variance)
        
        if downside_std < 1e-10:
            return 0.0
        
        risk_free_daily = 0.02 / 250
        sortino = (mean_return - risk_free_daily) / downside_std
        
        # 年化
        annualized_sortino = sortino * math.sqrt(250)
        return annualized_sortino
    
    async def _calculate_max_consecutive(self, account_id: str, days: int = 90) -> tuple:
        """
        计算最大连续盈亏次数
        
        Returns:
            (max_consecutive_wins, max_consecutive_losses)
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            
            trades = await mongo_manager.find_many(
                "trade_records",
                {
                    "account_id": account_id,
                    "trade_time": {"$gte": cutoff},
                    "direction": "sell"
                },
                sort=[("trade_time", 1)]
            )
            
            if not trades:
                return (0, 0)
            
            max_wins = 0
            max_losses = 0
            current_wins = 0
            current_losses = 0
            
            for trade in trades:
                pnl = (trade["price"] - trade.get("cost_price", 0)) * trade["quantity"]
                if pnl > 0:
                    current_wins += 1
                    current_losses = 0
                    max_wins = max(max_wins, current_wins)
                elif pnl < 0:
                    current_losses += 1
                    current_wins = 0
                    max_losses = max(max_losses, current_losses)
                else:
                    current_wins = 0
                    current_losses = 0
            
            return (max_wins, max_losses)
            
        except Exception as e:
            logger.error(f"计算最大连续盈亏失败: {e}")
            return (0, 0)
    
    async def get_latest_reports(
        self,
        account_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """获取最新报告列表"""
        reports = await mongo_manager.find_many(
            "performance_reports",
            {"account_id": account_id},
            sort=[("created_at", -1)],
            limit=limit
        )
        
        return reports


# 全局实例
performance_report_generator = PerformanceReportGenerator()
