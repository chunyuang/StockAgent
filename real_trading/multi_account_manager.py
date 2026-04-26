#!/usr/bin/env python3
"""
多账户管理模块
功能：管理多个实盘/模拟账户，支持独立风控、独立策略、汇总统计、批量操作
"""
import sys
import os
import json
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))  # FIXME: 使用sys.path.insert做模块查找是反模式，应改用setup.py/pyproject.toml将项目安装到venv中
sys.path.insert(0, os.path.dirname(__file__))

from position_manager import PositionManager
from performance_analyzer import PerformanceAnalyzer

@dataclass
class TradingAccount:
    """交易账户"""
    account_id: str
    name: str
    account_type: str  # real/paper
    status: str  # active/disabled
    strategy: str  # 绑定的策略名称
    risk_level: str  # low/medium/high
    max_position: float
    max_single_position: float
    stop_loss_pct: float
    take_profit_pct: float
    max_hold_days: int
    created_at: str
    updated_at: str
    broker: str = ""
    api_key: str = ""  # 仅存储掩码/占位，真实值通过 get_api_credentials() 从环境变量读取
    api_secret: str = ""  # 同上
    notes: str = ""

    def get_api_credentials(self) -> tuple[str, str]:
        """从环境变量获取API凭证，格式: {BROKER}_{ACCOUNT_ID}_API_KEY / _API_SECRET
        
        环境变量命名规则：
        - 券商为空: {ACCOUNT_ID}_API_KEY, {ACCOUNT_ID}_API_SECRET
        - 券商非空: {BROKER}_{ACCOUNT_ID}_API_KEY, {BROKER}_{ACCOUNT_ID}_API_SECRET
        
        Returns:
            (api_key, api_secret) 元组，未配置则返回空字符串
        """
        prefix = f"{self.broker.upper()}_{self.account_id}" if self.broker else self.account_id
        api_key = os.environ.get(f"{prefix}_API_KEY", "")
        api_secret = os.environ.get(f"{prefix}_API_SECRET", "")
        return api_key, api_secret

