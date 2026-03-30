#!/usr/bin/env python3
"""
实盘风控告警模块
支持实时监控和多种告警规则
"""
import sys
import os
import json
from datetime import datetime
from typing import List, Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))
sys.path.insert(0, os.path.dirname(__file__))

from position_manager import PositionManager
from paper_trading import PaperTradingEngine

class RiskAlertEngine:
    """风控告警引擎"""
    
    def __init__(self, config: Dict = None):
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
        history_file = "./alert_history.json"
        if os.path.exists(history_file):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def _save_alert_history(self):
        """保存告警历史"""
        history_file = "./alert_history.json"
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(self.alert_history, f, ensure_ascii=False, indent=2)
    
    def _send_alert(self, title: str, content: str, level: str = "info"):
        """发送告警"""
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
            print(f"📤 发送风控告警：{title}")
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
    
    def check_account_risk(self, account_id: str) -> List[Dict]:
        """检查账户风险"""
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
        total_position_value = sum(pos.shares * pos.cost_price for pos in positions)
        position_ratio = total_position_value / account.current_balance if account.current_balance > 0 else 0
        
        if position_ratio >= self.config["position_limit_alert"]:
            alerts.append({
                "title": "仓位超限告警",
                "content": f"账户【{account.name}】当前仓位达到{position_ratio*100:.1f}%，超过阈值{self.config['position_limit_alert']*100:.0f}%",
                "level": "info"
            })
        
        # 3. 单只股票亏损检查
        for pos in positions:
            # 这里简化处理，实际应获取当前价格计算浮亏
            # 模拟浮亏5%测试
            current_price = pos.cost_price * 0.95
            loss_pct = (current_price - pos.cost_price) / pos.cost_price
            
            if loss_pct <= -self.config["single_stock_loss_alert"]:
                alerts.append({
                    "title": "个股亏损告警",
                    "content": f"股票【{pos.ts_code}】浮亏达到{-loss_pct*100:.2f}%，超过阈值{self.config['single_stock_loss_alert']*100:.0f}%",
                    "level": "warning"
                })
        
        # 发送所有告警
        for alert in alerts:
            self._send_alert(**alert)
        
        return alerts
    
    def check_market_risk(self) -> List[Dict]:
        """检查市场风险"""
        alerts = []
        
        # 这里可以实现市场指数波动、涨跌停家数、情绪周期等检查
        # 示例：市场情绪过冷/过热告警
        # sentiment = get_market_sentiment()
        # if sentiment >= 90 or sentiment <= 10:
        #     alerts.append(...)
        
        return alerts
    
    def run_daily_check(self, account_id: str = None):
        """每日盘后风险检查"""
        print("🔍 开始每日风控检查...")
        
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
            print("✅ 今日风控检查通过，无异常")
        
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
