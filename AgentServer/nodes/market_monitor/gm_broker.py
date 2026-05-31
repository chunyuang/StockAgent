#!/usr/bin/env python3
"""
GmBroker — 掘金量化交易网关

掘金(gm)是事件驱动框架, 不像普通REST API可以随意调用。
需要写策略→gm.run()→框架驱动回调。

实现方式:
1. GmBrokerStrategy: 掘金策略(后台运行)
2. GmBroker: 适配器(与MarketScanner对接)
3. 通过 asyncio.Queue 通信: Scanner → GmBroker → gm下单 → 回调 → GmBroker → Scanner

使用:
    broker = GmBroker(token="你的token", strategy_id="你的策略ID")
    await broker.start()  # 启动gm后台进程
    ok, msg, order = broker.place_order(...)  # 下单
    await broker.stop()

仿真模式:
    需要在掘金终端或官网创建"仿真"策略
    不需要真实券商账户, 仿真环境自动给虚拟资金
"""
import asyncio
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from threading import Thread

logger = logging.getLogger("broker.gm")


class GmOrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELED = "canceled"


@dataclass
class GmOrder:
    """掘金委托"""
    order_id: str
    ts_code: str
    stock_name: str
    side: str  # buy/sell
    quantity: int
    price: float
    filled_qty: int = 0
    filled_price: float = 0.0
    status: GmOrderStatus = GmOrderStatus.PENDING
    reason: str = ""
    strategy: str = ""
    create_time: str = ""
    gm_cl_ord_id: str = ""  # 掘金委托ID


