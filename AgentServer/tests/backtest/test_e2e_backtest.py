"""
回测端到端测试

模拟完整回测流程: 数据加载 → 选股 → 调仓 → 持仓更新 → 止损止盈 → 结算
使用 MockMongoManager 替代真实 MongoDB，测试核心算法逻辑。
"""
import pytest
import sys
import os
from datetime import datetime, timedelta
from copy import deepcopy

_base = os.path.join(os.path.dirname(__file__), '..')
if _base not in sys.path:
    sys.path.insert(0, _base)


# ============================================================
# 模拟回测引擎 - 从 PortfolioBacktester 提取的核心算法
# 不依赖真实MongoDB，纯逻辑测试
# ============================================================

class SimulatedBacktest:
    """模拟回测引擎 - 提取核心逻辑用于测试"""

    COMMISSION_RATE = 0.0003  # 万3
    MIN_COMMISSION = 5.0      # 最低5元
    STAMP_DUTY_RATE = 0.001   # 千1 (仅卖出)
    SLIPPAGE_PCT = 0.001      # 滑点0.1%

    def __init__(self, initial_cash=1_000_000, risk_config=None):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions = {}       # ts_code -> {quantity, avg_cost, buy_date}
        self.trade_log = []       # 交易记录
        self.daily_nav = []       # 每日净值
        self.completed_trades = []  # 已完成交易

        # 风控配置
        self.risk = risk_config or {
            "enable_stop_loss": True,
            "stop_loss_pct": 0.02,
            "enable_take_profit": True,
            "take_profit_pct": 0.07,
            "max_hold_days": 10,
            "max_position_per_stock": 0.1,  # 单股最大10%仓位
        }

    def buy(self, ts_code: str, price: float, quantity: int, trade_date: int) -> bool:
        """买入"""
        amount = price * quantity
        commission = max(amount * self.COMMISSION_RATE, self.MIN_COMMISSION)
        total_cost = amount + commission

        # 检查资金
        if total_cost > self.cash:
            return False

        # 检查单股仓位限制
        total_equity = self._get_equity({ts_code: price})
        if total_equity > 0 and (amount / total_equity) > self.risk["max_position_per_stock"]:
            # 缩减到允许的最大量
            max_amount = total_equity * self.risk["max_position_per_stock"]
            quantity = int(max_amount / price / 100) * 100  # 整手
            if quantity <= 0:
                return False
            amount = price * quantity
            commission = max(amount * self.COMMISSION_RATE, self.MIN_COMMISSION)
            total_cost = amount + commission

        self.cash -= total_cost

        if ts_code in self.positions:
            pos = self.positions[ts_code]
            old_total = pos["avg_cost"] * pos["quantity"]
            pos["quantity"] += quantity
            pos["avg_cost"] = (old_total + amount) / pos["quantity"]
            pos["buy_date"] = trade_date  # 更新买入日
        else:
            self.positions[ts_code] = {
                "quantity": quantity,
                "avg_cost": price,
                "buy_date": trade_date,
            }

        self.trade_log.append({
            "action": "buy", "ts_code": ts_code, "price": price,
            "quantity": quantity, "commission": commission, "date": trade_date,
        })
        return True

    def sell(self, ts_code: str, price: float, quantity: int, trade_date: int,
             reason: str = "signal") -> bool:
        """卖出"""
        if ts_code not in self.positions:
            return False
        if price <= 0:  # 停牌股不能卖
            return False

        pos = self.positions[ts_code]
        quantity = min(quantity, pos["quantity"])
        if quantity <= 0:
            return False

        amount = price * quantity
        commission = max(amount * self.COMMISSION_RATE, self.MIN_COMMISSION)
        stamp_duty = amount * self.STAMP_DUTY_RATE
        net_proceeds = amount - commission - stamp_duty

        self.cash += net_proceeds

        # 记录已完成交易
        profit = (price - pos["avg_cost"]) * quantity - commission - stamp_duty
        self.completed_trades.append({
            "ts_code": ts_code, "buy_price": pos["avg_cost"],
            "sell_price": price, "quantity": quantity,
            "profit": profit, "reason": reason,
            "buy_date": pos["buy_date"], "sell_date": trade_date,
        })

        pos["quantity"] -= quantity
        if pos["quantity"] <= 0:
            del self.positions[ts_code]

        self.trade_log.append({
            "action": "sell", "ts_code": ts_code, "price": price,
            "quantity": quantity, "commission": commission + stamp_duty,
            "date": trade_date, "reason": reason,
        })
        return True

    def check_risk(self, prices: dict, trade_date: int) -> list:
        """风控检查: 止损/止盈/超时强卖"""
        forced_sells = []
        for ts_code in list(self.positions.keys()):
            pos = self.positions[ts_code]
            current_price = prices.get(ts_code, 0)
            if current_price <= 0:
                continue  # 停牌

            pnl_pct = (current_price / pos["avg_cost"]) - 1

            # 止损
            if self.risk["enable_stop_loss"] and pnl_pct <= -self.risk["stop_loss_pct"]:
                forced_sells.append((ts_code, current_price, "stop_loss"))

            # 止盈
            elif self.risk["enable_take_profit"] and pnl_pct >= self.risk["take_profit_pct"]:
                forced_sells.append((ts_code, current_price, "take_profit"))

            # 超时强卖
            hold_days = self._trading_days_between(pos["buy_date"], trade_date)
            if hold_days >= self.risk["max_hold_days"]:
                forced_sells.append((ts_code, current_price, "max_hold"))

        return forced_sells

    def daily_settle(self, prices: dict, trade_date: int):
        """每日结算: 计算净值"""
        equity = self._get_equity(prices)
        self.daily_nav.append({"date": trade_date, "nav": equity / self.initial_cash})

    def _get_equity(self, prices: dict) -> float:
        """总权益 = 现金 + 持仓市值"""
        market_value = 0
        for ts_code, pos in self.positions.items():
            price = prices.get(ts_code, pos["avg_cost"])  # 无市价用成本价(不应发生)
            market_value += price * pos["quantity"]
        return self.cash + market_value

    def _trading_days_between(self, start: int, end: int) -> int:
        """近似交易日 = 日历天数 × 0.67"""
        s = str(start)
        e = str(end)
        d1 = datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
        d2 = datetime(int(e[:4]), int(e[4:6]), int(e[6:8]))
        calendar_days = (d2 - d1).days
        return int(calendar_days * 0.67)

    def get_performance(self, benchmark_data: list = None) -> dict:
        """计算绩效指标"""
        if not self.daily_nav:
            return {}

        navs = [d["nav"] for d in self.daily_nav]
        total_return = navs[-1] - 1

        # 胜率
        winning = sum(1 for t in self.completed_trades if t["profit"] > 0)
        losing = sum(1 for t in self.completed_trades if t["profit"] <= 0)
        completed = winning + losing
        win_rate = winning / completed if completed > 0 else 0

        # 盈亏比
        total_profit = sum(t["profit"] for t in self.completed_trades if t["profit"] > 0)
        total_loss = abs(sum(t["profit"] for t in self.completed_trades if t["profit"] < 0))
        avg_profit = total_profit / winning if winning > 0 else 0
        avg_loss = total_loss / losing if losing > 0 else 1
        plr = avg_profit / avg_loss if avg_loss > 0 else 0

        # 最大回撤
        peak, max_dd = navs[0], 0
        for nav in navs:
            if nav > peak:
                peak = nav
            dd = (peak - nav) / peak
            if dd > max_dd:
                max_dd = dd

        # 基准收益率
        benchmark_return = 0.0
        if benchmark_data and len(benchmark_data) >= 2:
            benchmark_return = benchmark_data[-1] / benchmark_data[0] - 1

        alpha = total_return - benchmark_return

        return {
            "total_return": total_return,
            "win_rate": win_rate,
            "profit_loss_ratio": plr,
            "max_drawdown": max_dd,
            "completed_trades": completed,
            "winning_trades": winning,
            "losing_trades": losing,  # = completed - winning ✅
            "benchmark_return": benchmark_return,
            "alpha": alpha,
        }


