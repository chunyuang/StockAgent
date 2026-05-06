#!/usr/bin/env python3
"""
实盘风控告警模块
支持实时监控和多种告警规则
"""
import sys
import logging

logger = logging.getLogger(__name__)
import os
import json
from datetime import datetime
from typing import List, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))  # FIXME: 使用sys.path.insert做模块查找是反模式，应改用setup.py/pyproject.toml将项目安装到venv中
sys.path.insert(0, os.path.dirname(__file__))

from paper_trading import PaperTradingEngine

class RiskAlertEngine:
    """风控告警引擎
    
    提供多层次风控检查：
    - 账户级：最大回撤超限/仓位超限/单股亏损超限
    - 市场级：指数波动/情绪极端（框架预留）
    - 每日盘后例行检查
    
    告警通过飞书等渠道推送，历史记录持久化到 alert_history.json。
    """
    
    def __init__(self, config: Dict = None):
        """初始化风控引擎
        
        Args:
            config: 可选配置覆盖，支持的字段：
                - alert_channels: 告警渠道列表，默认 ['feishu']
                - max_drawdown_alert: 最大回撤告警阈值，默认0.1（10%）
                - single_stock_loss_alert: 单股亏损告警阈值，默认0.08（8%）
                - position_limit_alert: 仓位超限告警阈值，默认0.9（90%）
                - daily_loss_alert: 单日亏损告警阈值，默认0.05（5%）
                - volatility_alert: 指数波动告警阈值，默认0.03（3%）
        """
        self.default_config = {
            "alert_channels": ["feishu"],  # 告警渠道
            "max_drawdown_alert": 0.1,  # 最大回撤超过10%告警
            "single_stock_loss_alert": 0.08,  # 单只股票亏损超过8%告警
            "position_limit_alert": 0.9,  # 仓位超过90%告警
            "daily_loss_alert": 0.05,  # 单日亏损超过5%告警
            "volatility_alert": 0.03,  # 指数波动超过3%告警
        }
        self.config = {**self.default_config, **(config or {})}
        self.alert_history = self._load_alert_history()
    
    def _load_alert_history(self) -> List[Dict]:
        """加载告警历史"""
        history_file = os.path.join(os.path.dirname(__file__), "alert_history.json")
        if not os.path.exists(history_file):
            return []
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    return []
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"⚠️  加载告警历史失败: {e}")
            return []
    
    def _save_alert_history(self):
        """保存告警历史"""
        history_file = os.path.join(os.path.dirname(__file__), "alert_history.json")
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(self.alert_history, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError) as e:
            logger.error(f"⚠️  保存告警历史失败: {e}")
    
    def _send_alert(self, title: str, content: str, level: str = "info"):
        """发送风控告警
        
        根据级别选择emoji，通过配置的渠道推送，并记录到告警历史。
        
        Args:
            title: 告警标题
            content: 告警内容详情
            level: 告警级别 info/warning/danger/critical
        """
        # 生成告警内容
        level_emoji = {
            "info": "ℹ️",
            "warning": "⚠️",
            "danger": "🚨",
            "critical": "🔴"
        }.get(level, "ℹ️")
        
        alert_message = f"{level_emoji} **{title}**\n---\n{content}\n\n告警时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # 发送到飞书
        if "feishu" in self.config["alert_channels"]:
            logger.info(f"📤 发送风控告警：{title}")
            # 调用系统消息推送
            os.system(f'/root/.openclaw/bin/openclaw message send --message "{alert_message}" --channel feishu')
        
        # 记录历史
        self.alert_history.append({
            "time": datetime.now().isoformat(),
            "title": title,
            "content": content,
            "level": level,
        })
        self._save_alert_history()
    
    async def check_account_risk(self, account_id: str) -> List[Dict]:
        """检查指定账户的风险状况
        
        执行三项检查：
        1. 最大回撤检查 → 超过 max_drawdown_alert 阈值告警
        2. 仓位超限检查 → 超过 position_limit_alert 阈值告警
        3. 单股亏损检查 → 超过 single_stock_loss_alert 阈值告警
        
        Args:
            account_id: 要检查的模拟账户ID
        
        Returns:
            List[Dict]: 告警列表，每条包含 title/content/level
        """
        engine = PaperTradingEngine()
        if account_id not in engine.accounts:
            return []
        
        account = engine.accounts[account_id]
        alerts = []
        
        # 1. 最大回撤检查
        if account.max_drawdown >= self.config["max_drawdown_alert"]:
            alerts.append({
                "title": "账户最大回撤告警",
                "content": f"账户【{account.name}】当前最大回撤达到{account.max_drawdown*100:.2f}%，超过阈值{self.config['max_drawdown_alert']*100:.0f}%",
                "level": "warning"
            })
        
        # 2. 仓位检查
        pos_manager = engine.position_managers[account_id]
        positions = pos_manager.get_positions()
        total_position_value = sum(pos["shares"] * pos["buy_price"] for pos in positions)  # TODO: 用当前市价替代成本价
        position_ratio = total_position_value / account.current_balance if account.current_balance > 0 else 0
        
        if position_ratio >= self.config["position_limit_alert"]:
            alerts.append({
                "title": "仓位超限告警",
                "content": f"账户【{account.name}】当前仓位达到{position_ratio*100:.1f}%，超过阈值{self.config['position_limit_alert']*100:.0f}%",
                "level": "info"
            })
        
        # 3. 单只股票亏损检查
        for pos in positions:
            # TODO: 从MongoDB/AKShare获取当前价格，当前用成本价近似导致loss_pct永远为0
            try:
                from core.managers import mongo_manager
                doc = await mongo_manager.find_one("stock_daily_ak_full", {"ts_code": pos["ts_code"]}, sort=[("trade_date", -1)])
                current_price = doc["close"] if doc and doc.get("close", 0) > 0 else pos["buy_price"]
            except Exception:
                current_price = pos["buy_price"]
            cost = pos["buy_price"]
            loss_pct = (current_price - cost) / cost if cost > 0 else 0
            
            if loss_pct <= -self.config["single_stock_loss_alert"]:
                alerts.append({
                    "title": "个股亏损告警",
                    "content": f"股票【{pos['ts_code']}】浮亏达到{-loss_pct*100:.2f}%，超过阈值{self.config['single_stock_loss_alert']*100:.0f}%",
                    "level": "warning"
                })
        
        # 发送所有告警
        for alert in alerts:
            self._send_alert(**alert)
        
        return alerts
    
    def check_market_risk(self) -> List[Dict]:
        """检查市场整体风险
        
        框架预留，可扩展实现：
        - 市场指数波动率超限告警
        - 涨跌停家数异常告警
        - 情绪周期极端告警
        
        Returns:
            List[Dict]: 告警列表（当前返回空列表）
        """
        alerts = []
        
        # 这里可以实现市场指数波动、涨跌停家数、情绪周期等检查
        # 示例：市场情绪过冷/过热告警
        # sentiment = get_market_sentiment()
        # if sentiment >= 90 or sentiment <= 10:
        #     alerts.append(...)
        
        return alerts
    
    def run_daily_check(self, account_id: str = None):
        """每日盘后风险检查（入口方法）
        
        检查指定账户或所有活跃账户的风险，加上市场风险检查。
        
        Args:
            account_id: 指定账户ID，None则检查所有活跃账户
        
        Returns:
            List[Dict]: 所有告警的汇总列表
        """
        logger.debug("🔍 开始每日风控检查...")
        
        alerts = []
        
        # 检查所有活跃账户
        if not account_id:
            engine = PaperTradingEngine()
            for acc_id, acc in engine.accounts.items():
                if acc.status == "active":
                    alerts.extend(self.check_account_risk(acc_id))
        else:
            alerts.extend(self.check_account_risk(account_id))
        
        # 检查市场风险
        alerts.extend(self.check_market_risk())
        
        if not alerts:
            logger.error("✅ 今日风控检查通过，无异常")
        
        return alerts

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="风控告警引擎")
    parser.add_argument("--account", help="指定账户ID")
    parser.add_argument("--check", choices=["daily", "market"], default="daily", help="检查类型")
    args = parser.parse_args()
    
    engine = RiskAlertEngine()
    
    if args.check == "daily":
        engine.run_daily_check(args.account)
    elif args.check == "market":
        engine.check_market_risk()
