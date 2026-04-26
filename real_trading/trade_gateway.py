#!/usr/bin/env python3
"""
实盘交易对接网关
框架设计，支持扩展对接不同券商/量化平台API，提供统一的交易接口
"""
import sys
import os
from datetime import datetime
from typing import List, Dict, Optional
from abc import ABC, abstractmethod

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))  # FIXME: 使用sys.path.insert做模块查找是反模式，应改用setup.py/pyproject.toml将项目安装到venv中
sys.path.insert(0, os.path.dirname(__file__))

class BaseTradeGateway(ABC):
    """交易网关抽象基类
    
    定义统一的交易接口协议，所有券商对接都必须实现这些方法：
    - connect/disconnect: 连接管理
    - get_account_info/get_positions: 账户查询
    - place_order/cancel_order/get_order_status: 订单管理
    - get_trade_history/get_realtime_quote: 数据查询
    
    子类实现：SimulatedGateway（模拟）、FutuGateway（富途）、TigerGateway（老虎）等
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.connected = False
    
    @abstractmethod
    def connect(self) -> bool:
        """连接交易接口"""
        pass
    
    @abstractmethod
    def disconnect(self) -> bool:
        """断开连接"""
        pass
    
    @abstractmethod
    def get_account_info(self) -> Dict:
        """获取账户信息：资金、持仓、可用余额等"""
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Dict]:
        """获取持仓列表"""
        pass
    
    @abstractmethod
    def place_order(self, ts_code: str, price: float, quantity: int, order_type: str = "limit") -> Dict:
        """下单
        
        Args:
            ts_code: 股票代码（如 000001.SZ）
            price: 委托价格（元）
            quantity: 委托数量（股），需为100的整数倍
            order_type: 委托类型 limit-限价 / market-市价
        
        Returns:
            Dict: 订单信息，至少包含 order_id 和 success 字段
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> Dict:
        """查询订单状态"""
        pass
    
    @abstractmethod
    def get_trade_history(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """获取交易历史"""
        pass
    
    @abstractmethod
    def get_realtime_quote(self, ts_code: str) -> Dict:
        """获取实时行情"""
        pass

class SimulatedGateway(BaseTradeGateway):
    """模拟交易网关，用于测试验证
    
    完全模拟实盘交易规则：
    - 买入：扣除资金+佣金（万2，最低5元）
    - 卖出：回款-佣金-印花税（千1）
    - 加仓：加权平均成本价
    - 100%模拟成交，无滑点
    """
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.balance = config.get("initial_balance", 1000000)
        self.positions = {}  # ts_code -> {"shares": int, "cost_price": float}
        self.order_id_counter = 1
        self.orders = {}
    
    def connect(self) -> bool:
        self.connected = True
        print("✅ 模拟交易网关连接成功")
        return True
    
    def disconnect(self) -> bool:
        self.connected = False
        print("✅ 模拟交易网关断开连接")
        return True
    
    def get_account_info(self) -> Dict:
        if not self.connected:
            raise Exception("网关未连接")
        
        # 计算持仓市值
        market_value = 0
        for ts_code, pos in self.positions.items():
            # 模拟用成本价计算市值
            market_value += pos["shares"] * pos["cost_price"]
        
        return {
            "total_asset": self.balance + market_value,
            "available_balance": self.balance,
            "market_value": market_value,
            "frozen_balance": 0,
            "pnl": market_value - sum(pos["shares"] * pos["cost_price"] for pos in self.positions.values())
        }
    
    def get_positions(self) -> List[Dict]:
        if not self.connected:
            raise Exception("网关未连接")
        
        result = []
        for ts_code, pos in self.positions.items():
            result.append({
                "ts_code": ts_code,
                "shares": pos["shares"],
                "cost_price": pos["cost_price"],
                "market_value": pos["shares"] * pos["cost_price"],
                "pnl": 0  # 模拟不计算实时盈亏
            })
        return result
    
    def place_order(self, ts_code: str, price: float, quantity: int, order_type: str = "limit") -> Dict:
        if not self.connected:
            raise Exception("网关未连接")
        
        order_id = f"SIM{self.order_id_counter}"
        self.order_id_counter += 1
        
        # 模拟100%成交
        total_cost = price * quantity
        commission = max(total_cost * 0.0003, 5)  # 佣金万3，对齐前端和回测配置
        stamp_tax = total_cost * 0.001 if order_type == "sell" else 0
        total_payment = total_cost + commission + stamp_tax
        
        if order_type == "buy":
            if total_payment > self.balance:
                return {"success": False, "msg": "余额不足", "order_id": order_id}
            
            self.balance -= total_payment
            if ts_code in self.positions:
                # 加仓，成本价加权平均
                old_shares = self.positions[ts_code]["shares"]
                old_cost = self.positions[ts_code]["cost_price"]
                new_cost = (old_shares * old_cost + quantity * price) / (old_shares + quantity)
                self.positions[ts_code] = {
                    "shares": old_shares + quantity,
                    "cost_price": new_cost
                }
            else:
                self.positions[ts_code] = {
                    "shares": quantity,
                    "cost_price": price
                }
        
        elif order_type == "sell":
            if ts_code not in self.positions or self.positions[ts_code]["shares"] < quantity:
                return {"success": False, "msg": "持仓不足", "order_id": order_id}
            
            total_income = price * quantity
            commission = max(total_income * 0.0003, 5)  # 佣金万3，对齐前端和回测配置
            stamp_tax = total_income * 0.001
            net_income = total_income - commission - stamp_tax
            self.balance += net_income
            
            self.positions[ts_code]["shares"] -= quantity
            if self.positions[ts_code]["shares"] == 0:
                del self.positions[ts_code]
        
        order = {
            "order_id": order_id,
            "ts_code": ts_code,
            "price": price,
            "quantity": quantity,
            "order_type": order_type,
            "status": "filled",
            "filled_quantity": quantity,
            "created_at": datetime.now().strftime("%Y%m%d %H:%M:%S"),
            "success": True,
            "msg": "模拟成交成功"
        }
        self.orders[order_id] = order
        
        print(f"✅ 模拟下单成功：订单ID{order_id}，{order_type} {ts_code} {quantity}股，价格{price:.2f}元")
        return order
    
    def cancel_order(self, order_id: str) -> bool:
        if not self.connected:
            raise Exception("网关未连接")
        
        if order_id in self.orders and self.orders[order_id]["status"] == "pending":
            self.orders[order_id]["status"] = "cancelled"
            return True
        return False
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        if not self.connected:
            raise Exception("网关未连接")
        
        return self.orders.get(order_id)
    
    def get_trade_history(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        if not self.connected:
            raise Exception("网关未连接")
        
        # 模拟返回所有订单
        return list(self.orders.values())
    
    def get_realtime_quote(self, ts_code: str) -> Dict:
        if not self.connected:
            raise Exception("网关未连接")
        
        # 模拟返回行情，这里简化处理，实际应该接入真实行情源
        return {
            "ts_code": ts_code,
            "name": "模拟股票",
            "price": 10.0,
            "high": 10.5,
            "low": 9.8,
            "volume": 1000000,
            "amount": 10000000,
            "pct_chg": 2.5,
            "update_time": datetime.now().strftime("%Y%m%d %H:%M:%S")
        }

# 扩展其他券商对接示例：
# class FutuGateway(BaseTradeGateway):
#     """富途牛牛网关"""
#     def connect(self):
#         # 实现富途连接逻辑
#         pass
# 
# class TigerGateway(BaseTradeGateway):
#     """老虎证券网关"""
#     pass
# 
# class SnowballGateway(BaseTradeGateway):
#     """雪球量化网关"""
#     pass

class TradeGatewayFactory:
    """交易网关工厂
    
    根据网关类型字符串创建对应的网关实例，
    当前仅支持 simulated，可扩展 futu/tiger/snowball 等。
    """
    
    @staticmethod
    def create_gateway(gateway_type: str, config: Dict) -> BaseTradeGateway:
        """创建交易网关实例"""
        gateway_map = {
            "simulated": SimulatedGateway,
            # 扩展其他券商："futu": FutuGateway, "tiger": TigerGateway, etc.
        }
        
        if gateway_type not in gateway_map:
            raise ValueError(f"不支持的网关类型：{gateway_type}，支持的类型：{list(gateway_map.keys())}")
        
        return gateway_map[gateway_type](config)

class TradingService:
    """交易服务上层封装
    
    提供更便捷的交易接口，封装底层网关细节：
    - start/stop: 生命周期管理
    - buy/sell: 简化的买卖接口
    - auto_trade_by_signal: 信号驱动的自动调仓（先卖后买）
    """
    
    def __init__(self, gateway_type: str = "simulated", gateway_config: Dict = None):
        self.gateway = TradeGatewayFactory.create_gateway(gateway_type, gateway_config or {})
        self.connected = False
    
    def start(self) -> bool:
        """启动交易服务"""
        if self.connected:
            return True
        
        try:
            self.connected = self.gateway.connect()
            return self.connected
        except Exception as e:
            print(f"❌ 启动交易服务失败：{e}")
            return False
    
    def stop(self) -> bool:
        """停止交易服务"""
        if not self.connected:
            return True
        
        try:
            self.gateway.disconnect()
            self.connected = False
            return True
        except Exception as e:
            print(f"❌ 停止交易服务失败：{e}")
            return False
    
    def buy(self, ts_code: str, price: float, quantity: int, order_type: str = "limit") -> Dict:
        """买入股票"""
        if not self.connected:
            return {"success": False, "msg": "交易服务未连接"}
        
        try:
            return self.gateway.place_order(ts_code, price, quantity, "buy")
        except Exception as e:
            print(f"❌ 买入失败：{e}")
            return {"success": False, "msg": str(e)}
    
    def sell(self, ts_code: str, price: float, quantity: int, order_type: str = "limit") -> Dict:
        """卖出股票"""
        if not self.connected:
            return {"success": False, "msg": "交易服务未连接"}
        
        try:
            return self.gateway.place_order(ts_code, price, quantity, "sell")
        except Exception as e:
            print(f"❌ 卖出失败：{e}")
            return {"success": False, "msg": str(e)}
    
    def auto_trade_by_signal(self, signals: List[Dict], max_position: float = 0.7, max_single_position: float = 0.2) -> List[Dict]:
        """根据信号自动调仓
        
        策略：先卖出不在新信号中的旧持仓，再买入新信号标的。
        - 卖出价 = 实时价 × 0.995（略低保证成交）
        - 买入价 = 实时价 × 1.005（略高保证成交）
        - 单票最大仓位不超过 max_single_position
        - 总仓位不超过 max_position
        
        Args:
            signals: 选股信号列表，每个信号需包含 ts_code
            max_position: 最大总仓位比例，默认0.7（70%）
            max_single_position: 单票最大仓位比例，默认0.2（20%）
        
        Returns:
            List[Dict]: 交易结果列表
        """
        if not self.connected:
            return []
        
        results = []
        account_info = self.gateway.get_account_info()
        total_asset = account_info["total_asset"]
        available_balance = account_info["available_balance"]
        current_positions = {pos["ts_code"]: pos for pos in self.gateway.get_positions()}
        
        # 先卖出不在信号中的持仓
        for ts_code in current_positions:
            if ts_code not in [s["ts_code"] for s in signals]:
                pos = current_positions[ts_code]
                # 获取最新价格
                quote = self.gateway.get_realtime_quote(ts_code)
                sell_price = quote["price"] * 0.995  # 市价略低保证成交
                result = self.sell(ts_code, sell_price, pos["shares"], "market")
                results.append(result)
                if result["success"]:
                    available_balance += result.get("filled_quantity", 0) * sell_price * 0.997  # 扣除手续费
        
        # 再买入新信号
        max_per_stock = total_asset * max_single_position
        for signal in signals[:int(max_position / max_single_position)]:  # 最多买N只
            ts_code = signal["ts_code"]
            if ts_code in current_positions:
                continue  # 已经持仓的跳过
            
            # 计算可买数量
            quote = self.gateway.get_realtime_quote(ts_code)
            buy_price = quote["price"] * 1.005  # 市价略高保证成交
            max_buy_shares = int(min(available_balance, max_per_stock) / buy_price / 100) * 100
            
            if max_buy_shares >= 100:
                result = self.buy(ts_code, buy_price, max_buy_shares, "market")
                results.append(result)
                if result["success"]:
                    available_balance -= result.get("filled_quantity", 0) * buy_price * 1.003  # 扣除手续费
        
        print(f"✅ 自动交易执行完成，共{len(results)}笔交易")
        return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="实盘交易工具")
    parser.add_argument("--action", required=True, 
                        choices=["test", "buy", "sell", "auto", "info", "positions"], 
                        help="操作类型")
    parser.add_argument("--gateway", default="simulated", help="网关类型，默认simulated(模拟)")
    parser.add_argument("--ts-code", help="股票代码")
    parser.add_argument("--price", type=float, help="价格")
    parser.add_argument("--shares", type=int, help="数量")
    parser.add_argument("--initial-balance", type=float, default=1000000, help="模拟账户初始资金，默认100万")
    
    args = parser.parse_args()
    
    gateway_config = {"initial_balance": args.initial_balance}
    service = TradingService(args.gateway, gateway_config)
    
    if not service.start():
        print("❌ 交易服务启动失败")
        sys.exit(1)
    
    try:
        if args.action == "test":
            print("✅ 交易网关连接测试成功")
            info = service.gateway.get_account_info()
            print(f"账户总资产：{info['total_asset']:.2f}元，可用余额：{info['available_balance']:.2f}元")
        
        elif args.action == "info":
            info = service.gateway.get_account_info()
            print("="*50)
            print("📊 账户信息")
            print("="*50)
            print(f"总资产：{info['total_asset']:.2f}元")
            print(f"可用余额：{info['available_balance']:.2f}元")
            print(f"持仓市值：{info['market_value']:.2f}元")
            print(f"浮动盈亏：{info['pnl']:.2f}元")
            print("="*50)
        
        elif args.action == "positions":
            positions = service.gateway.get_positions()
            if not positions:
                print("当前无持仓")
            else:
                print("="*50)
                print("📋 持仓列表")
                print("="*50)
                for pos in positions:
                    print(f"{pos['ts_code']}：{pos['shares']}股，成本价{pos['cost_price']:.2f}元，市值{pos['market_value']:.2f}元，浮盈{pos['pnl']:.2f}元")
                print("="*50)
        
        elif args.action == "buy":
            if not all([args.ts_code, args.price, args.shares]):
                print("参数错误：需要 --ts-code、--price、--shares")
                sys.exit(1)
            result = service.buy(args.ts_code, args.price, args.shares)
            print(result["msg"])
        
        elif args.action == "sell":
            if not all([args.ts_code, args.price, args.shares]):
                print("参数错误：需要 --ts-code、--price、--shares")
                sys.exit(1)
            result = service.sell(args.ts_code, args.price, args.shares)
            print(result["msg"])
        
        elif args.action == "auto":
            # 示例信号，实际使用时从信号生成器获取
            signals = [
                {"ts_code": "000001.SZ", "name": "平安银行", "strategy": "半路追涨"},
                {"ts_code": "600000.SH", "name": "浦发银行", "strategy": "首板打板"},
            ]
            results = service.auto_trade_by_signal(signals)
            for res in results:
                print(res["msg"])
    
    finally:
        service.stop()