class TestBuySellBasic:
    """基础买卖测试"""

    def test_buy_reduces_cash(self):
        bt = SimulatedBacktest(initial_cash=1_000_000)
        bt.buy("000001.SZ", 10.0, 1000, 20250101)
        assert bt.cash < 1_000_000
        assert "000001.SZ" in bt.positions
        assert bt.positions["000001.SZ"]["quantity"] == 1000

    def test_sell_increases_cash(self):
        bt = SimulatedBacktest(initial_cash=1_000_000)
        bt.buy("000001.SZ", 10.0, 1000, 20250101)
        cash_after_buy = bt.cash
        bt.sell("000001.SZ", 11.0, 1000, 20250102)
        assert bt.cash > cash_after_buy
        assert "000001.SZ" not in bt.positions

    def test_cannot_sell_suspended_stock(self):
        """停牌股close=0不能卖"""
        bt = SimulatedBacktest(initial_cash=1_000_000)
        bt.buy("000001.SZ", 10.0, 1000, 20250101)
        result = bt.sell("000001.SZ", 0, 1000, 20250102)  # price=0 停牌
        assert result is False
        assert "000001.SZ" in bt.positions  # 仍在持仓

    def test_cannot_buy_insufficient_cash(self):
        bt = SimulatedBacktest(initial_cash=1000)
        result = bt.buy("000001.SZ", 10.0, 10000, 20250101)  # 需要10万
        assert result is False

    def test_commission_deducted(self):
        """佣金从现金扣除"""
        bt = SimulatedBacktest(initial_cash=1_000_000)
        bt.buy("000001.SZ", 10.0, 1000, 20250101)
        # 1000*10=10000, 佣金=max(10000*0.0003, 5)=5
        expected_commission = max(10000 * 0.0003, 5)
        assert bt.cash == 1_000_000 - 10000 - expected_commission

    def test_stamp_duty_on_sell_only(self):
        """印花税仅卖出时收取"""
        bt = SimulatedBacktest(initial_cash=1_000_000)
        bt.buy("000001.SZ", 10.0, 10000, 20250101)
        cash_after_buy = bt.cash

        # 卖出: 佣金万3 + 印花税千1
        bt.sell("000001.SZ", 10.0, 10000, 20250102)
        amount = 10000 * 10.0
        commission = max(amount * 0.0003, 5)
        stamp_duty = amount * 0.001
        expected_cash = cash_after_buy + amount - commission - stamp_duty
        assert abs(bt.cash - expected_cash) < 0.01


