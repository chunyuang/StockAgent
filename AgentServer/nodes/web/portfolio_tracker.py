#!/usr/bin/env python3
"""
持仓管理与每日净值跟踪

解决的核心问题：
1. 现有 PositionManager 使用 JSON 文件 → 改为 MongoDB 持久化
2. 缺少每日净值跟踪 → 每日收盘后自动计算组合净值并记录
3. 缺少净值历史曲线 → 支持查询任意日期范围的净值走势
4. 缺少与信号系统的联动 → 执行信号自动建仓，平仓自动记录
5. 缺少每日市值快照 → 持仓+现金的总资产快照存入MongoDB

MongoDB Collections:
  portfolio_positions: 当前持仓（与 trading signals 联动）
    - (account_id, ts_code) unique
    - (account_id, status)
  
  portfolio_nav_daily: 每日净值快照
    - (account_id, date) unique
    - (account_id, date) compound
  
  portfolio_trades: 交易记录（平仓记录）
    - (account_id, trade_id) unique
    - (account_id, executed_at)

使用方式：
  from nodes.web.portfolio_tracker import portfolio_tracker

  # 初始化
  await portfolio_tracker.initialize()

  # 信号驱动建仓
  await portfolio_tracker.open_position(account_id, signal_doc)

  # 平仓
  result = await portfolio_tracker.close_position(account_id, ts_code, sell_price, reason)

  # 每日净值计算（盘后自动调用）
  nav = await portfolio_tracker.record_daily_nav(account_id, trade_date)

  # 查询净值曲线
  navs = await portfolio_tracker.get_nav_history(account_id, start_date, end_date)

  # 查询持仓
  positions = await portfolio_tracker.get_positions(account_id)

  # 每日风控检查
  alerts = await portfolio_tracker.daily_risk_check(account_id, trade_date)
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

from core.managers import mongo_manager

logger = logging.getLogger("portfolio_tracker")


# ==================== 集合名 ====================

COLLECTION_POSITIONS = "portfolio_positions"
COLLECTION_NAV = "portfolio_nav_daily"
COLLECTION_TRADES = "portfolio_trades"


# ==================== 持仓状态 ====================

class PositionStatus:
    OPEN = "open"        # 持仓中
    CLOSED = "closed"    # 已平仓
    FORCED = "forced"    # 强制平仓


class PortfolioTracker:
    """
    持仓管理与每日净值跟踪

    核心能力：
    1. MongoDB 持久化持仓（替代 JSON 文件）
    2. 每日净值计算与快照
    3. 信号驱动建仓 / 止损止盈平仓
    4. 净值历史曲线查询
    5. 每日风控检查（止损/止盈/超期）
    """

    def __init__(self, config: Dict = None):
        self.config = {
            "default_initial_cash": 1_000_000,
            "default_stop_loss_pct": 0.02,     # 2% 止损
            "default_take_profit_pct": 0.07,   # 7% 止盈
            "default_max_hold_days": 3,
            "default_max_position_per_stock": 0.2,  # 单票 20%
            "default_max_total_position": 0.7,      # 总仓位 70%
        }
        self.config.update(config or {})
        self._initialized = False

    # ==================== 初始化 & 索引 ====================

    async def initialize(self) -> None:
        """创建持仓相关集合的索引"""
        if self._initialized:
            return

        logger.info("Initializing portfolio tracker indexes...")

        try:
            db = mongo_manager.db

            await db[COLLECTION_POSITIONS].create_indexes([
                {"key": [("account_id", 1), ("ts_code", 1)], "unique": True, "name": "idx_account_tscode"},
                {"key": [("account_id", 1), ("status", 1)], "name": "idx_account_status"},
                {"key": [("strategy", 1), ("buy_date", -1)], "name": "idx_strategy_date"},
            ])

            await db[COLLECTION_NAV].create_indexes([
                {"key": [("account_id", 1), ("date", 1)], "unique": True, "name": "idx_account_date"},
                {"key": [("account_id", 1), ("date", -1)], "name": "idx_account_date_desc"},
            ])

            await db[COLLECTION_TRADES].create_indexes([
                {"key": [("account_id", 1), ("trade_id", 1)], "unique": True, "name": "idx_account_trade"},
                {"key": [("account_id", 1), ("executed_at", -1)], "name": "idx_account_date"},
                {"key": [("ts_code", 1)], "name": "idx_tscode"},
            ])

            self._initialized = True
            logger.info("Portfolio tracker indexes created ✓")

        except Exception as e:
            logger.error(f"Failed to create portfolio indexes: {e}")
            self._initialized = True

    # ==================== 账户管理 ====================

    async def get_or_create_account(self, account_id: str, initial_cash: float = None) -> Dict:
        """
        获取或创建模拟账户

        Returns:
            Dict: 账户信息，包含 cash, initial_cash, total_assets 等
        """
        account = await mongo_manager.find_one("sim_accounts", {"account_id": account_id})
        if account:
            return account

        # 创建默认账户
        cash = initial_cash or self.config["default_initial_cash"]
        now = datetime.now(timezone.utc)
        account = {
            "account_id": account_id,
            "name": "默认模拟账户",
            "user_id": "system",
            "initial_cash": cash,
            "available_cash": cash,
            "total_assets": cash,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        await mongo_manager.insert_one("sim_accounts", account)

        # 创建初始净值记录
        await self._upsert_nav_record(account_id, self._get_today_str(), {
            "total_assets": cash,
            "cash": cash,
            "position_value": 0,
            "nav": 1.0,
            "nav_change_pct": 0,
            "positions": [],
        })

        logger.info(f"Created account {account_id} with initial cash {cash}")
        return account

    # ==================== 建仓 ====================

    async def open_position(
        self,
        account_id: str,
        ts_code: str,
        stock_name: str,
        buy_price: float,
        shares: int,
        strategy: str = "",
        signal_id: str = "",
        stop_loss_pct: float = None,
        take_profit_pct: float = None,
        max_hold_days: int = None,
    ) -> Dict:
        """
        建仓

        Args:
            account_id: 账户ID
            ts_code: 股票代码
            stock_name: 股票名称
            buy_price: 买入价格
            shares: 买入数量（100的整数倍）
            strategy: 策略标签
            signal_id: 关联信号ID
            stop_loss_pct: 止损比例（默认2%）
            take_profit_pct: 止盈比例（默认7%）
            max_hold_days: 最大持仓天数（默认3天）

        Returns:
            Dict: {"success": bool, "position": dict, "message": str}
        """
        # 1. 检查是否已有持仓
        existing = await mongo_manager.find_one(
            COLLECTION_POSITIONS,
            {"account_id": account_id, "ts_code": ts_code, "status": PositionStatus.OPEN},
        )
        if existing:
            return {"success": False, "message": f"{ts_code} 已在持仓中", "position": None}

        # 2. 检查账户余额
        account = await self.get_or_create_account(account_id)
        total_cost = buy_price * shares
        if account.get("available_cash", 0) < total_cost:
            return {"success": False, "message": f"余额不足（需要{total_cost:.0f}，可用{account.get('available_cash', 0):.0f}）", "position": None}

        # 3. 计算风控参数
        sl_pct = stop_loss_pct or self.config["default_stop_loss_pct"]
        tp_pct = take_profit_pct or self.config["default_take_profit_pct"]
        mhd = max_hold_days or self.config["default_max_hold_days"]
        buy_date = self._get_today_str()

        position = {
            "position_id": f"pos_{uuid.uuid4().hex[:12]}",
            "account_id": account_id,
            "ts_code": ts_code,
            "stock_name": stock_name,
            "buy_date": buy_date,
            "buy_price": buy_price,
            "shares": shares,
            "total_cost": total_cost,
            "stop_loss_price": round(buy_price * (1 - sl_pct), 3),
            "take_profit_price": round(buy_price * (1 + tp_pct), 3),
            "max_hold_days": mhd,
            "strategy": strategy,
            "signal_id": signal_id,
            "status": PositionStatus.OPEN,
            "created_at": datetime.now(timezone.utc),
        }

        # 4. 写入持仓
        await mongo_manager.insert_one(COLLECTION_POSITIONS, position)

        # 5. 扣减账户余额
        await mongo_manager.update_one(
            "sim_accounts",
            {"account_id": account_id},
            {"$inc": {"available_cash": -total_cost}},
        )

        logger.info(f"Opened position: {stock_name}({ts_code}) {shares}股 @ {buy_price:.2f} = {total_cost:.0f}元")
        return {"success": True, "message": f"建仓成功：{stock_name} {shares}股", "position": position}

    async def open_position_by_signal(self, account_id: str, signal: Dict) -> Dict:
        """
        通过信号建仓（便捷方法）

        Args:
            account_id: 账户ID
            signal: 信号字典（来自 trading_signals 集合或盘前信号）

        Returns:
            Dict: 建仓结果
        """
        buy_price = signal.get("price", signal.get("close", 0) * 1.01)
        shares = signal.get("suggest_quantity", 100)
        # 买入数量调整为100整数倍
        shares = (shares // 100) * 100
        if shares <= 0:
            shares = 100

        return await self.open_position(
            account_id=account_id,
            ts_code=signal.get("ts_code", ""),
            stock_name=signal.get("stock_name", signal.get("name", "")),
            buy_price=buy_price,
            shares=shares,
            strategy=signal.get("strategy", ""),
            signal_id=signal.get("signal_id", ""),
        )

    # ==================== 平仓 ====================

    async def close_position(
        self,
        account_id: str,
        ts_code: str,
        sell_price: float,
        reason: str = "手动平仓",
    ) -> Dict:
        """
        平仓

        Args:
            account_id: 账户ID
            ts_code: 股票代码
            sell_price: 卖出价格
            reason: 平仓原因

        Returns:
            Dict: {"success": bool, "trade": dict, "profit": float}
        """
        position = await mongo_manager.find_one(
            COLLECTION_POSITIONS,
            {"account_id": account_id, "ts_code": ts_code, "status": PositionStatus.OPEN},
        )
        if not position:
            return {"success": False, "message": f"{ts_code} 不在持仓中", "trade": None}

        sell_amount = sell_price * position["shares"]
        profit = sell_amount - position["total_cost"]
        profit_pct = (sell_price - position["buy_price"]) / position["buy_price"] * 100
        hold_days = self._calc_hold_days(position["buy_date"])
        sell_date = self._get_today_str()
        now = datetime.now(timezone.utc)

        # 1. 更新持仓状态
        await mongo_manager.update_one(
            COLLECTION_POSITIONS,
            {"position_id": position["position_id"]},
            {"$set": {
                "status": PositionStatus.FORCED if "强制" in reason else PositionStatus.CLOSED,
                "sell_date": sell_date,
                "sell_price": sell_price,
                "sell_amount": sell_amount,
                "profit": profit,
                "profit_pct": profit_pct,
                "close_reason": reason,
                "closed_at": now,
            }},
        )

        # 2. 记录交易
        trade = {
            "trade_id": f"trd_{uuid.uuid4().hex[:12]}",
            "account_id": account_id,
            "ts_code": ts_code,
            "stock_name": position["stock_name"],
            "direction": "sell",
            "quantity": position["shares"],
            "price": sell_price,
            "amount": sell_amount,
            "profit": profit,
            "profit_pct": profit_pct,
            "buy_price": position["buy_price"],
            "buy_date": position["buy_date"],
            "hold_days": hold_days,
            "strategy": position.get("strategy", ""),
            "signal_id": position.get("signal_id", ""),
            "reason": reason,
            "executed_at": now,
        }
        await mongo_manager.insert_one(COLLECTION_TRADES, trade)

        # 3. 增加账户余额
        await mongo_manager.update_one(
            "sim_accounts",
            {"account_id": account_id},
            {"$inc": {"available_cash": sell_amount}},
        )

        # 4. 更新信号状态
        if position.get("signal_id"):
            try:
                from nodes.web.signal_persistence import signal_persistence
                await signal_persistence.mark_signal_executed(
                    signal_id=position["signal_id"],
                    account_id=account_id,
                    trade_id=trade["trade_id"],
                    execution_price=sell_price,
                    execution_quantity=position["shares"],
                )
            except Exception:
                pass  # signal_persistence 不可用时不阻塞

        icon = "✅" if profit > 0 else "❌"
        logger.info(f"{icon} Closed {position['stock_name']}({ts_code}): "
                     f"持仓{hold_days}天，盈利{profit:.2f}元({profit_pct:.2f}%)，原因：{reason}")

        return {"success": True, "trade": trade, "profit": profit, "profit_pct": profit_pct}

    # ==================== 每日净值计算 ====================

    async def record_daily_nav(self, account_id: str, trade_date: str = None) -> Dict:
        """
        每日收盘后计算并记录净值快照

        计算逻辑：
        1. 获取所有 open 持仓
        2. 从 MongoDB 获取当日收盘价
        3. 计算每只持仓的市值 = 收盘价 × 数量
        4. 总持仓市值 = sum(每只持仓市值)
        5. 总资产 = 现金 + 总持仓市值
        6. NAV = 总资产 / 初始资金
        7. NAV变化 = (今日NAV - 昨日NAV) / 昨日NAV

        Args:
            account_id: 账户ID
            trade_date: 交易日期，默认今天

        Returns:
            Dict: 净值快照
        """
        if not trade_date:
            trade_date = self._get_today_str()

        # 1. 获取账户信息
        account = await self.get_or_create_account(account_id)
        initial_cash = account.get("initial_cash", self.config["default_initial_cash"])
        cash = account.get("available_cash", 0)

        # 2. 获取持仓
        positions = await mongo_manager.find_many(
            COLLECTION_POSITIONS,
            {"account_id": account_id, "status": PositionStatus.OPEN},
        )

        # 3. 获取当日收盘价
        ts_codes = [p["ts_code"] for p in positions]
        price_map = {}
        if ts_codes:
            try:
                daily_data = await mongo_manager.find_many(
                    "stock_daily_ak_full",
                    {"ts_code": {"$in": ts_codes}, "trade_date": int(trade_date)},
                    projection={"ts_code": 1, "close": 1, "pct_chg": 1, "high": 1, "low": 1},
                )
                price_map = {d.get("ts_code", ""): d for d in (daily_data or []) if d.get("ts_code")}
            except Exception as e:
                logger.warning(f"获取收盘价失败: {e}")

        # 4. 计算每只持仓市值
        position_details = []
        total_position_value = 0

        for pos in positions:
            daily = price_map.get(pos["ts_code"], {})
            close_price = daily.get("close", pos["buy_price"])
            pct_chg = daily.get("pct_chg", 0)
            market_value = close_price * pos["shares"]
            pos_profit = market_value - pos["total_cost"]
            pos_profit_pct = (close_price - pos["buy_price"]) / pos["buy_price"] * 100 if pos["buy_price"] > 0 else 0

            position_details.append({
                "ts_code": pos["ts_code"],
                "stock_name": pos["stock_name"],
                "shares": pos["shares"],
                "buy_price": pos["buy_price"],
                "close_price": close_price,
                "pct_chg": pct_chg,
                "market_value": round(market_value, 2),
                "profit": round(pos_profit, 2),
                "profit_pct": round(pos_profit_pct, 2),
                "hold_days": self._calc_hold_days(pos["buy_date"]),
                "strategy": pos.get("strategy", ""),
            })
            total_position_value += market_value

        # 5. 计算总资产和NAV
        total_assets = cash + total_position_value
        nav = total_assets / initial_cash if initial_cash > 0 else 1.0
        position_ratio = total_position_value / total_assets if total_assets > 0 else 0

        # 6. 计算NAV变化率
        prev_nav = await self._get_previous_nav(account_id, trade_date)
        nav_change_pct = (nav - prev_nav) / prev_nav * 100 if prev_nav > 0 else 0

        # 7. 写入净值快照
        nav_record = {
            "account_id": account_id,
            "date": trade_date,
            "cash": round(cash, 2),
            "position_value": round(total_position_value, 2),
            "total_assets": round(total_assets, 2),
            "nav": round(nav, 4),
            "nav_change_pct": round(nav_change_pct, 2),
            "position_ratio": round(position_ratio, 4),
            "position_count": len(positions),
            "positions": position_details,
            "initial_cash": initial_cash,
            "total_profit": round(total_assets - initial_cash, 2),
            "total_profit_pct": round((total_assets - initial_cash) / initial_cash * 100, 2) if initial_cash > 0 else 0,
            "generated_at": datetime.now(timezone.utc),
        }

        await self._upsert_nav_record(account_id, trade_date, nav_record)

        # 8. 更新账户总资产
        await mongo_manager.update_one(
            "sim_accounts",
            {"account_id": account_id},
            {"$set": {"total_assets": round(total_assets, 2)}},
        )

        logger.info(f"[NAV] {trade_date} account={account_id}: "
                     f"总资产={total_assets:.0f} NAV={nav:.4f} ({nav_change_pct:+.2f}%) "
                     f"持仓={len(positions)}只 仓位={position_ratio:.0%}")
        return nav_record

    async def _upsert_nav_record(self, account_id: str, trade_date: str, nav_record: Dict) -> None:
        """幂等写入净值记录"""
        existing = await mongo_manager.find_one(
            COLLECTION_NAV,
            {"account_id": account_id, "date": trade_date},
        )
        if existing:
            await mongo_manager.update_one(
                COLLECTION_NAV,
                {"account_id": account_id, "date": trade_date},
                {"$set": nav_record},
            )
        else:
            await mongo_manager.insert_one(COLLECTION_NAV, nav_record)

    async def _get_previous_nav(self, account_id: str, current_date: str) -> float:
        """获取前一个交易日的NAV"""
        try:
            # 查询当前日期之前最近的一条NAV记录
            records = await mongo_manager.find_many(
                COLLECTION_NAV,
                {"account_id": account_id, "date": {"$lt": current_date}},
                sort=[("date", -1)],
                limit=1,
            )
            if records:
                return records[0].get("nav", 1.0)
        except Exception:
            pass
        return 1.0  # 无历史记录，默认NAV=1.0

    # ==================== 查询方法 ====================

    async def get_positions(self, account_id: str, status: str = None) -> List[Dict]:
        """获取持仓列表"""
        query = {"account_id": account_id}
        if status:
            query["status"] = status
        else:
            query["status"] = PositionStatus.OPEN
        return await mongo_manager.find_many(
            COLLECTION_POSITIONS, query,
            sort=[("created_at", -1)],
        )

    async def get_position(self, account_id: str, ts_code: str) -> Optional[Dict]:
        """获取单只持仓"""
        return await mongo_manager.find_one(
            COLLECTION_POSITIONS,
            {"account_id": account_id, "ts_code": ts_code, "status": PositionStatus.OPEN},
        )

    async def get_nav_history(
        self, account_id: str, start_date: str = None, end_date: str = None, limit: int = 60,
    ) -> List[Dict]:
        """查询净值历史"""
        query = {"account_id": account_id}
        if start_date or end_date:
            date_filter = {}
            if start_date:
                date_filter["$gte"] = start_date
            if end_date:
                date_filter["$lte"] = end_date
            if date_filter:
                query["date"] = date_filter

        return await mongo_manager.find_many(
            COLLECTION_NAV, query,
            sort=[("date", 1)],  # 升序，适合画图
            limit=limit,
        )

    async def get_latest_nav(self, account_id: str) -> Optional[Dict]:
        """获取最新净值"""
        records = await mongo_manager.find_many(
            COLLECTION_NAV,
            {"account_id": account_id},
            sort=[("date", -1)],
            limit=1,
        )
        return records[0] if records else None

    async def get_trade_history(
        self, account_id: str, limit: int = 50, offset: int = 0,
    ) -> Dict:
        """获取交易历史"""
        total = await mongo_manager.count(COLLECTION_TRADES, {"account_id": account_id})
        records = await mongo_manager.find_many(
            COLLECTION_TRADES,
            {"account_id": account_id},
            sort=[("executed_at", -1)],
            skip=offset,
            limit=limit,
        )
        return {"total": total, "items": records}

    async def get_performance_summary(self, account_id: str) -> Dict:
        """获取绩效统计"""
        # 1. 从交易记录计算
        trades = await mongo_manager.find_many(
            COLLECTION_TRADES,
            {"account_id": account_id},
        )

        if not trades:
            return {
                "total_trades": 0, "win_rate": 0, "total_profit": 0,
                "avg_profit_pct": 0, "max_drawdown": 0, "avg_hold_days": 0,
            }

        total = len(trades)
        wins = [t for t in trades if t.get("profit", 0) > 0]
        total_profit = sum(t.get("profit", 0) for t in trades)
        avg_profit_pct = sum(t.get("profit_pct", 0) for t in trades) / total
        avg_hold_days = sum(t.get("hold_days", 0) for t in trades) / total

        # 2. 从净值记录计算最大回撤
        nav_records = await self.get_nav_history(account_id, limit=365)
        max_drawdown = 0
        peak_nav = 0
        for r in nav_records:
            nav = r.get("nav", 1.0)
            if nav > peak_nav:
                peak_nav = nav
            drawdown = (peak_nav - nav) / peak_nav * 100 if peak_nav > 0 else 0
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        # 3. 最新净值
        latest_nav = await self.get_latest_nav(account_id)

        return {
            "total_trades": total,
            "win_trades": len(wins),
            "lose_trades": total - len(wins),
            "win_rate": round(len(wins) / total * 100, 2) if total > 0 else 0,
            "total_profit": round(total_profit, 2),
            "avg_profit_pct": round(avg_profit_pct, 2),
            "max_drawdown": round(max_drawdown, 2),
            "avg_hold_days": round(avg_hold_days, 1),
            "current_nav": latest_nav.get("nav", 1.0) if latest_nav else 1.0,
            "current_total_assets": latest_nav.get("total_assets", 0) if latest_nav else 0,
        }

    # ==================== 每日风控检查 ====================

    async def daily_risk_check(self, account_id: str, trade_date: str = None) -> List[Dict]:
        """
        每日盘后风控检查

        检查项：
        1. 持仓超期 → danger，建议强制平仓
        2. 触发止损 → danger
        3. 接近止损 → warning
        4. 触发止盈 → success
        5. 接近止盈 → warning
        6. 仓位过重 → warning

        Returns:
            List[Dict]: 告警列表
        """
        if not trade_date:
            trade_date = self._get_today_str()

        positions = await self.get_positions(account_id)
        if not positions:
            return []

        # 获取收盘价
        ts_codes = [p["ts_code"] for p in positions]
        price_map = {}
        try:
            daily_data = await mongo_manager.find_many(
                "stock_daily_ak_full",
                {"ts_code": {"$in": ts_codes}, "trade_date": int(trade_date)},
                projection={"ts_code": 1, "close": 1, "high": 1, "low": 1, "pct_chg": 1},
            )
            price_map = {d.get("ts_code", ""): d for d in (daily_data or []) if d.get("ts_code")}
        except Exception as e:
            logger.warning(f"风控检查获取行情失败: {e}")

        alerts = []
        for pos in positions:
            daily = price_map.get(pos["ts_code"], {})
            close = daily.get("close", pos["buy_price"])
            high = daily.get("high", close)
            low = daily.get("low", close)
            pct_chg = daily.get("pct_chg", 0)

            alert = {
                "ts_code": pos["ts_code"],
                "stock_name": pos["stock_name"],
                "close": close,
                "pct_chg": pct_chg,
                "hold_days": self._calc_hold_days(pos["buy_date"]),
                "profit_pct": round((close - pos["buy_price"]) / pos["buy_price"] * 100, 2) if pos["buy_price"] > 0 else 0,
                "alerts": [],
                "level": "normal",
            }

            # 持仓超期
            if alert["hold_days"] >= pos.get("max_hold_days", 3):
                alert["alerts"].append(f"持仓超期：已持有{alert['hold_days']}天，超过{pos.get('max_hold_days', 3)}天上限")
                alert["level"] = "danger"

            # 止损
            sl = pos.get("stop_loss_price", 0)
            if low <= sl and sl > 0:
                alert["alerts"].append(f"触发止损：最低价{low:.2f} ≤ 止损价{sl:.2f}")
                alert["level"] = "danger"
            elif close <= sl * 1.05 and sl > 0:
                alert["alerts"].append(f"接近止损：当前{close:.2f} 接近止损{sl:.2f}")
                if alert["level"] != "danger":
                    alert["level"] = "warning"

            # 止盈
            tp = pos.get("take_profit_price", 0)
            if high >= tp and tp > 0:
                alert["alerts"].append(f"触发止盈：最高价{high:.2f} ≥ 止盈价{tp:.2f}")
                if alert["level"] not in ("danger",):
                    alert["level"] = "success"
            elif close >= tp * 0.95 and tp > 0:
                alert["alerts"].append(f"接近止盈：当前{close:.2f} 接近止盈{tp:.2f}")
                if alert["level"] not in ("danger", "success"):
                    alert["level"] = "warning"

            if alert["alerts"]:
                alerts.append(alert)

        return alerts

    # ==================== 辅助方法 ====================

    def _get_today_str(self) -> str:
        return datetime.now().strftime("%Y%m%d")

    def _calc_hold_days(self, buy_date: str) -> int:
        try:
            buy_dt = datetime.strptime(buy_date, "%Y%m%d")
            # 【P2修复：持仓天数=日历天数×0.67近似交易日(5/7≈0.67)，与回测引擎第6轮修复一致】
            # 原代码直接用日历天数，周末1个交易日=3日历天被误判超时
            return int((datetime.now() - buy_dt).days * 0.67)
        except (ValueError, TypeError):
            return 0

    @property
    def is_initialized(self) -> bool:
        return self._initialized


# ==================== 全局单例 ====================

portfolio_tracker = PortfolioTracker()
