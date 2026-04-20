"""
每日收盘复盘报告

功能:
- 当日交易总结
- 持仓盈亏统计
- 策略绩效统计
- 写入飞书多维表格
- 生成复盘报告推送
"""

import logging
from datetime import date, datetime
from typing import List, Dict, Any, Optional

from core.managers import mongo_manager
from .position_manager import PositionManager
from .base_executor import AccountInfo
from ..strategies.emotion_cycle import emotion_cycle_manager


logger = logging.getLogger(__name__)


class DailyReporter:
    """每日收盘复盘报告"""
    
    def __init__(self, position_manager: PositionManager):
        self._position_manager = position_manager
    
    async def generate_daily_report(
        self,
        today: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        生成每日复盘报告
        
        Args:
            today: 日期，默认今天
        
        Returns:
            报告字典
        """
        if today is None:
            today = date.today().strftime("%Y%m%d")
        
        # 获取账户信息
        account = await self._position_manager.get_account_info()
        if account is None:
            logger.warning("[REPORT] Failed to get account info")
            return {}
        
        # 获取当前持仓
        positions = await self._position_manager.get_positions()
        
        # 获取今日交易记录
        today_trades = await self._get_today_trades(today)
        
        # 统计今日交易
        buy_count = sum(1 for t in today_trades if t["action"] == "buy")
        sell_count = sum(1 for t in today_trades if t["action"] == "sell")
        
        # 获取今日情绪
        emotion = await emotion_cycle_manager.calculate_daily_emotion(today)
        
        # 计算今日盈亏
        today_profit = self._calculate_today_profit(today_trades, account)
        
        # 统计策略绩效
        strategy_stats = self._calculate_strategy_stats(today_trades)
        
        # 构建报告
        report = {
            "date": today,
            "total_asset": account.total_asset,
            "available_cash": account.available_cash,
            "market_value": account.market_value,
            "total_profit": account.total_profit,
            "total_profit_pct": account.total_profit_pct,
            "position_count": account.position_count,
            "today_buy_count": buy_count,
            "today_sell_count": sell_count,
            "today_profit": today_profit,
            "emotion_score": emotion.score,
            "emotion_phase": emotion.phase.value,
            "emotion_position_multiplier": emotion.position_multiplier,
            "limit_up_count": emotion.limit_up_count,
            "limit_down_count": emotion.limit_down_count,
            "current_positions": [
                {
                    "ts_code": p.ts_code,
                    "shares": p.shares,
                    "cost_price": p.cost_price,
                    "current_price": p.current_price,
                    "profit_pct": p.profit_pct,
                    "profit_amount": p.profit_amount,
                    "stop_loss": p.stop_loss,
                    "strategy": p.strategy,
                }
                for p in positions
            ],
            "strategy_stats": strategy_stats,
            "created_at": datetime.now(),
        }
        
        logger.info(
            f"[REPORT] {today} generated:\n"
            f"  Total Asset: {account.total_asset:.2f}\n"
            f"  Total Profit: {account.total_profit:.2f} ({account.total_profit_pct:.2f}%)\n"
            f"  Positions: {account.position_count}\n"
            f"  Today: {buy_count} buys, {sell_count} sells, profit: {today_profit:.2f}\n"
            f"  Emotion: {emotion.score:.1f} ({emotion.phase.value})"
        )
        
        # 写入 MongoDB
        await mongo_manager.replace_one(
            "daily_reports",
            {"date": today},
            report,
            upsert=True,
        )
        
        # 写入飞书多维表格（如果配置了）
        from core.managers import feishu_bitable_manager
        if feishu_bitable_manager.is_configured:
            record_id = await feishu_bitable_manager.add_daily_report(report)
            if record_id:
                logger.info(f"[REPORT] Daily report written to Feishu Bitable: {record_id}")
            else:
                logger.warning("[REPORT] Failed to write daily report to Feishu Bitable")
        
        return report
    
    async def _get_today_trades(self, today: str) -> List[Dict[str, Any]]:
        """获取今日交易记录"""
        from datetime import datetime
        
        # 查询今日所有交易
        start_of_day = datetime.strptime(today, "%Y%m%d").replace(hour=0, minute=0, second=0)
        end_of_day = datetime.strptime(today, "%Y%m%d").replace(hour=23, minute=59, second=59)
        
        query = {
            "created_at": {
                "$gte": start_of_day,
                "$lte": end_of_day,
            }
        }
        
        result = await mongo_manager.find_many("trading_records", query)
        return list(result)
    
    async def _calculate_today_profit(
        self,
        today_trades: List[Dict[str, Any]],
        account: AccountInfo,
    ) -> float:
        """计算今日盈亏"""
        # 今日平仓卖出的盈利
        today_profit = 0.0
        
        for trade in today_trades:
            if trade["action"] == "sell":
                # 盈利已经在卖出时计算到累计
                # 这里只计算今日卖出相对于昨日持仓的盈利
                pass
        
        # 今日持仓浮盈
        positions = await self._position_manager.get_positions()
        for pos in positions:
            today_profit += pos.profit_amount
        
        return today_profit
    
    def _calculate_strategy_stats(self, today_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """按策略统计今日交易"""
        stats: Dict[str, Dict] = {}
        
        for trade in today_trades:
            strategy = trade.get("strategy", "unknown")
            if strategy not in stats:
                stats[strategy] = {
                    "buy": 0,
                    "sell": 0,
                    "profit": 0.0,
                }
            
            if trade["action"] == "buy":
                stats[strategy]["buy"] += 1
            else:
                stats[strategy]["sell"] += 1
                # 盈利记录在卖出时
                if "commission" in trade:
                    # 盈利 = 卖出金额 - 买入成本 - 佣金
                    # 这里简化统计，详细统计在 MongoDB
                    pass
        
        return stats
    
    async def push_report_to_wecom(self, report: Dict[str, Any]) -> bool:
        """推送复盘报告到企业微信/飞书 Webhook"""
        from core.managers.notification_manager import notification_manager
        
        # 生成markdown消息
        msg = self._format_markdown(report)
        
        try:
            result = await notification_manager.send_text(msg)
            logger.info("[REPORT] Daily report pushed to WeCom")
            return True
        except Exception as e:
            logger.error(f"[REPORT] Failed to push report: {e}")
            return False
    
    def _format_markdown(self, report: Dict[str, Any]) -> str:
        """格式化markdown复盘报告"""
        today = report.get("date", "")
        total_asset = report.get("total_asset", 0)
        total_profit = report.get("total_profit", 0)
        total_profit_pct = report.get("total_profit_pct", 0)
        position_count = report.get("position_count", 0)
        today_buy = report.get("today_buy_count", 0)
        today_sell = report.get("today_sell_count", 0)
        today_profit = report.get("today_profit", 0)
        emotion_score = report.get("emotion_score", 0)
        emotion_phase = report.get("emotion_phase", "unknown")
        
        positions = report.get("current_positions", [])
        
        msg = f"""# 📊 StockAgent 每日复盘 {today}

## 💰 账户概况
- **总资产**: {total_asset:.2f} 元
- **累计盈亏**: {total_profit:.2f} 元 ({total_profit_pct:.2f}%)
- **当前持仓**: {position_count} 只

## 🎯 今日交易
- **买入**: {today_buy} 只
- **卖出**: {today_sell} 只
- **今日浮盈**: {today_profit:.2f} 元

## 😁 市场情绪
- **得分**: {emotion_score:.1f}/100
- **阶段**: {emotion_phase}
"""
        
        if positions:
            msg += "\n## 📈 当前持仓\n"
            for p in positions:
                emoji = "🟢" if p["profit_pct"] > 0 else "🔴"
                msg += f"{emoji} **{p['ts_code']}** {p['shares']} 股 @ {p['cost_price']:.2f} → {p['current_price']:.2f}  {p['profit_pct']:.2f}% ({p['profit_amount']:.2f})\n"
        
        msg += f"\n---\nGenerated by StockAgent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return msg


# 全局单例
def get_daily_reporter(position_manager: PositionManager) -> DailyReporter:
    """获取每日复盘报告器单例"""
    return DailyReporter(position_manager)