class GmBroker:
    """
    掘金量化交易网关

    通过子进程运行掘金策略, 与主进程通过文件/队列通信。
    支持仿真和实盘模式。
    """

    def __init__(self, token: str, strategy_id: str = "",
                 mode: int = 1,  # 1=live(仿真/实盘), 2=backtest
                 serv_addr: str = "",
                 account_id: str = ""):
        self.token = token
        self.strategy_id = strategy_id
        self.mode = mode
        self.serv_addr = serv_addr
        self.account_id = account_id

        # 状态
        self._is_running = False
        self._process = None
        self._orders: Dict[str, GmOrder] = {}
        self._positions: List[Dict] = []
        self._account_info: Dict = {}
        self._connected = False

        # 通信(子进程写文件, 主进程读)
        self._state_file = "/tmp/gm_broker_state.json"
        self._order_file = "/tmp/gm_broker_orders.json"

    @property
    def is_running(self):
        return self._is_running

    def get_positions(self) -> List[Dict]:
        """获取持仓"""
        self._load_state()
        return self._positions

    def get_account(self) -> Dict:
        """获取账户"""
        self._load_state()
        return self._account_info

    def get_orders(self) -> List[Dict]:
        """获取委托"""
        self._load_state()
        return [self._order_to_dict(o) for o in self._orders.values()]

    # ==================== 生命周期 ====================

    async def start(self):
        """启动掘金策略子进程"""
        if self._is_running:
            return {"success": True, "message": "已在运行中"}

        # 写策略文件
        strategy_script = self._generate_strategy_script()
        script_path = "/tmp/gm_broker_strategy.py"
        with open(script_path, 'w') as f:
            f.write(strategy_script)

        # 启动子进程
        cmd = f"cd /root/.openclaw/workspace/StockAgent && source venv/bin/activate && python3 {script_path}"
        self._process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._is_running = True
        logger.info(f"[GM] 掘金策略进程启动, PID={self._process.pid}")

        # 等待连接
        for _ in range(30):
            await asyncio.sleep(1)
            self._load_state()
            if self._connected:
                logger.info("[GM] 掘金连接成功")
                return {"success": True, "message": "掘金连接成功"}

        logger.warning("[GM] 掘金连接超时(30秒)")
        return {"success": False, "message": "掘金连接超时"}

    async def stop(self):
        """停止掘金策略"""
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
        self._is_running = False
        self._connected = False
        logger.info("[GM] 掘金策略已停止")
        return {"success": True, "message": "已停止"}

    # ==================== 下单 ====================

    def place_order(self, ts_code: str, stock_name: str,
                    side: str, quantity: int,
                    price: float = 0.0,
                    order_type: str = "market",
                    strategy: str = "",
                    reason: str = "") -> Tuple[bool, str, GmOrder]:
        """
        下单

        通过写命令文件, 掘金子进程读取并执行
        """
        order_id = f"GM{datetime.now().strftime('%H%M%S')}{len(self._orders):04d}"

        order = GmOrder(
            order_id=order_id,
            ts_code=ts_code,
            stock_name=stock_name,
            side=side,
            quantity=quantity,
            price=price,
            strategy=strategy,
            reason=reason,
            create_time=datetime.now().strftime("%H:%M:%S"),
        )

        # 写命令文件(掘金子进程读取)
        cmd = {
            "action": "place_order",
            "order_id": order_id,
            "ts_code": ts_code,
            "side": side,
            "quantity": quantity,
            "price": price,
            "order_type": order_type,
            "strategy": strategy,
            "timestamp": time.time(),
        }

        cmd_file = "/tmp/gm_broker_cmd.json"
        import json
        with open(cmd_file, 'w') as f:
            json.dump(cmd, f)

        self._orders[order_id] = order
        logger.info(f"[GM] 下单: {side} {ts_code} {quantity}股@{price} ({strategy})")

        # 异步撮合(掘金回调更新状态)
        return True, f"已提交: {side} {ts_code} {quantity}股", order

    # ==================== 内部方法 ====================

    def _load_state(self):
        """从状态文件读取掘金状态"""
        import json
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file) as f:
                    state = json.load(f)
                self._connected = state.get("connected", False)
                self._positions = state.get("positions", [])
                self._account_info = state.get("account", {})
                # 更新委托状态
                for oid, odata in state.get("orders", {}).items():
                    if oid in self._orders:
                        o = self._orders[oid]
                        o.filled_qty = odata.get("filled_qty", 0)
                        o.filled_price = odata.get("filled_price", 0)
                        o.status = GmOrderStatus(odata.get("status", "pending"))
                        o.reason = odata.get("reason", "")
        except Exception as _e:
            logger.debug(f"order operation failed: {_e}")

    def _generate_strategy_script(self) -> str:
        """生成掘金策略脚本(子进程运行)"""
        return f'''#!/usr/bin/env python3
"""
掘金策略 — 由GmBroker自动生成
功能: 读取命令文件执行下单, 写状态文件回报结果
"""
import json
import os
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [GM] %(message)s")
logger = logging.getLogger("gm_broker")

STATE_FILE = "/tmp/gm_broker_state.json"
CMD_FILE = "/tmp/gm_broker_cmd.json"

# 全局状态
state = {{"connected": False, "positions": [], "account": {{}}, "orders": {{}}}}

def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False)

def init(context):
    """掘金初始化回调"""
    logger.info("掘金策略初始化")
    state["connected"] = True
    save_state()

    # 订阅全市场1分钟行情
    # symbols = get_symbols(sec_type1=1)  # 1=股票
    # subscribe(symbols=symbols[:100], frequency="60s", count=1)

def on_bar(context, bars):
    """行情回调"""
    # 读取命令文件
    if os.path.exists(CMD_FILE):
        try:
            with open(CMD_FILE) as f:
                cmd = json.load(f)
            if cmd.get("action") == "place_order":
                execute_order(context, cmd)
            # 执行后删除命令文件
            os.remove(CMD_FILE)
        except Exception as e:
            logger.error(f"处理命令失败: {{e}}")

    # 更新持仓和账户
    update_state(context)

def on_order_filled(context, order):
    """成交回调"""
    logger.info(f"成交: {{order.symbol}} {{order.side}} {{order.filled_volume}}@{{order.filled_vwap}}")
    oid = order.cl_ord_id if hasattr(order, "cl_ord_id") else ""
    if oid in state.get("orders", {{}}):
        state["orders"][oid]["status"] = "filled"
        state["orders"][oid]["filled_qty"] = order.filled_volume
        state["orders"][oid]["filled_price"] = order.filled_vwap
    save_state()

def on_order_rejected(context, order):
    """委托被拒"""
    logger.warning(f"被拒: {{order.symbol}} {{order.reject_reason}}")
    save_state()

def on_backtest_finished(context, indicator):
    """回测完成"""
    logger.info(f"回测完成: {{indicator}}")

def execute_order(context, cmd):
    """执行下单命令"""
    ts_code = cmd.get("ts_code", "")
    side = cmd.get("side", "buy")
    quantity = cmd.get("quantity", 0)
    price = cmd.get("price", 0)
    order_type = cmd.get("order_type", "market")
    order_id = cmd.get("order_id", "")

    # 转换ts_code格式: 600519.SH → SHSE.600519
    gm_symbol = convert_symbol(ts_code)

    from gm.api import OrderSide_Buy, OrderSide_Sell, OrderType_Market, OrderType_Limit, PositionEffect_Open, PositionEffect_Close

    gm_side = OrderSide_Buy if side == "buy" else OrderSide_Sell
    gm_type = OrderType_Market if order_type == "market" else OrderType_Limit
    gm_effect = PositionEffect_Open if side == "buy" else PositionEffect_Close

    try:
        from gm.api import order_volume
        result = order_volume(
            symbol=gm_symbol,
            volume=quantity,
            side=gm_side,
            order_type=gm_type,
            position_effect=gm_effect,
            price=price if order_type == "limit" else 0,
        )
        logger.info(f"下单成功: {{gm_symbol}} {{side}} {{quantity}} result={{{{result}}}}")

        # 记录
        state.setdefault("orders", {{}})[order_id] = {{
            "status": "pending",
            "filled_qty": 0,
            "filled_price": 0,
        }}
    except Exception as e:
        logger.error(f"下单失败: {{e}}")
        state.setdefault("orders", {{}})[order_id] = {{
            "status": "rejected",
            "reason": str(e),
        }}

def update_state(context):
    """更新持仓和账户"""
    try:
        from gm.api import get_position, context as gm_ctx
        pos = get_position()
        if pos is not None:
            positions = []
            if hasattr(pos, "__iter__"):
                for p in pos:
                    positions.append({{
                        "ts_code": convert_symbol_back(p.symbol) if hasattr(p, "symbol") else "",
                        "stock_name": "",
                        "total_qty": p.volume if hasattr(p, "volume") else 0,
                        "available_qty": p.available if hasattr(p, "available") else 0,
                        "avg_cost": p.vwap if hasattr(p, "vwap") else 0,
                        "current_price": p.price if hasattr(p, "price") else 0,
                    }})
            state["positions"] = positions

        # 账户
        acct = context.account() if hasattr(context, "account") else None
        if acct:
            state["account"] = {{
                "total_assets": acct.nav if hasattr(acct, "nav") else 0,
                "available_cash": acct.available if hasattr(acct, "available") else 0,
                "market_value": acct.market_value if hasattr(acct, "market_value") else 0,
            }}
    except Exception as e:
        logger.debug(f"更新状态: {{e}}")

    save_state()

def convert_symbol(ts_code: str) -> str:
    """600519.SH → SHSE.600519"""
    if "." not in ts_code:
        return ts_code
    code, suffix = ts_code.split(".")
    exchange_map = {{"SH": "SHSE", "SZ": "SZSE", "BJ": "BJSE"}}
    exchange = exchange_map.get(suffix, suffix)
    return f"{{exchange}}.{{code}}"

def convert_symbol_back(gm_symbol: str) -> str:
    """SHSE.600519 → 600519.SH"""
    if "." not in gm_symbol:
        return gm_symbol
    exchange, code = gm_symbol.split(".")
    exchange_map = {{"SHSE": "SH", "SZSE": "SZ", "BJSE": "BJ"}}
    suffix = exchange_map.get(exchange, exchange)
    return f"{{code}}.{{suffix}}"

if __name__ == "__main__":
    from gm.api import run, set_token

    set_token("{self.token}")

    logger.info(f"启动掘金策略: token={self.token[:8]}... mode={self.mode}")

    run(
        strategy_id="{self.strategy_id}",
        filename=__file__,
        mode={self.mode},
        serv_addr="{self.serv_addr}",
    )
'''

    @staticmethod
    def _order_to_dict(o: GmOrder) -> Dict:
        return {
            "order_id": o.order_id, "ts_code": o.ts_code,
            "stock_name": o.stock_name, "side": o.side,
            "quantity": o.quantity, "price": o.price,
            "filled_qty": o.filled_qty, "filled_price": o.filled_price,
            "status": o.status.value, "reason": o.reason,
            "strategy": o.strategy, "create_time": o.create_time,
        }
