"""
推送服务

支持飞书/企业微信/短信等渠道的消息推送，用于推送交易信号、绩效报告、告警通知等。
"""

import logging
from typing import Dict, List, Any

import aiohttp

from core.settings import settings

logger = logging.getLogger("push_service")

class PushService:
    """推送服务"""
    
    def __init__(self):
        self.feishu_webhook = settings.notification.feishu_webhook
        self.wecom_webhook = settings.notification.wecom_webhook
        self.enabled = settings.notification.enabled
    
    async def push_signal_alert(self, signals: List[Dict[str, Any]]) -> bool:
        """推送交易信号提醒"""
        if not self.enabled or not signals:
            return False
        
        try:
            # 构造飞书卡片消息
            title = f"📈 今日交易信号（{len(signals)}个）"
            
            content = []
            for i, signal in enumerate(signals[:10]):  # 最多显示10个
                direction = "🟢 买入" if signal["signal_type"] == "buy" else "🔴 卖出"
                line = (
                    f"**{i+1}. {signal['stock_name']}({signal['ts_code']})**\n"
                    f"策略：{signal['strategy_name']} | {direction}\n"
                    f"价格：{signal['price']:.2f} | 置信度：{signal['confidence']*100:.0f}%\n"
                    f"理由：{signal['reason'][:50]}..."
                )
                content.append(line)
            
            if len(signals) > 10:
                content.append(f"\n... 还有 {len(signals)-10} 个信号未显示")
            
            message = {
                "msg_type": "interactive",
                "card": {
                    "config": {
                        "wide_screen_mode": True
                    },
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": "\n\n".join(content)
                        }
                    ],
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": title
                        },
                        "template": "blue"
                    }
                }
            }
            
            # 推送飞书
            if self.feishu_webhook:
                await self._send_feishu_webhook(message)
            
            # 推送企业微信
            if self.wecom_webhook:
                await self._send_wecom_webhook(title, "\n\n".join(content))
            
            logger.info(f"交易信号推送成功，共 {len(signals)} 个信号")
            
            return True
            
        except Exception as e:
            logger.exception(f"推送信号提醒失败: {e}")
            return False
    
    async def push_performance_report(self, report: Dict[str, Any]) -> bool:
        """推送绩效报告"""
        if not self.enabled:
            return False
        
        try:
            title = f"📊 每日绩效报告 {report['end_date']}"
            
            content = (
                f"**账户收益：{report['total_return_pct']*100:.2f}%**\n"
                f"年化收益：{report['annual_return_pct']*100:.2f}%\n"
                f"最大回撤：{report['max_drawdown_pct']*100:.2f}%\n"
                f"夏普比率：{report['sharpe_ratio']:.2f}\n"
                f"胜率：{report['win_rate_pct']*100:.2f}%\n"
                f"盈亏比：{report['profit_factor']:.2f}\n"
                f"今日交易次数：{report['total_trades']}"
            )
            
            message = {
                "msg_type": "interactive",
                "card": {
                    "config": {
                        "wide_screen_mode": True
                    },
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": content
                        }
                    ],
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": title
                        },
                        "template": "green" if report["total_return_pct"] >= 0 else "red"
                    }
                }
            }
            
            if self.feishu_webhook:
                await self._send_feishu_webhook(message)
            
            if self.wecom_webhook:
                await self._send_wecom_webhook(title, content)
            
            logger.info("绩效报告推送成功")
            
            return True
            
        except Exception as e:
            logger.exception(f"推送绩效报告失败: {e}")
            return False
    
    async def push_risk_alert(self, title: str, content: str, level: str = "warning") -> bool:
        """推送风险告警"""
        if not self.enabled:
            return False
        
        try:
            template = "red" if level == "danger" else "orange"
            
            message = {
                "msg_type": "interactive",
                "card": {
                    "config": {
                        "wide_screen_mode": True
                    },
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": content
                        }
                    ],
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": f"⚠️ {title}"
                        },
                        "template": template
                    }
                }
            }
            
            if self.feishu_webhook:
                await self._send_feishu_webhook(message)
            
            if self.wecom_webhook:
                await self._send_wecom_webhook(title, content)
            
            logger.warning(f"风险告警推送成功：{title}")
            
            return True
            
        except Exception as e:
            logger.exception(f"推送风险告警失败: {e}")
            return False
    
    async def _send_feishu_webhook(self, message: Dict[str, Any]) -> bool:
        """发送飞书Webhook消息"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.feishu_webhook,
                    json=message,
                    timeout=10
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("code") == 0:
                            return True
                        logger.error(f"飞书推送失败：{result.get('msg')}")
                    else:
                        logger.error(f"飞书推送HTTP错误：{resp.status}")
            
            return False
            
        except Exception as e:
            logger.exception(f"发送飞书消息失败: {e}")
            return False
    
    async def _send_wecom_webhook(self, title: str, content: str) -> bool:
        """发送企业微信Webhook消息"""
        try:
            message = {
                "msgtype": "markdown",
                "markdown": {
                    "content": f"## {title}\n\n{content}"
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.wecom_webhook,
                    json=message,
                    timeout=10
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("errcode") == 0:
                            return True
                        logger.error(f"企业微信推送失败：{result.get('errmsg')}")
                    else:
                        logger.error(f"企业微信推送HTTP错误：{resp.status}")
            
            return False
            
        except Exception as e:
            logger.exception(f"发送企业微信消息失败: {e}")
            return False


# 全局实例
push_service = PushService()
