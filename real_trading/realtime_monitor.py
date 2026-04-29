#!/usr/bin/env python3
"""
实盘盘中实时监控模块
功能：实时行情监控、买入条件触发提醒、大盘风险预警、持仓异动提醒
"""
import sys
import logging

logger = logging.getLogger(__name__)
import os
import asyncio
import time
from datetime import datetime
from typing import List, Dict
import akshare as ak

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))  # FIXME: 使用sys.path.insert做模块查找是反模式，应改用setup.py/pyproject.toml将项目安装到venv中
sys.path.insert(0, os.path.dirname(__file__))

from signal_pusher import SignalPusher

class RealTimeMonitor:
    """盘中实时监控器"""
    
    def __init__(self, config: Dict = None):
        self.default_config = {
            "check_interval": 30,  # 检查间隔，秒
            "enable_stock_monitor": True,
            "enable_market_monitor": True,
            "enable_position_monitor": True,
            "alert_threshold": {
                "index_drop": 1.5,  # 大盘跌幅≥1.5%预警
                "limit_down_count": 30,  # 跌停家数≥30预警
                "position_drop": 3,  # 持仓跌幅≥3%预警
                "target_reach_buy_price": 0.5,  # 目标股达到买入价±0.5%提醒
            },
            "push_config": {},  # 推送配置
            "target_stocks": [],  # 监控的目标股票列表
        }
        self.config = {**self.default_config, **(config or {})}
        self.pusher = SignalPusher(self.config["push_config"])
        self.last_alert_time = {}  # 防重复提醒，记录上次提醒时间
    
    async def start(self, duration: int = None):
        """启动监控
        duration: 监控时长，秒，None表示一直运行
        """
        logger.info(f"🚀 盘中实时监控启动，检查间隔{self.config['check_interval']}秒")
        start_time = time.time()
        
        try:
            while True:
                if duration and time.time() - start_time > duration:
                    logger.info("⏰ 监控时长到，停止监控")
                    break
                
                now = datetime.now()
                # 仅在交易时间运行（9:30-11:30, 13:00-15:00）
                if not self._is_trading_time(now):
                    await asyncio.sleep(60)
                    continue
                
                logger.info(f"\n[{now.strftime('%H:%M:%S')}] 开始本轮检查...")
                
                alerts = []
                
                # 大盘监控
                if self.config["enable_market_monitor"]:
                    market_alerts = await self._check_market_risk()
                    alerts.extend(market_alerts)
                
                # 持仓监控
                if self.config["enable_position_monitor"]:
                    position_alerts = await self._check_positions()
                    alerts.extend(position_alerts)
                
                # 目标股票监控
                if self.config["enable_stock_monitor"] and self.config["target_stocks"]:
                    stock_alerts = await self._check_target_stocks()
                    alerts.extend(stock_alerts)
                
                # 推送提醒
                if alerts:
                    await self._push_alerts(alerts)
                
                # 等待下一轮检查
                await asyncio.sleep(self.config["check_interval"])
        
        except KeyboardInterrupt:
            logger.info("\n⏹️  手动停止监控")
    
    def _is_trading_time(self, dt: datetime) -> bool:
        """判断是否是交易时间"""
        # 排除周末
        if dt.weekday() >= 5:
            return False
        
        hour = dt.hour
        minute = dt.minute
        
        # 早盘 9:30-11:30
        if 9 <= hour <= 11:
            if hour == 9 and minute < 30:
                return False
            if hour == 11 and minute > 30:
                return False
            return True
        
        # 午盘 13:00-15:00
        if 13 <= hour <= 15:
            if hour == 15 and minute > 0:
                return False
            return True
        
        return False
    
    async def _check_market_risk(self) -> List[Dict]:
        """检查大盘风险"""
        alerts = []
        
        try:
            # 获取上证指数和创业板指实时行情
            sh_df = ak.stock_zh_index_spot_em()
            sh_index = sh_df[sh_df["代码"] == "000001"].iloc[0]
            cyb_index = sh_df[sh_df["代码"] == "399006"].iloc[0]
            
            sh_pct = sh_index["涨跌幅"]
            cyb_pct = cyb_index["涨跌幅"]
            
            # 大盘暴跌预警
            drop_threshold = self.config["alert_threshold"]["index_drop"]
            if sh_pct <= -drop_threshold or cyb_pct <= -drop_threshold:
                alerts.append({
                    "level": "danger",
                    "title": "⚠️ 大盘暴跌预警",
                    "content": f"上证指数跌幅{sh_pct:.2f}%，创业板指跌幅{cyb_pct:.2f}%，超过{drop_threshold}%阈值，注意风险控制"
                })
            
            # 涨跌停家数监控
            limit_up_count = len(sh_df[sh_df["涨跌幅"] >= 9.5])
            limit_down_count = len(sh_df[sh_df["涨跌幅"] <= -9.5])
            
            ld_threshold = self.config["alert_threshold"]["limit_down_count"]
            if limit_down_count >= ld_threshold:
                alerts.append({
                    "level": "danger",
                    "title": "⚠️ 市场恐慌预警",
                    "content": f"当前跌停家数{limit_down_count}只，超过{ld_threshold}只阈值，市场情绪恐慌，建议降低仓位"
                })
            
            # 市场无赚钱效应预警
            if limit_up_count < 10:
                alerts.append({
                    "level": "warning",
                    "title": "ℹ️ 市场清淡提醒",
                    "content": f"当前涨停家数仅{limit_up_count}只，市场无赚钱效应，建议观望"
                })
        
        except Exception as e:
            logger.error(f"❌ 大盘监控异常: {e}")
        
        return alerts
    
    async def _check_positions(self) -> List[Dict]:
        """检查持仓异动"""
        alerts = []
        
        try:
            from position_manager import PositionManager
            pos_manager = PositionManager()
            positions = pos_manager.get_positions()
            
            if not positions:
                return alerts
            
            # 获取持仓实时行情
            ts_codes = [pos["ts_code"].split(".")[0] for pos in positions]
            quote_df = ak.stock_zh_a_spot_em()
            quote_df = quote_df[quote_df["代码"].isin(ts_codes)]
            quote_map = {row["代码"]: row for _, row in quote_df.iterrows()}
            
            drop_threshold = self.config["alert_threshold"]["position_drop"]
            
            for pos in positions:
                code = pos["ts_code"].split(".")[0]
                if code not in quote_map:
                    continue
                
                quote = quote_map[code]
                current_price = quote["最新价"]
                pct_chg = quote["涨跌幅"]
                
                # 持仓大跌预警
                if pct_chg <= -drop_threshold:
                    alert_key = f"pos_drop_{pos['ts_code']}"
                    if self._should_alert(alert_key):
                        alerts.append({
                            "level": "warning",
                            "title": f"📉 持仓异动提醒：{pos['name']}",
                            "content": f"{pos['name']}({pos['ts_code']}) 当前跌幅{pct_chg:.2f}%，超过{drop_threshold}%阈值，成本价{pos['buy_price']:.2f}，当前价{current_price:.2f}"
                        })
                
                # 接近止损预警
                if current_price <= pos["stop_loss_price"] * 1.03:
                    alert_key = f"pos_stop_loss_{pos['ts_code']}"
                    if self._should_alert(alert_key):
                        alerts.append({
                            "level": "danger",
                            "title": f"🔴 接近止损提醒：{pos['name']}",
                            "content": f"{pos['name']}({pos['ts_code']}) 当前价{current_price:.2f}，接近止损价{pos['stop_loss_price']:.2f}，建议注意风险"
                        })
                
                # 接近止盈预警
                if current_price >= pos["take_profit_price"] * 0.97:
                    alert_key = f"pos_take_profit_{pos['ts_code']}"
                    if self._should_alert(alert_key):
                        alerts.append({
                            "level": "success",
                            "title": f"🟢 接近止盈提醒：{pos['name']}",
                            "content": f"{pos['name']}({pos['ts_code']}) 当前价{current_price:.2f}，接近止盈价{pos['take_profit_price']:.2f}，建议考虑止盈"
                        })
        
        except Exception as e:
            logger.error(f"❌ 持仓监控异常: {e}")
        
        return alerts
    
    async def _check_target_stocks(self) -> List[Dict]:
        """检查目标股票是否达到买入条件"""
        alerts = []
        
        try:
            target_codes = [s.split(".")[0] for s in self.config["target_stocks"]]
            quote_df = ak.stock_zh_a_spot_em()
            quote_df = quote_df[quote_df["代码"].isin(target_codes)]
            quote_map = {row["代码"]: row for _, row in quote_df.iterrows()}
            
            
            for target in self.config["target_stocks"]:
                code = target.split(".")[0]
                if code not in quote_map:
                    continue
                
                quote = quote_map[code]
                current_price = quote["最新价"]
                pct_chg = quote["涨跌幅"]
                name = quote["名称"]
                
                # 假设目标买入价保存在target_stocks的字典中，这里简化处理
                # 实际使用时可以配置每个目标的买入价
                if isinstance(target, dict):
                    pass  # TODO: implement target dict logic
                else:
                    # 简单提醒达到预设的涨幅区间
                    if 0.5 <= pct_chg <= 3:
                        alert_key = f"target_buy_{code}"
                        if self._should_alert(alert_key):
                            alerts.append({
                                "level": "info",
                                "title": f"🎯 目标股提醒：{name}",
                                "content": f"{name}({target}) 当前涨幅{pct_chg:.2f}%，当前价{current_price:.2f}，符合买入涨幅区间"
                            })
        
        except Exception as e:
            logger.error(f"❌ 目标股监控异常: {e}")
        
        return alerts
    
    def _should_alert(self, alert_key: str, interval: int = 1800) -> bool:
        """防重复提醒，默认间隔30分钟"""
        now = time.time()
        last_time = self.last_alert_time.get(alert_key, 0)
        if now - last_time > interval:
            self.last_alert_time[alert_key] = now
            return True
        return False
    
    async def _push_alerts(self, alerts: List[Dict]):
        """推送提醒"""
        if not alerts:
            return
        
        # 构造推送内容
        content = [
            "# ⚠️ 盘中监控提醒",
            ""
        ]
        
        for alert in alerts:
            icon = "🔴" if alert["level"] == "danger" else "🟡" if alert["level"] == "warning" else "🔵"
            content.append(f"## {icon} {alert['title']}")
            content.append(f"{alert['content']}")
            content.append("")
        
        content.append(f"*提醒时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        
        # 构造信号数据用于推送
        signal_data = {
            "date": datetime.now().strftime("%Y%m%d"),
            "force_empty": False,
            "sentiment": {"level": "盘中提醒"},
            "signals": [],
            "trading_plan": "\n".join(content)
        }
        
        try:
            self.pusher.push(signal_data)
            logger.info(f"✅ 推送{len(alerts)}条提醒")
        except Exception as e:
            logger.error(f"❌ 推送提醒失败: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="盘中实时监控工具")
    parser.add_argument("--duration", type=int, help="监控时长，秒，默认一直运行")
    parser.add_argument("--interval", type=int, default=30, help="检查间隔，秒，默认30秒")
    parser.add_argument("--target", nargs="+", help="监控的目标股票代码，例如 000001.SZ 600000.SH")
    parser.add_argument("--feishu", help="飞书webhook地址，用于推送提醒")
    parser.add_argument("--wecom", help="企业微信webhook地址，用于推送提醒")
    
    args = parser.parse_args()
    
    config = {
        "check_interval": args.interval,
        "target_stocks": args.target or [],
        "push_config": {}
    }
    
    if args.feishu:
        config["push_config"]["feishu_webhook"] = args.feishu
    if args.wecom:
        config["push_config"]["wecom_webhook"] = args.wecom
    
    monitor = RealTimeMonitor(config)
    
    async def main():
        await monitor.start(args.duration)
    
    asyncio.run(main())