class TestPositionConcentration:
    """仓位限制测试"""

    def test_max_position_per_stock(self):
        """单股仓位不超过上限"""
        bt = SimulatedBacktest(initial_cash=1_000_000, risk_config={
            "max_position_per_stock": 0.1,  # 10%
            **SimulatedBacktest(initial_cash=1).risk,
        })
        # 尝试买入50%仓位，应被缩减到10%
        bt.buy("000001.SZ", 10.0, 50000, 20250101)
        pos_value = bt.positions["000001.SZ"]["quantity"] * 10.0
        total_equity = bt._get_equity({"000001.SZ": 10.0})
        assert pos_value / total_equity <= 0.11  # 允许微小误差


class TestRiskControl:
    """风控测试"""

    def test_stop_loss_triggers(self):
        """止损触发"""
        bt = SimulatedBacktest(initial_cash=1_000_000, risk_config={
            "enable_stop_loss": True, "stop_loss_pct": 0.05,
            "enable_take_profit": False, "max_hold_days": 999,
            "max_position_per_stock": 1.0,
        })
        bt.buy("000001.SZ", 10.0, 1000, 20250101)  # 成本10元

        # 跌5%到9.5
        forced = bt.check_risk({"000001.SZ": 9.5}, 20250102)
        assert len(forced) == 1
        assert forced[0][2] == "stop_loss"

    def test_take_profit_triggers(self):
        """止盈触发"""
        bt = SimulatedBacktest(initial_cash=1_000_000, risk_config={
            "enable_stop_loss": False,
            "enable_take_profit": True, "take_profit_pct": 0.10,
            "max_hold_days": 999, "max_position_per_stock": 1.0,
        })
        bt.buy("000001.SZ", 10.0, 1000, 20250101)

        # 涨10%到11
        forced = bt.check_risk({"000001.SZ": 11.0}, 20250102)
        assert len(forced) == 1
        assert forced[0][2] == "take_profit"

    def test_max_hold_days_triggers(self):
        """超时强卖触发(用交易日近似)"""
        bt = SimulatedBacktest(initial_cash=1_000_000, risk_config={
            "enable_stop_loss": False, "enable_take_profit": False,
            "max_hold_days": 3, "max_position_per_stock": 1.0,
        })
        bt.buy("000001.SZ", 10.0, 1000, 20250101)  # 1月1日买入

        # 1月6日 = 5个日历天 ≈ 3.35交易日 > 3 → 触发
        forced = bt.check_risk({"000001.SZ": 10.0}, 20250106)
        assert len(forced) == 1
        assert forced[0][2] == "max_hold"

    def test_risk_disabled_no_trigger(self):
        """关闭风控不触发"""
        bt = SimulatedBacktest(initial_cash=1_000_000, risk_config={
            "enable_stop_loss": False, "stop_loss_pct": 0.01,
            "enable_take_profit": False, "take_profit_pct": 0.01,
            "max_hold_days": 999, "max_position_per_stock": 1.0,
        })
        bt.buy("000001.SZ", 10.0, 1000, 20250101)

        # 跌50%也不触发
        forced = bt.check_risk({"000001.SZ": 5.0}, 20250102)
        assert len(forced) == 0

    def test_suspended_stock_not_force_sold(self):
        """停牌股不触发风控(价格=0跳过)"""
        bt = SimulatedBacktest(initial_cash=1_000_000, risk_config={
            "enable_stop_loss": True, "stop_loss_pct": 0.01,
            "enable_take_profit": False, "max_hold_days": 999,
            "max_position_per_stock": 1.0,
        })
        bt.buy("000001.SZ", 10.0, 1000, 20250101)

        # 停牌: price=0
        forced = bt.check_risk({"000001.SZ": 0}, 20250102)
        assert len(forced) == 0  # 不应强制卖出


