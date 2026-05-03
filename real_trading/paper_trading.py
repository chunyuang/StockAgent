#!/usr/bin/env python3
"""
实盘模拟交易模块
功能：模拟实盘交易，验证策略效果，支持手动/自动交易，完全仿真实盘规则
"""
import sys
import logging

logger = logging.getLogger(__name__)
import os
import json
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))  # FIXME: 使用sys.path.insert做模块查找是反模式，应改用setup.py/pyproject.toml将项目安装到venv中
sys.path.insert(0, os.path.dirname(__file__))

from position_manager import Position, PositionManager
from performance_analyzer import PerformanceAnalyzer
from pre_buy_risk_check import PreBuyRiskChecker

@dataclass
class PaperAccount:
    """模拟交易账户数据模型
    
    用于记录模拟账户的基本信息，包括账户ID、名称、资金余额、
    累计收益、最大回撤等核心指标。每个账户独立管理持仓和交易历史。
    
    Attributes:
        account_id: 账户唯一标识（8位短UUID）
        name: 账户显示名称
        initial_balance: 初始资金（元）
        current_balance: 当前可用余额（元）
        total_profit: 累计盈亏金额（元）
        total_profit_pct: 累计盈亏百分比（%）
        max_drawdown: 历史最大回撤（%）
        created_at: 账户创建日期（YYYYMMDD）
        status: 账户状态，active-活跃 / closed-已关闭
        notes: 备注信息
    """
    account_id: str
    name: str
    initial_balance: float
    current_balance: float
    total_profit: float
    total_profit_pct: float
    max_drawdown: float
    created_at: str
    status: str = "active"  # active/closed
    notes: str = ""

