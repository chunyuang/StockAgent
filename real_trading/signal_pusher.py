#!/usr/bin/env python3
"""
实盘信号推送模块
支持多渠道推送：飞书、企业微信、钉钉、邮件、短信
"""
import sys
import os
import json
import requests
from typing import Dict
from datetime import datetime

class SignalPusher:
    """信号推送器"""
    
    def __init__(self, config: Dict = None):
        self.default_config = {
            "feishu_webhook": os.getenv("FEISHU_WEBHOOK"),
            "wecom_webhook": os.getenv("WECOM_WEBHOOK"),
            "dingtalk_webhook": os.getenv("DINGTALK_WEBHOOK"),
            "smtp_config": {
                "host": os.getenv("SMTP_HOST"),
                "port": os.getenv("SMTP_PORT", 465),
                "user": os.getenv("SMTP_USER"),
                "password": os.getenv("SMTP_PASSWORD"),
                "to": os.getenv("SMTP_TO"),
            },
            "push_empty_signal": False,  # 是否推送空信号
        }
        self.config = {**self.default_config, **(config or {})}
    
    def push(self, signal_data: Dict) -> bool:
        """推送信号到所有配置的渠道"""
        success = True
        
        # 空信号判断
        if not signal_data.get("signals") and not self.config["push_empty_signal"]:
            print("ℹ️  无交易信号，跳过推送")
            return True
        
        print(f"📤 开始推送{signal_data['date']}信号...")
        
        # 推送飞书
        if self.config["feishu_webhook"]:
            try:
                self._push_feishu(signal_data)
                print("✅ 飞书推送成功")
            except Exception as e:
                print(f"❌ 飞书推送失败: {e}")
                success = False
        
        # 推送企业微信
        if self.config["wecom_webhook"]:
            try:
                self._push_wecom(signal_data)
                print("✅ 企业微信推送成功")
            except Exception as e:
                print(f"❌ 企业微信推送失败: {e}")
                success = False
        
        # 推送钉钉
        if self.config["dingtalk_webhook"]:
            try:
                self._push_dingtalk(signal_data)
                print("✅ 钉钉推送成功")
            except Exception as e:
                print(f"❌ 钉钉推送失败: {e}")
                success = False
        
        # 推送邮件
        if self.config["smtp_config"]["host"] and self.config["smtp_config"]["to"]:
            try:
                self._push_email(signal_data)
                print("✅ 邮件推送成功")
            except Exception as e:
                print(f"❌ 邮件推送失败: {e}")
                success = False
        
        return success
    
    def _generate_markdown_content(self, signal_data: Dict) -> str:
        """生成markdown格式的推送内容"""
        date = signal_data["date"]
        sentiment = signal_data["sentiment"]
        signals = signal_data["signals"]
        
        # 标题
        if signal_data["force_empty"]:
            title = f"⚠️ 【实盘信号-{date}】触发强制空仓"
            content = [
                f"## {title}",
                "",
                "### 📊 市场情绪",
                f"- 评分：**{sentiment['score']}分**",
                f"- 等级：**{sentiment['level']}**",
                f"- 仓位上限：**{sentiment['position_limit']:.0%}**",
                "",
                "### 交易计划",
                "触发强制空仓条件，今日不进行任何交易，建议空仓观望。",
                "",
                f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
            ]
        else:
            title = f"🎯 【实盘信号-{date}】可选标的{len(signals)}只"
            content = [
                f"## {title}",
                "",
                "### 📊 市场情绪",
                f"- 评分：**{sentiment['score']}分**",
                f"- 等级：**{sentiment['level']}**",
                f"- 仓位上限：**{sentiment['position_limit']:.0%}**",
                f"- 允许策略：**{', '.join(sentiment['allowed_strategies'])}**",
                f"- 预选池数量：**{signal_data['universe_size']}只**",
                "",
                "### 🎖️ 可选标的（按优先级排序）：",
            ]
            
            if signals:
                for idx, stock in enumerate(signals, 1):
                    lhb_tag = " 🎉龙虎榜" if stock["has_lhb"] else ""
                    content.append(f"#### {idx}. {stock['name']}({stock['ts_code']}){lhb_tag}")
                    content.append(f"- 策略：**{stock['strategy']}** | 行业：{stock['industry']}")
                    content.append(f"- 收盘价：**{stock['close']:.2f}** | 涨跌幅：**{stock['pct_chg']:.2f}%**")
                    content.append(f"- 建议买入价：≤**{stock['close'] * 1.01:.2f}**")
                    content.append(f"- 止损价：**{stock['close'] * 0.95:.2f}** | 止盈价：**{stock['close'] * 1.1:.2f}**")
                    if stock["has_lhb"]:
                        content.append(f"- 龙虎榜净买入：**{stock['lhb_net_buy']/10000:.1f}万** | 原因：{stock['lhb_reason']}")
                    content.append("")
            else:
                content.append("无符合条件的标的，建议空仓观望。")
            
            content.append("")
            content.append("### ⚠️ 交易纪律")
            content.append("1. 严格执行止损，触及止损价立即卖出")
            content.append("2. 单票仓位不超过20%，总仓位不超过上限")
            content.append("3. 持仓最多持有3天，到期强制卖出")
            content.append("")
            content.append(f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        
        return "\n".join(content)
    
    def _push_feishu(self, signal_data: Dict):
        """推送到飞书webhook"""
        content = self._generate_markdown_content(signal_data)
        data = {
            "msg_type": "interactive",
            "card": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content
                    }
                ],
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"实盘交易信号 {signal_data['date']}"
                    },
                    "template": "red" if signal_data["force_empty"] or not signal_data["signals"] else "green"
                }
            }
        }
        
        response = requests.post(
            self.config["feishu_webhook"],
            headers={"Content-Type": "application/json"},
            data=json.dumps(data),
            timeout=10
        )
        response.raise_for_status()
    
    def _push_wecom(self, signal_data: Dict):
        """推送到企业微信webhook"""
        content = self._generate_markdown_content(signal_data)
        data = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
        
        response = requests.post(
            self.config["wecom_webhook"],
            headers={"Content-Type": "application/json"},
            data=json.dumps(data),
            timeout=10
        )
        response.raise_for_status()
    
    def _push_dingtalk(self, signal_data: Dict):
        """推送到钉钉webhook"""
        content = self._generate_markdown_content(signal_data)
        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"实盘交易信号 {signal_data['date']}",
                "text": content
            }
        }
        
        response = requests.post(
            self.config["dingtalk_webhook"],
            headers={"Content-Type": "application/json"},
            data=json.dumps(data),
            timeout=10
        )
        response.raise_for_status()
    
    def _push_email(self, signal_data: Dict):
        """推送邮件"""
        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header
        
        smtp_config = self.config["smtp_config"]
        content = self._generate_markdown_content(signal_data)
        
        # 转换markdown为html（简单转换）
        html_content = content.replace("\n", "<br>").replace("**", "<strong>").replace("## ", "<h2>").replace("### ", "<h3>").replace("- ", "<li>")
        
        msg = MIMEText(html_content, "html", "utf-8")
        msg["From"] = Header(f"实盘信号推送 <{smtp_config['user']}>", "utf-8")
        msg["To"] = Header(smtp_config["to"], "utf-8")
        msg["Subject"] = Header(f"实盘交易信号 {signal_data['date']}", "utf-8")
        
        with smtplib.SMTP_SSL(smtp_config["host"], smtp_config["port"]) as server:
            server.login(smtp_config["user"], smtp_config["password"])
            server.sendmail(smtp_config["user"], smtp_config["to"].split(","), msg.as_string())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="实盘信号推送工具")
    parser.add_argument("--signal-file", required=True, help="信号JSON文件路径")
    parser.add_argument("--feishu", help="飞书webhook地址")
    parser.add_argument("--wecom", help="企业微信webhook地址")
    parser.add_argument("--dingtalk", help="钉钉webhook地址")
    
    args = parser.parse_args()
    
    # 读取信号文件
    with open(args.signal_file, "r", encoding="utf-8") as f:
        signal_data = json.load(f)
    
    # 配置推送器
    config = {}
    if args.feishu:
        config["feishu_webhook"] = args.feishu
    if args.wecom:
        config["wecom_webhook"] = args.wecom
    if args.dingtalk:
        config["dingtalk_webhook"] = args.dingtalk
    
    pusher = SignalPusher(config)
    success = pusher.push(signal_data)
    sys.exit(0 if success else 1)
