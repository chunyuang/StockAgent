#!/usr/bin/env python3
"""
实盘持仓管理模块
功能：记录持仓、自动检查止损止盈、持仓超期提醒、强制平仓提醒
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))  # FIXME: 使用sys.path.insert做模块查找是反模式，应改用setup.py/pyproject.toml将项目安装到venv中
sys.path.insert(0, os.path.dirname(__file__))

import json
import asyncio
from datetime import datetime
from typing import List, Dict
from dataclasses import dataclass, asdict

@dataclass
class Position:
    """持仓信息数据模型
    
    记录单只股票的完整持仓信息，包括买入信息、风控参数和策略标签。
    提供持仓天数计算、止损止盈触发检查等业务方法。
    
    Attributes:
        ts_code: 股票代码（如 000001.SZ）
        name: 股票名称
        buy_date: 买入日期（YYYYMMDD格式）
        buy_price: 买入成交价（元）
        shares: 持股数量（股）
        total_cost: 总成本（元），= 买入价 × 数量
        stop_loss_price: 止损价（元），跌破此价触发止损卖出
        take_profit_price: 止盈价（元），涨到此价触发止盈卖出
        max_hold_days: 最大持仓天数，超期强制卖出，默认3天
        strategy: 策略标签，用于绩效归因分析
        notes: 备注信息
    """
    ts_code: str
    name: str
    buy_date: str  # YYYYMMDD
    buy_price: float
    shares: int
    total_cost: float
    stop_loss_price: float
    take_profit_price: float
    max_hold_days: int = 3
    strategy: str = "未知"
    notes: str = ""
    
    def hold_days(self, current_date: str = None) -> int:
        """计算持仓天数（自然日）
        
        Args:
            current_date: 计算基准日期（YYYYMMDD），默认取当天
        
        Returns:
            int: 持仓天数，= current_date - buy_date
        """
        if not current_date:
            current_date = datetime.now().strftime("%Y%m%d")
        buy_dt = datetime.strptime(self.buy_date, "%Y%m%d")
        current_dt = datetime.strptime(current_date, "%Y%m%d")
        return (current_dt - buy_dt).days
    
    def should_force_close(self, current_date: str = None) -> bool:
        """是否应该强制平仓（持仓超期）
        
        超短策略核心风控：持仓超过 max_hold_days 天必须卖出，
        防止短线变中线、中线变长线的问题。
        
        Args:
            current_date: 计算基准日期（YYYYMMDD），默认取当天
        
        Returns:
            bool: True表示持仓超期，应强制平仓
        """
        return self.hold_days(current_date) >= self.max_hold_days
    
    def check_stop_loss(self, current_price: float) -> bool:
        """检查是否触发止损
        
        Args:
            current_price: 当前价格（元）
        
        Returns:
            bool: True表示当前价格已跌破止损价
        """
        return current_price <= self.stop_loss_price
    
    def check_take_profit(self, current_price: float) -> bool:
        """检查是否触发止盈
        
        Args:
            current_price: 当前价格（元）
        
        Returns:
            bool: True表示当前价格已达到止盈价
        """
        return current_price >= self.take_profit_price
    
    def current_profit_pct(self, current_price: float) -> float:
        """计算当前收益率
        
        Args:
            current_price: 当前价格（元）
        
        Returns:
            float: 收益率（%），正数盈利，负数亏损
        """
        return (current_price - self.buy_price) / self.buy_price * 100

class PositionManager:
    """持仓管理器
    
    管理单个账户的所有持仓，提供：
    - 持仓的增删查（add/close/get）
    - 信号驱动建仓（add_position_by_signal）
    - 每日风控检查（daily_check）：止损/止盈/超期自动告警
    - 交易历史记录和绩效统计
    
    数据持久化到JSON文件：positions.json + trade_history.json
    """
    
    def __init__(self, data_file: str = "positions.json"):
        self.data_file = os.path.join(os.path.dirname(__file__), data_file)
        self.positions: Dict[str, Position] = {}  # ts_code -> Position
        self._load_positions()
    
    def _load_positions(self):
        """加载持仓数据"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    print(f"⚠️  持仓数据格式异常（期望dict，实际{type(data).__name__}），初始化空持仓")
                    self.positions = {}
                    return
                for ts_code, pos_data in data.items():
                    try:
                        self.positions[ts_code] = Position(**pos_data)
                    except (TypeError, KeyError) as e:
                        print(f"⚠️  跳过异常持仓记录 {ts_code}: {e}")
                print(f"✅ 加载持仓数据成功，共{len(self.positions)}只持仓")
            except (json.JSONDecodeError, OSError) as e:
                print(f"❌ 加载持仓数据失败: {e}")
                self.positions = {}
        else:
            print("ℹ️  无历史持仓数据，初始化空持仓")
    
    def _save_positions(self):
        """保存持仓数据"""
        try:
            data = {ts_code: asdict(pos) for ts_code, pos in self.positions.items()}
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("✅ 持仓数据已保存")
        except (OSError, TypeError) as e:
            print(f"❌ 保存持仓数据失败: {e}")
    
    def add_position(self, position: Position) -> bool:
        """添加新持仓
        
        Args:
            position: Position对象，包含完整的持仓信息
        
        Returns:
            bool: True添加成功，False表示该股票已在持仓中（不允许重复建仓）
        """
        if position.ts_code in self.positions:
            print(f"⚠️  {position.ts_code} 已在持仓中，是否需要加仓？")
            return False
        
        self.positions[position.ts_code] = position
        self._save_positions()
        print(f"✅ 添加持仓：{position.name}({position.ts_code})，{position.shares}股，成本{position.buy_price:.2f}元")
        return True
    
    def add_position_by_signal(self, signal: Dict, buy_price: float = None, shares: int = None) -> bool:
        """通过选股信号创建持仓
        
        便捷方法：根据信号数据自动计算买入价、数量、止损止盈价。
        - 默认买入价 = 收盘价 × 1.01（应对高开）
        - 默认买入金额 = 1万元（100股整数倍）
        - 默认止损 = 买入价 × 0.95（5%）
        - 默认止盈 = 买入价 × 1.1（10%）
        
        Args:
            signal: 选股信号字典，需包含 ts_code/name/close/date 等字段
            buy_price: 自定义买入价，None则使用默认计算
            shares: 自定义买入数量，None则使用默认计算
        
        Returns:
            bool: True建仓成功
        """
        if not buy_price:
            # 默认买入价为收盘价上浮1%
            buy_price = signal["close"] * 1.01
        if not shares:
            # 默认买100股的整数倍，1万元
            shares = int(10000 / buy_price / 100) * 100
            if shares <= 0:
                shares = 100
        
        total_cost = buy_price * shares
        stop_loss_price = buy_price * 0.95  # 默认止损5%
        take_profit_price = buy_price * 1.1  # 默认止盈10%
        
        position = Position(
            ts_code=signal["ts_code"],
            name=signal["name"],
            buy_date=datetime.now().strftime("%Y%m%d"),
            buy_price=buy_price,
            shares=shares,
            total_cost=total_cost,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            strategy=signal.get("strategy", "未知"),
            notes=f"信号日期：{signal.get('date', datetime.now().strftime('%Y%m%d'))}"
        )
        
        return self.add_position(position)
    
    def close_position(self, ts_code: str, sell_price: float, sell_date: str = None, reason: str = "手动平仓") -> Dict:
        """平仓指定股票
        
        执行平仓流程：计算盈亏 → 记录交易历史 → 删除持仓 → 持久化
        
        Args:
            ts_code: 要平仓的股票代码
            sell_price: 卖出成交价（元）
            sell_date: 卖出日期（YYYYMMDD），默认当天
            reason: 平仓原因，用于交易历史记录
        
        Returns:
            Dict: 交易记录字典，包含盈亏详情；股票不在持仓中时返回空dict
        """
        if ts_code not in self.positions:
            print(f"⚠️  {ts_code} 不在持仓中")
            return {}
        
        pos = self.positions[ts_code]
        if not sell_date:
            sell_date = datetime.now().strftime("%Y%m%d")
        
        sell_amount = sell_price * pos.shares
        profit = sell_amount - pos.total_cost
        profit_pct = (sell_price - pos.buy_price) / pos.buy_price * 100
        hold_days = pos.hold_days(sell_date)
        
        # 记录交易历史
        trade_record = {
            "ts_code": ts_code,
            "name": pos.name,
            "buy_date": pos.buy_date,
            "sell_date": sell_date,
            "buy_price": pos.buy_price,
            "sell_price": sell_price,
            "shares": pos.shares,
            "profit": profit,
            "profit_pct": profit_pct,
            "hold_days": hold_days,
            "strategy": pos.strategy,
            "reason": reason
        }
        self._add_trade_history(trade_record)
        
        # 删除持仓
        del self.positions[ts_code]
        self._save_positions()
        
        print(f"✅ 平仓 {pos.name}({ts_code})，持仓{hold_days}天，盈利{profit:.2f}元({profit_pct:.2f}%)，原因：{reason}")
        return trade_record
    
    def _add_trade_history(self, record: Dict):
        """添加交易历史"""
        history_file = os.path.join(os.path.dirname(__file__), "trade_history.json")
        history = []
        if os.path.exists(history_file):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass  # 文件损坏或不存在，从空列表开始
        
        history.append(record)
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError) as e:
            print(f"❌ 保存交易历史失败: {e}")
    
    async def daily_check(self, current_date: str = None) -> List[Dict]:
        """每日盘后持仓风控检查
        
        从MongoDB获取当日行情，逐只检查：
        1. 持仓超期 → danger级别，建议强制平仓
        2. 触发止损（最低价≤止损价） → danger级别，建议立即卖出
        3. 接近止损（5%以内） → warning级别
        4. 触发止盈（最高价≥止盈价） → success级别，建议止盈
        5. 接近止盈（5%以内） → warning级别
        
        Args:
            current_date: 检查日期（YYYYMMDD），默认当天
        
        Returns:
            List[Dict]: 告警列表，每条包含 ts_code/name/alerts/level 等字段
        """
        if not current_date:
            current_date = datetime.now().strftime("%Y%m%d")
        
        print(f"========== 持仓每日检查 {current_date} ==========")
        alerts = []
        
        if not self.positions:
            print("ℹ️  当前无持仓")
            return alerts
        
        # 获取当日行情数据
        from core.managers import mongo_manager
        ts_codes = list(self.positions.keys())
        
        price_map = {}
        try:
            daily_data = await mongo_manager.find_many(
                "stock_daily_ak_full",
                {"ts_code": {"$in": ts_codes}, "trade_date": int(current_date)},
                projection={"ts_code": 1, "close": 1, "pct_chg": 1, "high": 1, "low": 1}
            )
            if daily_data:
                price_map = {x.get("ts_code", ""): x for x in daily_data if x.get("ts_code")}
        except (ConnectionError, OSError, ValueError) as e:
            print(f"⚠️  获取行情数据失败: {e}，将使用成本价代替")
        except Exception as e:
            print(f"⚠️  获取行情数据异常: {e}，将使用成本价代替")
        
        for ts_code, pos in self.positions.items():
            daily = price_map.get(ts_code, {})
            current_price = daily.get("close", pos.buy_price) if isinstance(daily, dict) else pos.buy_price
            high = daily.get("high", current_price) if isinstance(daily, dict) else current_price
            low = daily.get("low", current_price) if isinstance(daily, dict) else current_price
            pct_chg = daily.get("pct_chg", 0) if isinstance(daily, dict) else 0
            
            alert = {
                "ts_code": ts_code,
                "name": pos.name,
                "current_price": current_price,
                "pct_chg": pct_chg,
                "hold_days": pos.hold_days(current_date),
                "profit_pct": pos.current_profit_pct(current_price),
                "alerts": []
            }
            
            # 检查强制平仓
            if pos.should_force_close(current_date):
                alert["alerts"].append(f"⚠️  持仓超期：已持有{alert['hold_days']}天，超过{pos.max_hold_days}天上限，建议强制平仓")
                alert["level"] = "danger"
            
            # 检查止损
            if low <= pos.stop_loss_price:
                alert["alerts"].append(f"🔴 触发止损：最低价{low:.2f} ≤ 止损价{pos.stop_loss_price:.2f}，建议立即卖出")
                alert["level"] = "danger"
            elif current_price <= pos.stop_loss_price * 1.05:
                alert["alerts"].append(f"🟡 接近止损：当前价{current_price:.2f} 接近止损价{pos.stop_loss_price:.2f}，注意风险")
                alert["level"] = "warning"
            
            # 检查止盈
            if high >= pos.take_profit_price:
                alert["alerts"].append(f"🟢 触发止盈：最高价{high:.2f} ≥ 止盈价{pos.take_profit_price:.2f}，建议止盈")
                alert["level"] = "success"
            elif current_price >= pos.take_profit_price * 0.95:
                alert["alerts"].append(f"🟡 接近止盈：当前价{current_price:.2f} 接近止盈价{pos.take_profit_price:.2f}，注意落袋为安")
                alert["level"] = "warning"
            
            if alert["alerts"]:
                alerts.append(alert)
                print(f"{alert['level'] == 'danger' and '🔴' or alert['level'] == 'warning' and '🟡' or '🟢'} {pos.name}({ts_code})：")
                for a in alert["alerts"]:
                    print(f"   - {a}")
            else:
                print(f"✅ {pos.name}({ts_code})：当前盈利{alert['profit_pct']:.2f}%，持仓{alert['hold_days']}天，正常")
        
        return alerts
    
    def get_positions(self) -> List[Dict]:
        """获取所有持仓"""
        result = []
        for pos in self.positions.values():
            result.append({
                "ts_code": pos.ts_code,
                "name": pos.name,
                "buy_date": pos.buy_date,
                "buy_price": pos.buy_price,
                "shares": pos.shares,
                "total_cost": pos.total_cost,
                "stop_loss_price": pos.stop_loss_price,
                "take_profit_price": pos.take_profit_price,
                "hold_days": pos.hold_days(),
                "strategy": pos.strategy,
                "notes": pos.notes
            })
        return result
    
    def get_trade_history(self, limit: int = 100) -> List[Dict]:
        """获取交易历史"""
        history_file = os.path.join(os.path.dirname(__file__), "trade_history.json")
        if not os.path.exists(history_file):
            return []
        
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            if not isinstance(history, list):
                print(f"⚠️  交易历史格式异常，期望list，实际{type(history).__name__}")
                return []
            # 按卖出日期倒序
            history.sort(key=lambda x: x.get("sell_date", ""), reverse=True)
            return history[:limit]
        except (json.JSONDecodeError, OSError, KeyError) as e:
            print(f"⚠️  读取交易历史失败: {e}")
            return []
    
    def get_performance_summary(self) -> Dict:
        """获取绩效统计摘要
        
        基于全部交易历史计算：
        - 总交易次数、胜率、总盈利
        - 平均每笔收益率
        - 最大回撤（简单峰值法）
        - 平均持仓天数
        
        Returns:
            Dict: 绩效统计字典，无交易记录时返回全零默认值
        """
        default_result = {
            "total_trades": 0,
            "win_rate": 0,
            "total_profit": 0,
            "avg_profit_pct": 0,
            "max_drawdown": 0,
            "avg_hold_days": 0
        }
        history = self.get_trade_history()
        if not history:
            return default_result
        
        try:
            total_trades = len(history)
            win_trades = [t for t in history if t.get("profit", 0) > 0]
            lose_trades = [t for t in history if t.get("profit", 0) <= 0]
            win_rate = len(win_trades) / total_trades * 100 if total_trades > 0 else 0
            total_profit = sum(t.get("profit", 0) for t in history)
            avg_profit_pct = sum(t.get("profit_pct", 0) for t in history) / total_trades if total_trades > 0 else 0
            avg_hold_days = sum(t.get("hold_days", 0) for t in history) / total_trades if total_trades > 0 else 0
            
            # 计算最大回撤（简单版）
            balance = 0
            max_balance = 0
            max_drawdown = 0
            for trade in sorted(history, key=lambda x: x.get("sell_date", "")):
                balance += trade.get("profit", 0)
                if balance > max_balance:
                    max_balance = balance
                drawdown = (max_balance - balance) / max_balance * 100 if max_balance > 0 else 0
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
            
            return {
                "total_trades": total_trades,
                "win_trades": len(win_trades),
                "lose_trades": total_trades - len(win_trades),
                "win_rate": round(win_rate, 2),
                "total_profit": round(total_profit, 2),
                "avg_profit_pct": round(avg_profit_pct, 2),
                "max_drawdown": round(max_drawdown, 2),
                "avg_hold_days": round(avg_hold_days, 1),
                "latest_trade_date": history[0].get("sell_date", "") if history else ""
            }
        except (KeyError, TypeError, ZeroDivisionError) as e:
            print(f"⚠️  计算绩效统计失败: {e}")
            return default_result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="持仓管理工具")
    parser.add_argument("--action", required=True, choices=["list", "add", "close", "check", "history", "performance"], help="操作类型")
    parser.add_argument("--ts-code", help="股票代码")
    parser.add_argument("--name", help="股票名称")
    parser.add_argument("--buy-price", type=float, help="买入价格")
    parser.add_argument("--shares", type=int, help="买入数量")
    parser.add_argument("--sell-price", type=float, help="卖出价格")
    parser.add_argument("--reason", help="平仓原因")
    parser.add_argument("--date", help="日期(YYYYMMDD)")
    
    args = parser.parse_args()
    
    manager = PositionManager()
    
    if args.action == "list":
        positions = manager.get_positions()
        if not positions:
            print("当前无持仓")
        else:
            print(f"当前持仓共{len(positions)}只：")
            for pos in positions:
                print(f"{pos['name']}({pos['ts_code']}) | 成本{pos['buy_price']:.2f} | 持仓{pos['hold_days']}天 | 止损{pos['stop_loss_price']:.2f} | 止盈{pos['take_profit_price']:.2f}")
    
    elif args.action == "add":
        if not all([args.ts_code, args.name, args.buy_price, args.shares]):
            print("参数错误：需要 --ts-code、--name、--buy-price、--shares")
            sys.exit(1)
        
        pos = Position(
            ts_code=args.ts_code,
            name=args.name,
            buy_date=args.date or datetime.now().strftime("%Y%m%d"),
            buy_price=args.buy_price,
            shares=args.shares,
            total_cost=args.buy_price * args.shares,
            stop_loss_price=args.buy_price * 0.95,
            take_profit_price=args.buy_price * 1.1
        )
        manager.add_position(pos)
    
    elif args.action == "close":
        if not all([args.ts_code, args.sell_price]):
            print("参数错误：需要 --ts-code、--sell-price")
            sys.exit(1)
        manager.close_position(args.ts_code, args.sell_price, args.date, args.reason or "手动平仓")
    
    elif args.action == "check":
        asyncio.run(manager.daily_check(args.date))
    
    elif args.action == "history":
        history = manager.get_trade_history(20)
        print(f"最近{len(history)}笔交易：")
        for t in history:
            profit_icon = "✅" if t["profit"] > 0 else "❌"
            print(f"{t['sell_date']} {profit_icon} {t['name']}({t['ts_code']}) | 盈利{t['profit']:.2f}元({t['profit_pct']:.2f}%) | 持仓{t['hold_days']}天 | 原因：{t['reason']}")
    
    elif args.action == "performance":
        perf = manager.get_performance_summary()
        print("="*50)
        print("📊 实盘绩效统计")
        print("="*50)
        print(f"总交易次数：{perf['total_trades']}次")
        print(f"胜率：{perf['win_rate']}%（{perf['win_trades']}胜{perf['lose_trades']}负）")
        print(f"总盈利：{perf['total_profit']:.2f}元")
        print(f"平均每笔收益：{perf['avg_profit_pct']:.2f}%")
        print(f"最大回撤：{perf['max_drawdown']:.2f}%")
        print(f"平均持仓天数：{perf['avg_hold_days']}天")
        if perf['latest_trade_date']:
            print(f"最近交易日期：{perf['latest_trade_date']}")
        print("="*50)