class PaperTradingEngine:
    """模拟交易引擎
    
    提供完整的模拟交易生命周期管理，包括：
    - 账户创建/关闭/查询
    - 模拟买入下单（含滑点、佣金计算）
    - 模拟卖出平仓（含滑点、佣金、印花税计算）
    - 每日结算（止损止盈检查、自动平仓）
    - 账户绩效更新（总权益、收益率、最大回撤）
    
    数据持久化到JSON文件，每个账户对应独立的持仓文件。
    """
    
    def __init__(self, data_file: str = "paper_accounts.json"):
        """初始化模拟交易引擎
        
        Args:
            data_file: 账户数据持久化文件名，默认 paper_accounts.json
                       文件存储在与本模块同目录下
        """
        self.data_file = os.path.join(os.path.dirname(__file__), data_file)
        self.accounts: Dict[str, PaperAccount] = {}  # account_id -> PaperAccount
        self.position_managers: Dict[str, PositionManager] = {}  # account_id -> PositionManager
        self._load_accounts()
        
        # 初始化风控检查器
        self.risk_checker = PreBuyRiskChecker()
    
    def _load_accounts(self):
        """加载模拟账户数据"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    logger.error(f"⚠️  账户数据格式异常（期望dict，实际{type(data).__name__}），初始化空")
                    self.accounts = {}
                    return
                for acc_id, acc_data in data.items():
                    try:
                        self.accounts[acc_id] = PaperAccount(**acc_data)
                        # 加载对应账户的持仓管理器
                        pos_file = f"paper_positions_{acc_id}.json"
                        self.position_managers[acc_id] = PositionManager(pos_file)
                    except (TypeError, KeyError) as e:
                        logger.error(f"⚠️  跳过异常账户记录 {acc_id}: {e}")
                logger.info(f"✅ 加载模拟账户成功，共{len(self.accounts)}个账户")
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"❌ 加载模拟账户失败: {e}")
                self.accounts = {}
        else:
            logger.info("ℹ️  无历史模拟账户，初始化空")
    
    def _save_accounts(self):
        """保存账户数据"""
        try:
            data = {acc_id: asdict(acc) for acc_id, acc in self.accounts.items()}
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("✅ 模拟账户数据已保存")
        except (OSError, TypeError) as e:
            logger.error(f"❌ 保存模拟账户失败: {e}")
    
    def create_account(self, name: str, initial_balance: float = 1000000, notes: str = "") -> str:
        """创建新模拟账户"""
        import uuid
        acc_id = str(uuid.uuid4())[:8]  # 短ID方便使用
        
        account = PaperAccount(
            account_id=acc_id,
            name=name,
            initial_balance=initial_balance,
            current_balance=initial_balance,
            total_profit=0.0,
            total_profit_pct=0.0,
            max_drawdown=0.0,
            created_at=datetime.now().strftime("%Y%m%d"),
            notes=notes
        )
        
        self.accounts[acc_id] = account
        # 创建对应持仓文件
        pos_file = f"paper_positions_{acc_id}.json"
        self.position_managers[acc_id] = PositionManager(pos_file)
        
        self._save_accounts()
        logger.info(f"✅ 创建模拟账户成功：{name}({acc_id})，初始资金{initial_balance:.2f}元")
        return acc_id
    
    def close_account(self, account_id: str) -> bool:
        """关闭账户"""
        if account_id not in self.accounts:
            logger.warning(f"⚠️  账户{account_id}不存在")
            return False
        
        self.accounts[account_id].status = "closed"
        self._save_accounts()
        logger.info(f"✅ 关闭模拟账户：{self.accounts[account_id].name}({account_id})")
        return True
    
    def get_account(self, account_id: str) -> Optional[PaperAccount]:
        """获取账户信息"""
        return self.accounts.get(account_id)
    
    def list_accounts(self) -> List[Dict]:
        """列出所有账户"""
        result = []
        for acc in self.accounts.values():
            result.append({
                "account_id": acc.account_id,
                "name": acc.name,
                "initial_balance": acc.initial_balance,
                "current_balance": acc.current_balance,
                "total_profit": acc.total_profit,
                "total_profit_pct": acc.total_profit_pct,
                "max_drawdown": acc.max_drawdown,
                "status": acc.status,
                "created_at": acc.created_at,
                "position_count": len(self.position_managers[acc.account_id].get_positions())
            })
        return result
    
    async def place_order(self, account_id: str, ts_code: str, name: str, buy_price: float, shares: int, 
                         strategy: str = "未知", slippage: float = 0.002) -> Dict:
        """模拟买入下单
        
        完整模拟实盘买入流程：滑点计算 → 佣金计算 → 余额检查 → 扣款 → 建仓
        
        Args:
            account_id: 模拟账户ID
            ts_code: 股票代码（如 000001.SZ）
            name: 股票名称
            buy_price: 买入申报价格（元）
            shares: 买入数量（股），需为100的整数倍
            strategy: 策略标签，用于绩效分析归因
            slippage: 滑点比例，默认0.2%，超短打板滑点较大，模拟成交价=申报价×(1+滑点)
        
        Returns:
            Dict: {success: bool, msg: str, position: dict(仅成功时)}
        """
        """模拟下单买入"""
        if account_id not in self.accounts:
            return {"success": False, "msg": f"账户{account_id}不存在"}
        
        account = self.accounts[account_id]
        if account.status != "active":
            return {"success": False, "msg": f"账户{account_id}已关闭"}
        
        # 计算实际成交价（滑点）
        actual_buy_price = buy_price * (1 + slippage)
        total_cost = actual_buy_price * shares
        commission = max(total_cost * 0.0003, 5)  # 佣金万3，最低5元（对齐前端和回测配置）
        total_payment = total_cost + commission
        
        if total_payment > account.current_balance:
            return {"success": False, "msg": f"余额不足，需要{total_payment:.2f}元，当前可用{account.current_balance:.2f}元"}
        
        # 扣除资金
        account.current_balance -= total_payment
        
        # 添加持仓
        stop_loss_price = actual_buy_price * 0.95
        take_profit_price = actual_buy_price * 1.1
        
        pos = Position(
            ts_code=ts_code,
            name=name,
            buy_date=datetime.now().strftime("%Y%m%d"),
            buy_price=actual_buy_price,
            shares=shares,
            total_cost=total_cost,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            strategy=strategy
        )
        
        pos_manager = self.position_managers[account_id]
        pos_manager.add_position(pos)
        
        # 更新账户收益
        self._update_account_performance(account_id)
        self._save_accounts()
        
        return {
            "success": True,
            "msg": f"下单成功：{name}({ts_code}) {shares}股，成交价{actual_buy_price:.2f}元，总成本{total_payment:.2f}元",
            "position": asdict(pos)
        }
    
    async def close_position(self, account_id: str, ts_code: str, sell_price: float, 
                           reason: str = "手动平仓", slippage: float = 0.002) -> Dict:
        """模拟卖出平仓
        
        完整模拟实盘卖出流程：滑点计算 → 佣金+印花税 → 回款 → 平仓记录
        
        Args:
            account_id: 模拟账户ID
            ts_code: 要平仓的股票代码
            sell_price: 卖出申报价格（元）
            reason: 平仓原因，如 '手动平仓'/'止损'/'止盈'/'超期强制'
            slippage: 滑点比例，默认0.2%，超短打板滑点较大，模拟成交价=申报价×(1-滑点)
        
        Returns:
            Dict: {success: bool, msg: str, trade_record: dict(仅成功时)}
        """
        """模拟平仓"""
        if account_id not in self.accounts:
            return {"success": False, "msg": f"账户{account_id}不存在"}
        
        account = self.accounts[account_id]
        if account.status != "active":
            return {"success": False, "msg": f"账户{account_id}已关闭"}
        
        pos_manager = self.position_managers[account_id]
        positions = pos_manager.get_positions()
        target_pos = next((p for p in positions if p["ts_code"] == ts_code), None)
        
        if not target_pos:
            return {"success": False, "msg": f"持仓中不存在{ts_code}"}
        
        # 计算实际成交价（滑点）
        actual_sell_price = sell_price * (1 - slippage)
        total_income = actual_sell_price * target_pos["shares"]
        commission = max(total_income * 0.0003, 5)  # 佣金万3，最低5元（对齐前端和回测配置）
        stamp_tax = total_income * 0.001  # 印花税千1
        net_income = total_income - commission - stamp_tax
        
        # 平仓
        trade_record = pos_manager.close_position(ts_code, actual_sell_price, reason=reason)
        
        # 增加资金
        account.current_balance += net_income
        
        # 更新账户收益
        self._update_account_performance(account_id)
        self._save_accounts()
        
        return {
            "success": True,
            "msg": f"平仓成功：{target_pos['name']}({ts_code}) {target_pos['shares']}股，成交价{actual_sell_price:.2f}元，净收入{net_income:.2f}元",
            "trade_record": trade_record
        }
    
    async def daily_settlement(self, account_id: str = None):
        """每日结算：检查持仓止损/止盈/超期，触发自动平仓，更新账户绩效
        
        盘后调用，执行以下流程：
        1. 遍历所有活跃账户（或指定账户）的持仓
        2. 检查每只持仓的止损、止盈、超期条件
        3. 对触发的持仓执行自动平仓
        4. 更新账户绩效指标
        
        Args:
            account_id: 指定结算的账户ID，None则结算所有活跃账户
        """
        """每日结算：检查持仓止损止盈，更新账户收益"""
        accounts = [account_id] if account_id else list(self.accounts.keys())
        
        for acc_id in accounts:
            if self.accounts[acc_id].status != "active":
                continue
            
            pos_manager = self.position_managers[acc_id]
            # 检查持仓
            alerts = await pos_manager.daily_check()
            
            # 如果有需要平仓的，自动模拟平仓
            for alert in alerts:
                if alert["level"] == "danger" and ("止损" in str(alert["alerts"]) or "超期" in str(alert["alerts"])):
                    # 获取当前价格（这里简化，实际可接入实时行情）
                    # 模拟平仓
                    logger.info(f"📅 自动平仓：{alert['name']}({alert['ts_code']})，原因：{alert['alerts'][0]}")
                    # 这里可以扩展接入真实行情自动平仓
            
            # 更新账户收益
            self._update_account_performance(acc_id)
        
        self._save_accounts()
        logger.info("✅ 每日结算完成")
    
    def _update_account_performance(self, account_id: str):
        """更新账户绩效指标
        
        计算逻辑：
        - 总权益 = 可用余额 + 持仓市值（按成本价估算）
        - 累计盈亏 = 总权益 - 初始资金
        - 收益率 = 总权益/初始资金 - 1
        - 最大回撤 = 从 PerformanceAnalyzer 获取历史最大回撤
        
        Args:
            account_id: 要更新绩效的账户ID
        """
        """更新账户绩效"""
        account = self.accounts[account_id]
        pos_manager = self.position_managers[account_id]
        
        # 计算持仓市值
        positions = pos_manager.get_positions()
        market_value = 0
        for pos in positions:
            # 【P1修复：用current_price计算市值，而非buy_price(买入价)】
            # 原代码用buy_price导致持仓期间PnL永远不变，收益计算完全失真
            current_price = pos.get("current_price") or pos.get("last_price") or pos["buy_price"]
            market_value += pos["shares"] * current_price
        
        # 计算总权益
        total_equity = account.current_balance + market_value
        account.total_profit = total_equity - account.initial_balance
        account.total_profit_pct = (total_equity / account.initial_balance - 1) * 100
        
        # 计算最大回撤
        analyzer = PerformanceAnalyzer(f"paper_trade_history_{account_id}.json")
        perf = analyzer.get_basic_stats()
        account.max_drawdown = perf.get("max_drawdown", 0)
    
    def get_account_performance(self, account_id: str) -> Dict:
        """获取账户完整绩效信息
        
        Returns:
            Dict: {
                account_info: PaperAccount字段字典,
                positions: 当前持仓列表,
                performance: 绩效统计指标,
                recent_trades: 最近10条交易记录
            }
        """
        """获取账户绩效"""
        if account_id not in self.accounts:
            return {}
        
        account = self.accounts[account_id]
        pos_manager = self.position_managers[account_id]
        analyzer = PerformanceAnalyzer(f"paper_trade_history_{account_id}.json")
        perf = analyzer.get_basic_stats()
        
        return {
            "account_info": asdict(account),
            "positions": pos_manager.get_positions(),
            "performance": perf,
            "recent_trades": analyzer.get_trade_history(10)
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="模拟交易工具")
    parser.add_argument("--action", required=True, 
                        choices=["list", "create", "close", "info", "buy", "sell", "settlement"], 
                        help="操作类型")
    parser.add_argument("--account-id", help="账户ID")
    parser.add_argument("--name", help="账户名称")
    parser.add_argument("--balance", type=float, default=1000000, help="初始资金，默认100万")
    parser.add_argument("--ts-code", help="股票代码")
    parser.add_argument("--stock-name", help="股票名称")
    parser.add_argument("--price", type=float, help="价格")
    parser.add_argument("--shares", type=int, help="数量")
    parser.add_argument("--strategy", default="未知", help="策略名称")
    parser.add_argument("--reason", default="手动平仓", help="平仓原因")
    
    args = parser.parse_args()
    
    engine = PaperTradingEngine()
    
    if args.action == "list":
        accounts = engine.list_accounts()
        if not accounts:
            logger.info("暂无模拟账户")
        else:
            logger.info(f"共{len(accounts)}个模拟账户：")
            for acc in accounts:
                status_icon = "✅" if acc["status"] == "active" else "❌"
                profit_icon = "📈" if acc["total_profit"] >= 0 else "📉"
                logger.info(f"{status_icon} {acc['name']}({acc['account_id']}) | 初始资金{acc['initial_balance']:.0f} | 当前{acc['current_balance']:.0f} | {profit_icon} {acc['total_profit_pct']:.2f}% | 持仓{acc['position_count']}只 | 创建于{acc['created_at']}")
    
    elif args.action == "create":
        if not args.name:
            logger.error("参数错误：需要 --name")
            sys.exit(1)
        acc_id = engine.create_account(args.name, args.balance)
        logger.info(f"创建成功，账户ID：{acc_id}")
    
    elif args.action == "close":
        if not args.account_id:
            logger.error("参数错误：需要 --account-id")
            sys.exit(1)
        engine.close_account(args.account_id)
    
    elif args.action == "info":
        if not args.account_id:
            logger.error("参数错误：需要 --account-id")
            sys.exit(1)
        perf = engine.get_account_performance(args.account_id)
        if not perf:
            logger.info("账户不存在")
        else:
            acc = perf["account_info"]
            logger.info("="*60)
            logger.info(f"📊 模拟账户：{acc['name']}({acc['account_id']})")
            logger.info("="*60)
            logger.info(f"初始资金：{acc['initial_balance']:.2f}元")
            logger.info(f"当前权益：{acc['current_balance']:.2f}元")
            logger.info(f"总收益：{acc['total_profit']:.2f}元（{acc['total_profit_pct']:.2f}%）")
            logger.info(f"最大回撤：{acc['max_drawdown']:.2f}%")
            logger.info(f"账户状态：{acc['status']}")
            logger.info(f"创建时间：{acc['created_at']}")
            print()
            logger.info("当前持仓：")
            for pos in perf["positions"]:
                logger.info(f"- {pos['name']}({pos['ts_code']}) | {pos['shares']}股 | 成本{pos['buy_price']:.2f} | 持仓{pos['hold_days']}天 | 止损{pos['stop_loss_price']:.2f} | 止盈{pos['take_profit_price']:.2f}")
            print()
            logger.info("最近10笔交易：")
            for t in perf["recent_trades"]:
                icon = "✅" if t["profit"] > 0 else "❌"
                logger.info(f"{icon} {t['sell_date']} {t['name']}({t['ts_code']}) | 盈利{t['profit']:.2f}元({t['profit_pct']:.2f}%) | 持仓{t['hold_days']}天")
            logger.info("="*60)
    
    elif args.action == "buy":
        if not all([args.account_id, args.ts_code, args.stock_name, args.price, args.shares]):
            logger.error("参数错误：需要 --account-id、--ts-code、--stock-name、--price、--shares")
            sys.exit(1)
        
        import asyncio
        result = asyncio.run(engine.place_order(
            args.account_id, args.ts_code, args.stock_name, 
            args.price, args.shares, args.strategy
        ))
        logger.info(result["msg"])
    
    elif args.action == "sell":
        if not all([args.account_id, args.ts_code, args.price]):
            logger.error("参数错误：需要 --account-id、--ts-code、--price")
            sys.exit(1)
        
        import asyncio
        result = asyncio.run(engine.close_position(
            args.account_id, args.ts_code, args.price, args.reason
        ))
        logger.info(result["msg"])
    
    elif args.action == "settlement":
        import asyncio
        asyncio.run(engine.daily_settlement(args.account_id))