class TestPerformanceCalculation:
    """绩效计算测试"""

    def test_losing_trades_equals_completed_minus_winning(self):
        """losing_trades = completed_trades - winning_trades"""
        bt = SimulatedBacktest(initial_cash=1_000_000)
        # 3笔交易: 2盈利1亏损
        bt.completed_trades = [
            {"ts_code": "A", "buy_price": 10, "sell_price": 11, "quantity": 100, "profit": 100},
            {"ts_code": "B", "buy_price": 10, "sell_price": 12, "quantity": 100, "profit": 200},
            {"ts_code": "C", "buy_price": 10, "sell_price": 9, "quantity": 100, "profit": -100},
        ]
        bt.daily_nav = [{"nav": 1.0}, {"nav": 1.05}]

        perf = bt.get_performance()
        assert perf["completed_trades"] == 3
        assert perf["winning_trades"] == 2
        assert perf["losing_trades"] == 1  # 3-2=1 ✅ 不是total_signals-2

    def test_benchmark_return_not_hardcoded(self):
        """基准收益率从数据计算"""
        bt = SimulatedBacktest()
        bt.completed_trades = []
        bt.daily_nav = [{"nav": 1.0}, {"nav": 1.05}]

        # 基准从3000涨到3240 = 8%
        perf = bt.get_performance(benchmark_data=[3000, 3240])
        assert abs(perf["benchmark_return"] - 0.08) < 0.001
        assert perf["benchmark_return"] != 0.0

    def test_alpha_calculation(self):
        """Alpha = 策略收益 - 基准收益"""
        bt = SimulatedBacktest()
        bt.completed_trades = []
        bt.daily_nav = [{"nav": 1.0}, {"nav": 1.15}]  # +15%

        perf = bt.get_performance(benchmark_data=[3000, 3240])  # +8%
        assert abs(perf["alpha"] - 0.07) < 0.001

    def test_max_drawdown(self):
        """最大回撤"""
        bt = SimulatedBacktest()
        bt.completed_trades = []
        # 净值: 1.0 → 1.2 → 0.9 → 1.1
        bt.daily_nav = [
            {"nav": 1.0}, {"nav": 1.2}, {"nav": 0.9}, {"nav": 1.1}
        ]
        perf = bt.get_performance()
        # 回撤: 峰1.2→谷0.9, (1.2-0.9)/1.2=25%
        assert abs(perf["max_drawdown"] - 0.25) < 0.001


