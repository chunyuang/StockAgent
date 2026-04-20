"""
绩效报告生成器

自动计算账户绩效指标，生成标准化的日/周/月/年度绩效报告。
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional


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
                "positions",
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
            
            # 构造报告
            report_id = f"rpt_{uuid.uuid4().hex[:12]}"
            now = datetime.utcnow()
            
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
                "sortino_ratio": 0.0,  # TODO: 计算索提诺比率
                "win_rate_pct": winning_trades / total_trades if total_trades > 0 else 0,
                "profit_factor": total_profit / total_loss if total_loss > 0 else float("inf"),
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "max_consecutive_wins": 0,  # TODO: 计算最大连续盈利
                "max_consecutive_losses": 0,  # TODO: 计算最大连续亏损
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
        """生成周期绩效报告"""
        # TODO: 实现周期报告生成
        pass
    
    async def _calculate_max_drawdown(self, account_id: str, days: int = 30) -> float:
        """计算最大回撤"""
        # TODO: 实现最大回撤计算，需要净值曲线数据
        return 0.0
    
    async def _calculate_sharpe_ratio(self, account_id: str, days: int = 30) -> float:
        """计算夏普比率"""
        # TODO: 实现夏普比率计算
        return 0.0
    
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