class MultiAccountManager:
    """多账户管理器"""
    
    def __init__(self, config_file: str = "multi_accounts.json"):
        self.config_file = os.path.join(os.path.dirname(__file__), config_file)
        self.accounts: Dict[str, TradingAccount] = {}
        self.position_managers: Dict[str, PositionManager] = {}
        self.performance_analyzers: Dict[str, PerformanceAnalyzer] = {}
        self._load_config()
    
    def _load_config(self):
        """加载账户配置"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for acc_id, acc_data in data.items():
                        self.accounts[acc_id] = TradingAccount(**acc_data)
                        # 初始化对应管理器
                        pos_file = f"positions_{acc_id}.json"
                        self.position_managers[acc_id] = PositionManager(pos_file)
                        perf_file = f"trade_history_{acc_id}.json"
                        self.performance_analyzers[acc_id] = PerformanceAnalyzer(perf_file)
                print(f"✅ 加载多账户配置成功，共{len(self.accounts)}个账户")
            except Exception as e:
                print(f"❌ 加载多账户配置失败: {e}")
                self.accounts = {}
        else:
            print("ℹ️  无多账户配置，初始化空")
    
    def _save_config(self):
        """保存账户配置"""
        try:
            data = {acc_id: asdict(acc) for acc_id, acc in self.accounts.items()}
            # 敏感信息掩码保存
            for acc_id in data:
                if data[acc_id]["api_key"]:
                    data[acc_id]["api_key"] = "***" + data[acc_id]["api_key"][-4:] if len(data[acc_id]["api_key"]) >4 else "***"
                if data[acc_id]["api_secret"]:
                    data[acc_id]["api_secret"] = "***"
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("✅ 多账户配置已保存")
        except Exception as e:
            print(f"❌ 保存多账户配置失败: {e}")
    
    def add_account(self, name: str, account_type: str = "paper", strategy: str = "default",
                  risk_level: str = "medium", **kwargs) -> str:
        """添加新账户"""
        import uuid
        acc_id = str(uuid.uuid4())[:8]
        
        # 风险等级对应默认参数
        risk_config = {
            "low": {"max_position": 0.3, "max_single_position": 0.1, "stop_loss_pct": 0.03, "take_profit_pct": 0.08, "max_hold_days": 2},
            "medium": {"max_position": 0.7, "max_single_position": 0.2, "stop_loss_pct": 0.05, "take_profit_pct": 0.1, "max_hold_days": 3},
            "high": {"max_position": 0.9, "max_single_position": 0.3, "stop_loss_pct": 0.08, "take_profit_pct": 0.15, "max_hold_days": 5},
        }
        
        config = risk_config[risk_level]
        config.update(kwargs)
        
        account = TradingAccount(
            account_id=acc_id,
            name=name,
            account_type=account_type,
            status="active",
            strategy=strategy,
            risk_level=risk_level,
            max_position=config["max_position"],
            max_single_position=config["max_single_position"],
            stop_loss_pct=config["stop_loss_pct"],
            take_profit_pct=config["take_profit_pct"],
            max_hold_days=config["max_hold_days"],
            created_at=datetime.now().strftime("%Y%m%d"),
            updated_at=datetime.now().strftime("%Y%m%d"),
            broker=kwargs.get("broker", ""),
            notes=kwargs.get("notes", "")
        )
        
        # 敏感信息：不再通过参数直接存储，提示用户使用环境变量
        if "api_key" in kwargs:
            print(f"⚠️  api_key不应通过参数传入，请设置环境变量 {kwargs.get('broker', '').upper()}_{acc_id}_API_KEY")
        if "api_secret" in kwargs:
            print(f"⚠️  api_secret不应通过参数传入，请设置环境变量 {kwargs.get('broker', '').upper()}_{acc_id}_API_SECRET")
        
        self.accounts[acc_id] = account
        
        # 初始化对应持仓和绩效文件
        pos_file = f"positions_{acc_id}.json"
        self.position_managers[acc_id] = PositionManager(pos_file)
        perf_file = f"trade_history_{acc_id}.json"
        self.performance_analyzers[acc_id] = PerformanceAnalyzer(perf_file)
        
        self._save_config()
        print(f"✅ 添加账户成功：{name}({acc_id})，类型：{account_type}，风险等级：{risk_level}")
        return acc_id
    
    def update_account(self, account_id: str, **kwargs) -> bool:
        """更新账户配置"""
        if account_id not in self.accounts:
            print(f"⚠️  账户{account_id}不存在")
            return False
        
        account = self.accounts[account_id]
        
        # 更新允许修改的字段
        allowed_fields = ["name", "status", "strategy", "risk_level", "max_position", 
                         "max_single_position", "stop_loss_pct", "take_profit_pct", 
                         "max_hold_days", "broker", "notes"]  # api_key/api_secret 已移除，请使用环境变量
        
        for field, value in kwargs.items():
            if field in allowed_fields and hasattr(account, field):
                setattr(account, field, value)
        
        account.updated_at = datetime.now().strftime("%Y%m%d")
        
        # 如果修改了风险等级，同步更新对应参数
        if "risk_level" in kwargs:
            risk_config = {
                "low": {"max_position": 0.3, "max_single_position": 0.1, "stop_loss_pct": 0.03, "take_profit_pct": 0.08, "max_hold_days": 2},
                "medium": {"max_position": 0.7, "max_single_position": 0.2, "stop_loss_pct": 0.05, "take_profit_pct": 0.1, "max_hold_days": 3},
                "high": {"max_position": 0.9, "max_single_position": 0.3, "stop_loss_pct": 0.08, "take_profit_pct": 0.15, "max_hold_days": 5},
            }
            config = risk_config[kwargs["risk_level"]]
            for k, v in config.items():
                setattr(account, k, v)
        
        self._save_config()
        print(f"✅ 更新账户成功：{account.name}({account_id})")
        return True
    
    def delete_account(self, account_id: str) -> bool:
        """删除账户"""
        if account_id not in self.accounts:
            print(f"⚠️  账户{account_id}不存在")
            return False
        
        del self.accounts[account_id]
        if account_id in self.position_managers:
            del self.position_managers[account_id]
        if account_id in self.performance_analyzers:
            del self.performance_analyzers[account_id]
        
        self._save_config()
        print(f"✅ 删除账户成功：{account_id}")
        return True
    
    def list_accounts(self) -> List[Dict]:
        """列出所有账户"""
        result = []
        for acc in self.accounts.values():
            # 获取基本信息
            pos_count = len(self.position_managers[acc.account_id].get_positions())
            perf = self.performance_analyzers[acc.account_id].get_basic_stats()
            
            result.append({
                "account_id": acc.account_id,
                "name": acc.name,
                "type": acc.account_type,
                "status": acc.status,
                "strategy": acc.strategy,
                "risk_level": acc.risk_level,
                "total_profit": perf.get("total_profit", 0),
                "total_profit_pct": perf.get("total_profit_pct", 0),
                "win_rate": perf.get("win_rate", 0),
                "position_count": pos_count,
                "created_at": acc.created_at,
                "broker": acc.broker
            })
        return result
    
    def get_account_info(self, account_id: str) -> Optional[Dict]:
        """获取账户详细信息"""
        if account_id not in self.accounts:
            return None
        
        acc = self.accounts[account_id]
        positions = self.position_managers[account_id].get_positions()
        perf = self.performance_analyzers[account_id].get_basic_stats()
        recent_trades = self.performance_analyzers[account_id].get_trade_history(10)
        
        return {
            "account_info": asdict(acc),
            "positions": positions,
            "performance": perf,
            "recent_trades": recent_trades
        }
    
    async def run_daily_routine(self):
        """每日例行任务：所有账户检查持仓、结算、生成信号"""
        print("🌞 开始执行所有账户每日例行任务")
        
        for acc_id, account in self.accounts.items():
            if account.status != "active":
                continue
            
            print(f"\n📋 处理账户：{account.name}({acc_id})")
            
            # 1. 每日持仓检查
            pos_manager = self.position_managers[acc_id]
            alerts = await pos_manager.daily_check()
            
            if alerts:
                print(f"⚠️  账户{account.name}有{len(alerts)}条提醒：")
                for alert in alerts:
                    print(f"   - {alert['title']}: {alert['content']}")
            
            # 2. 生成当日信号（这里可以扩展调用信号生成器）
            # 3. 模拟/实盘下单（根据配置）
            # 4. 每日结算
        
        print("\n✅ 所有账户每日例行任务执行完成")
    
    def get_summary_report(self) -> str:
        """生成所有账户汇总报告"""
        accounts = self.list_accounts()
        if not accounts:
            return "ℹ️  无账户"
        
        total_profit = sum(acc["total_profit"] for acc in accounts)
        avg_win_rate = np.mean([acc["win_rate"] for acc in accounts if acc["win_rate"] > 0]) if accounts else 0
        active_count = len([acc for acc in accounts if acc["status"] == "active"])
        
        report_lines = [
            "# 📊 多账户汇总报告",
            "",
            "## 🔹 总览",
            f"- 总账户数：{len(accounts)}个（活跃{active_count}个）",
            f"- 总盈利：{total_profit:.2f}元",
            f"- 平均胜率：{avg_win_rate:.2f}%",
            f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 📋 账户列表",
            "",
            "| 账户ID | 名称 | 类型 | 状态 | 策略 | 风险等级 | 总盈利 | 胜率 | 持仓数 | 创建时间 |",
            "|--------|------|------|------|------|----------|--------|------|--------|----------|",
        ]
        
        for acc in accounts:
            status_icon = "✅" if acc["status"] == "active" else "❌"
            type_icon = "💵" if acc["type"] == "real" else "📝"
            profit_icon = "📈" if acc["total_profit"] >= 0 else "📉"
            report_lines.append(
                f"| {acc['account_id']} | {acc['name']} | {type_icon} {acc['type']} | {status_icon} | {acc['strategy']} | {acc['risk_level']} | {profit_icon} {acc['total_profit']:.2f}元 | {acc['win_rate']:.2f}% | {acc['position_count']}只 | {acc['created_at']} |"
            )
        
        return "\n".join(report_lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="多账户管理工具")
    parser.add_argument("--action", required=True, 
                        choices=["list", "add", "update", "delete", "info", "summary", "daily"], 
                        help="操作类型")
    parser.add_argument("--account-id", help="账户ID")
    parser.add_argument("--name", help="账户名称")
    parser.add_argument("--type", choices=["real", "paper"], default="paper", help="账户类型：real(实盘)/paper(模拟)，默认paper")
    parser.add_argument("--strategy", default="default", help="绑定策略名称")
    parser.add_argument("--risk-level", choices=["low", "medium", "high"], default="medium", help="风险等级：low/medium/high，默认medium")
    parser.add_argument("--broker", help="券商名称")
    parser.add_argument("--notes", help="备注")
    parser.add_argument("--output", help="输出汇总报告路径")
    
    args = parser.parse_args()
    
    manager = MultiAccountManager()
    
    if args.action == "list":
        accounts = manager.list_accounts()
        if not accounts:
            print("暂无账户")
        else:
            print(f"共{len(accounts)}个账户：")
            for acc in accounts:
                status_icon = "✅" if acc["status"] == "active" else "❌"
                type_icon = "💵" if acc["type"] == "real" else "📝"
                profit_icon = "📈" if acc["total_profit"] >= 0 else "📉"
                print(f"{status_icon} {acc['name']}({acc['account_id']}) | {type_icon} {acc['type']} | {acc['strategy']} | {acc['risk_level']} | {profit_icon} {acc['total_profit']:.2f}元 | 胜率{acc['win_rate']:.2f}% | 持仓{acc['position_count']}只")
    
    elif args.action == "add":
        if not args.name:
            print("参数错误：需要 --name")
            sys.exit(1)
        
        # 收集额外参数
        kwargs = {}
        if args.broker:
            kwargs["broker"] = args.broker
        if args.notes:
            kwargs["notes"] = args.notes
        
        acc_id = manager.add_account(
            args.name, args.type, args.strategy, args.risk_level, **kwargs
        )
        print(f"账户ID：{acc_id}")
    
    elif args.action == "update":
        if not args.account_id:
            print("参数错误：需要 --account-id")
            sys.exit(1)
        
        kwargs = {}
        if args.name:
            kwargs["name"] = args.name
        if args.strategy:
            kwargs["strategy"] = args.strategy
        if args.risk_level:
            kwargs["risk_level"] = args.risk_level
        if args.broker:
            kwargs["broker"] = args.broker
        if args.notes:
            kwargs["notes"] = args.notes
        
        manager.update_account(args.account_id, **kwargs)
    
    elif args.action == "delete":
        if not args.account_id:
            print("参数错误：需要 --account-id")
            sys.exit(1)
        manager.delete_account(args.account_id)
    
    elif args.action == "info":
        if not args.account_id:
            print("参数错误：需要 --account-id")
            sys.exit(1)
        info = manager.get_account_info(args.account_id)
        if not info:
            print("账户不存在")
        else:
            acc = info["account_info"]
            print("="*60)
            print(f"📋 账户信息：{acc['name']}({acc['account_id']})")
            print("="*60)
            print(f"类型：{acc['account_type']} | 状态：{acc['status']} | 策略：{acc['strategy']} | 风险等级：{acc['risk_level']}")
            print(f"最大仓位：{acc['max_position']:.0%} | 单票最大：{acc['max_single_position']:.0%}")
            print(f"止损：{acc['stop_loss_pct']:.1%} | 止盈：{acc['take_profit_pct']:.1%} | 最长持仓：{acc['max_hold_days']}天")
            print(f"券商：{acc['broker']} | 创建时间：{acc['created_at']} | 备注：{acc['notes']}")
            print()
            print("当前持仓：")
            for pos in info["positions"]:
                print(f"- {pos['name']}({pos['ts_code']}) | {pos['shares']}股 | 成本{pos['buy_price']:.2f} | 持仓{pos['hold_days']}天")
            print()
            perf = info["performance"]
            print("绩效表现：")
            print(f"总盈利：{perf['total_profit']:.2f}元（{perf['total_profit_pct']:.2f}%） | 胜率：{perf['win_rate']:.2f}% | 最大回撤：{perf['max_drawdown']:.2f}%")
            print(f"交易次数：{perf['total_trades']}次 | 平均持仓天数：{perf['avg_hold_days']}天")
            print("="*60)
    
    elif args.action == "summary":
        report = manager.get_summary_report()
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"✅ 汇总报告已保存到：{args.output}")
        else:
            print("\n" + "="*80)
            print(report)
            print("="*80)
    
    elif args.action == "daily":
        asyncio.run(manager.run_daily_routine())