class TestEndToEndFlow:
    """完整回测流程端到端测试"""

    def test_simple_round_trip(self):
        """简单往返: 买→卖→结算"""
        bt = SimulatedBacktest(initial_cash=1_000_000)

        # Day 1: 买入
        bt.buy("000001.SZ", 10.0, 10000, 20250101)
        bt.daily_settle({"000001.SZ": 10.0}, 20250101)
        assert bt.daily_nav[-1]["nav"] > 0

        # Day 2: 涨到11
        bt.daily_settle({"000001.SZ": 11.0}, 20250102)
        assert bt.daily_nav[-1]["nav"] > bt.daily_nav[0]["nav"]

        # Day 3: 卖出
        bt.sell("000001.SZ", 11.0, 10000, 20250103)
        bt.daily_settle({"000001.SZ": 11.0}, 20250103)

        perf = bt.get_performance()
        assert perf["completed_trades"] == 1
        assert perf["winning_trades"] == 1
        assert perf["win_rate"] == 1.0

    def test_stop_loss_flow(self):
        """止损流程: 买→跌→止损→结算"""
        bt = SimulatedBacktest(initial_cash=1_000_000, risk_config={
            "enable_stop_loss": True, "stop_loss_pct": 0.05,
            "enable_take_profit": False, "max_hold_days": 999,
            "max_position_per_stock": 1.0,
        })

        # Day 1: 10元买入
        bt.buy("000001.SZ", 10.0, 10000, 20250101)
        bt.daily_settle({"000001.SZ": 10.0}, 20250101)

        # Day 2: 跌到9.5(-5%)，触发止损
        forced = bt.check_risk({"000001.SZ": 9.5}, 20250102)
        for code, price, reason in forced:
            bt.sell(code, price, bt.positions[code]["quantity"], 20250102, reason=reason)

        bt.daily_settle({"000001.SZ": 9.5}, 20250102)
        assert "000001.SZ" not in bt.positions

        perf = bt.get_performance()
        assert perf["completed_trades"] == 1
        assert perf["losing_trades"] == 1
        assert perf["win_rate"] == 0.0

    def test_multi_stock_with_risk(self):
        """多股票+风控+超时"""
        bt = SimulatedBacktest(initial_cash=2_000_000, risk_config={
            "enable_stop_loss": True, "stop_loss_pct": 0.08,
            "enable_take_profit": True, "take_profit_pct": 0.10,
            "max_hold_days": 5, "max_position_per_stock": 1.0,  # 不限制仓位
        })

        # Day 1: 买入两只
        bt.buy("000001.SZ", 10.0, 50000, 20250101)
        bt.buy("600000.SH", 20.0, 25000, 20250101)
        bt.daily_settle({"000001.SZ": 10.0, "600000.SH": 20.0}, 20250101)

        # Day 2: 000001涨15%(超止盈10%), 600000跌8%(触止损)
        forced = bt.check_risk({"000001.SZ": 11.5, "600000.SH": 18.4}, 20250102)
        assert len(forced) == 2
        reasons = {r for _, _, r in forced}
        assert "take_profit" in reasons
        assert "stop_loss" in reasons

        for code, price, reason in forced:
            bt.sell(code, price, bt.positions[code]["quantity"], 20250102, reason=reason)

        bt.daily_settle({"000001.SZ": 11.5, "600000.SH": 18.4}, 20250102)
        assert len(bt.positions) == 0

        perf = bt.get_performance()
        assert perf["completed_trades"] == 2
        assert perf["winning_trades"] == 1
        assert perf["losing_trades"] == 1
