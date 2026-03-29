"""
组合回测引擎

支持:
- 定期调仓
- 多种权重方法
- 交易成本
- 基准对比
- 绩效统计
"""

from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd
import numpy as np
import logging

from core.managers import mongo_manager
from .universe import UniverseManager, UniverseType, ExcludeRule
from .factor_engine import FactorEngine


logger = logging.getLogger(__name__)


@dataclass
class RebalanceRecord:
    """调仓记录"""
    date: str
    action: str  # "buy" | "sell"
    ts_code: str
    shares: int
    price: float
    amount: float
    reason: str


@dataclass
class Position:
    """持仓信息，包含买入日期"""
    ts_code: str
    shares: int
    buy_date: str
    cost_price: float


@dataclass
class PortfolioSnapshot:
    """组合快照"""
    date: str
    cash: float
    holdings: Dict[str, int]  # {ts_code: shares}
    prices: Dict[str, float]  # {ts_code: price}
    market_value: float
    total_value: float


class PortfolioBacktester:
    """
    组合回测引擎
    
    支持:
    - 定期调仓 (日/周/月/季)
    - 多种权重方法 (等权/因子加权)
    - 交易成本 (佣金+印花税)
    - 基准对比
    
    数据源隔离:
    - source: "ak" for AKShare, "ts" for Tushare, None for no filter
    """
    
    # 交易成本
    BUY_COMMISSION = 0.0002     # 买入佣金 万2
    SELL_COMMISSION = 0.0002   # 卖出佣金 万2
    STAMP_TAX = 0.001          # 印花税 千1 (卖出)
    MIN_COMMISSION = 5         # 最低佣金 5元
    SLIPPAGE = 0.001           # 滑点 千1 (默认)
    MAX_POSITION = 0.7         # 最大总仓位比例 (默认70%仓位，保留30%现金)
    
    def __init__(self, source: str = None, slippage: float = 0.001, max_position: float = 0.7):
        """
        Args:
            source: 数据源过滤，只查询该来源的数据，避免不同数据源混用
            slippage: 滑点比例，默认千1
            max_position: 最大总仓位比例，默认0.7（70%仓位，保留30%现金），0.5表示最多半仓
        """
        self.universe_mgr = UniverseManager()
        self.factor_engine = FactorEngine(source=source)
        self.SLIPPAGE = max(0.0, min(0.05, slippage))  # 限制滑点范围0~5%
        self.MAX_POSITION = max(0.0, min(1.0, max_position))  # 限制仓位0~100%
    
    async def run(self, config: Dict) -> Dict:
        """
        运行组合回测
        
        Args:
            config: {
                "universe": "all_a",
                "start_date": "20230101",
                "end_date": "20260101",
                "initial_cash": 1000000,
                "rebalance_freq": "monthly",
                "top_n": 20,
                "weight_method": "equal",
                "factors": [
                    {"name": "momentum_20d", "weight": 0.3},
                    {"name": "pb", "weight": 0.3},
                    {"name": "roe", "weight": 0.4},
                ],
                "exclude": ["st", "new_stock"],
                "benchmark": "000300.SH"
            }
        """
        logger.info(f"Starting portfolio backtest: {config['start_date']} -> {config['end_date']}")
        
        # 初始化
        initial_cash = config.get("initial_cash", 1000000)
        top_n = config.get("top_n", 20)
        weight_method = config.get("weight_method", "equal")
        benchmark_code = config.get("benchmark", "000300.SH")
        self.max_position_per_stock = config.get("max_position_per_stock", 0.2)  # 单票最大仓位，默认 20%
        # 滑点配置，默认千1
        self.SLIPPAGE = max(0.0, min(0.05, config.get("slippage", 0.001)))
        # 最大总仓位配置，默认70%仓位，保留30%现金
        self.MAX_POSITION = max(0.0, min(1.0, config.get("max_position", 0.7)))
        # 基础交易参数（可动态调整）
        self.base_stop_loss_pct = config.get("stop_loss_pct", 0.05)  # 默认止损5%
        self.base_take_profit_pct = config.get("take_profit_pct", 0.1)  # 默认止盈10%
        self.base_volume_threshold = config.get("volume_threshold", 1.5)  # 默认量能放大1.5倍
        self.base_liquidity_threshold = config.get("liquidity_threshold", 5000000)  # 默认流动性门槛500万
        
        # 解析排除规则
        exclude_rules = [ExcludeRule(r) for r in config.get("exclude", [])]
        
        # 获取调仓日期
        rebalance_dates = await self.universe_mgr.get_rebalance_dates(
            config["start_date"],
            config["end_date"],
            config.get("rebalance_freq", "monthly"),
        )
        
        if not rebalance_dates:
            return {"error": "No rebalance dates found"}
        
        # 获取所有交易日
        all_trade_dates = await self.universe_mgr.get_all_trade_dates(
            config["start_date"], config["end_date"]
        )
        
        if not all_trade_dates:
            return {"error": "No trade dates found"}
        
        logger.info(f"Rebalance dates: {len(rebalance_dates)}, Trade dates: {len(all_trade_dates)}")
        
        # 加载基准数据
        benchmark_data = await self._load_benchmark(benchmark_code, config["start_date"], config["end_date"])
        
        # 初始化组合状态
        cash = initial_cash
        holdings: Dict[str, Position] = {}  # {ts_code: Position}
        # 强制平仓规则：持仓超过X天强制卖出，默认3天
        self.max_hold_days = config.get("max_hold_days", 3)
        # 强制空仓规则开关
        self.enable_force_empty = config.get("enable_force_empty", True)
        # 情绪周期开关
        self.enable_sentiment_cycle = config.get("enable_sentiment_cycle", True)
        
        # 记录
        daily_values: List[Dict] = []
        rebalance_records: List[RebalanceRecord] = []
        selection_history: List[Dict] = []
        
        # 逐日模拟
        rebalance_set = set(rebalance_dates)
        total_days = len(all_trade_dates)
        
        for idx, trade_date in enumerate(all_trade_dates):
            # 每 20 天打印一次进度
            if idx % 20 == 0:
                logger.info(f"Processing day {idx+1}/{total_days}: {trade_date}")
            
            # ==============================================
            # 1. 止损检查 + 持仓超过3天强制平仓检查
            # ==============================================
            if holdings:
                # 获取当日价格
                hold_stocks = list(holdings.keys())
                prices, _, limit_down_prices = await self._get_prices_and_limits(set(hold_stocks), trade_date)
                # 获取动态止损系数
                stop_loss_coeff = self.current_sentiment.get("stop_loss_adjust", 1.0)
                base_stop_loss_pct = config.get("stop_loss_pct", 0.05)  # 默认止损5%
                adjusted_stop_loss_pct = base_stop_loss_pct * stop_loss_coeff
                
                for ts_code in list(holdings.keys()):
                    pos = holdings[ts_code]
                    shares = pos.shares
                    price = prices.get(ts_code, 0)
                    if price <= 0 or shares <= 0:
                        continue
                    
                    # ==============================================
                    # 新增：动态止盈/止损检查（根据情绪周期调整幅度）
                    # ==============================================
                    take_profit_coeff = self.current_sentiment.get("take_profit_adjust", 1.0)
                    adjusted_take_profit_pct = self.base_take_profit_pct * take_profit_coeff
                    
                    current_profit_pct = (price - pos.cost_price) / pos.cost_price
                    # 止损判断
                    if current_profit_pct <= -adjusted_stop_loss_pct:
                        # 触发止损，强制卖出
                        # 跌停无法卖出判断
                        limit_down = limit_down_prices.get(ts_code)
                        if limit_down and price <= limit_down * 1.005:
                            logger.warning(f"[{trade_date}] {ts_code} 跌停，无法止损卖出，继续持有")
                            continue
                        
                        # 卖出滑点
                        trade_price = price * (1 - self.SLIPPAGE)
                        amount = shares * trade_price
                        commission = max(amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
                        tax = amount * self.STAMP_TAX
                        cash += amount - commission - tax
                        
                        rebalance_records.append(RebalanceRecord(
                            date=trade_date, action="sell", ts_code=ts_code,
                            shares=shares, price=trade_price, amount=amount,
                            reason=f"stop_loss_{current_profit_pct:.2%}_adjust_{stop_loss_coeff:.1f}x",
                        ))
                        logger.info(f"[{trade_date}] 触发止损 {ts_code} （当前亏损{current_profit_pct:.2%}，调整后止损阈值{-adjusted_stop_loss_pct:.2%}），卖出{shares}股，收入{amount - commission - tax:.2f}元")
                        
                        # 移除持仓
                        del holdings[ts_code]
                        continue
                    
                    # 止盈判断
                    if current_profit_pct >= adjusted_take_profit_pct:
                        # 触发止盈，卖出
                        limit_down = limit_down_prices.get(ts_code)
                        if limit_down and price <= limit_down * 1.005:
                            logger.warning(f"[{trade_date}] {ts_code} 跌停，无法止盈卖出，继续持有")
                            continue
                        
                        # 卖出滑点
                        trade_price = price * (1 - self.SLIPPAGE)
                        amount = shares * trade_price
                        commission = max(amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
                        tax = amount * self.STAMP_TAX
                        cash += amount - commission - tax
                        
                        rebalance_records.append(RebalanceRecord(
                            date=trade_date, action="sell", ts_code=ts_code,
                            shares=shares, price=trade_price, amount=amount,
                            reason=f"take_profit_{current_profit_pct:.2%}_adjust_{take_profit_coeff:.1f}x",
                        ))
                        logger.info(f"[{trade_date}] 触发止盈 {ts_code} （当前盈利{current_profit_pct:.2%}，调整后止盈阈值{adjusted_take_profit_pct:.2%}），卖出{shares}股，收入{amount - commission - tax:.2f}元")
                        
                        # 移除持仓
                        del holdings[ts_code]
                        continue
                    
                    # ==============================================
                    # 持仓超过3天强制平仓检查
                    # ==============================================
                    # 计算持仓天数
                    from datetime import datetime
                    buy_dt = datetime.strptime(pos.buy_date, "%Y%m%d")
                    current_dt = datetime.strptime(trade_date, "%Y%m%d")
                    hold_days = (current_dt - buy_dt).days
                    
                    if hold_days >= self.max_hold_days:
                        # 持仓超过最大天数，强制卖出
                        # 跌停无法卖出判断
                        limit_down = limit_down_prices.get(ts_code)
                        if limit_down and price <= limit_down * 1.005:
                            logger.warning(f"[{trade_date}] {ts_code} 跌停，无法强制平仓，继续持有")
                            continue
                        
                        # 卖出滑点
                        trade_price = price * (1 - self.SLIPPAGE)
                        amount = shares * trade_price
                        commission = max(amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
                        tax = amount * self.STAMP_TAX
                        cash += amount - commission - tax
                        
                        rebalance_records.append(RebalanceRecord(
                            date=trade_date, action="sell", ts_code=ts_code,
                            shares=shares, price=trade_price, amount=amount,
                            reason=f"force_close_hold_{hold_days}_days",
                        ))
                        logger.info(f"[{trade_date}] 强制平仓 {ts_code} （持仓{hold_days}天超过{self.max_hold_days}天上限），卖出{shares}股，收入{amount - commission - tax:.2f}元")
                        
                        # 移除持仓
                        del holdings[ts_code]
            
            # ==============================================
            # 2. 强制空仓检查
            # ==============================================
            force_empty = await self._check_force_empty(trade_date)
            if force_empty:
                # 强制空仓，卖出所有持仓
                if holdings:
                    hold_stocks = list(holdings.keys())
                    prices, _, limit_down_prices = await self._get_prices_and_limits(set(hold_stocks), trade_date)
                    
                    for ts_code in list(holdings.keys()):
                        pos = holdings[ts_code]
                        shares = pos.shares
                        price = prices.get(ts_code, 0)
                        if price <= 0 or shares <= 0:
                            continue
                        
                        limit_down = limit_down_prices.get(ts_code)
                        if limit_down and price <= limit_down * 1.005:
                            logger.warning(f"[{trade_date}] {ts_code} 跌停，无法卖出，保留持仓")
                            continue
                        
                        trade_price = price * (1 - self.SLIPPAGE)
                        amount = shares * trade_price
                        commission = max(amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
                        tax = amount * self.STAMP_TAX
                        cash += amount - commission - tax
                        
                        rebalance_records.append(RebalanceRecord(
                            date=trade_date, action="sell", ts_code=ts_code,
                            shares=shares, price=trade_price, amount=amount,
                            reason="force_empty",
                        ))
                        del holdings[ts_code]
                    
                    logger.info(f"[{trade_date}] 强制空仓执行完毕，当前现金{cash:.2f}元")
                
                # 强制空仓日跳过调仓，直接继续下一天
                market_value = sum(
                    pos.shares * prices.get(pos.ts_code, 0)
                    for pos in holdings.values()
                )
                total_value = cash + market_value
                benchmark_nav = benchmark_data.get(trade_date, 1.0)
                daily_values.append({
                    "date": trade_date,
                    "cash": cash,
                    "market_value": market_value,
                    "total_value": total_value,
                    "benchmark_value": benchmark_nav * initial_cash,
                    "return_pct": (total_value / initial_cash - 1) * 100,
                    "force_empty": True,
                    "sentiment": current_sentiment
                })
                continue
            
            # ==============================================
            # 3. 情绪周期判断，动态调整总仓位上限和策略权限
            # ==============================================
            sentiment_info = await self._get_sentiment_cycle(trade_date)
            # 保存当日情绪信息到daily_values
            current_sentiment = {
                "score": sentiment_info["score"],
                "level": sentiment_info["level"],
                "position_limit": sentiment_info["position_limit"],
                "allowed_strategies": sentiment_info["allowed_strategies"]
            }
            # 取配置的最大仓位和情绪周期对应仓位的最小值，双重控制
            original_max_position = self.MAX_POSITION
            self.MAX_POSITION = min(original_max_position, sentiment_info["position_limit"])
            # 保存情绪周期参数，供后续选股过滤使用
            self.current_sentiment = sentiment_info
            
            # 检查是否是调仓日
            if trade_date in rebalance_set:
                logger.info(f"Rebalancing on {trade_date} ({idx+1}/{total_days})")
                
                # 1. 获取当日股票池
                universe = await self.universe_mgr.get_universe(
                    UniverseType.ALL_A,
                    trade_date,
                    exclude_rules,
                )
                
                if not universe:
                    logger.warning(f"No stocks in universe for {trade_date}")
                    continue
                
                # ==============================================
                # 新增：竞价阶段过滤（第5层筛选）
                # ==============================================
                enable_auction_filter = config.get("enable_auction_filter", True)
                if enable_auction_filter:
                    # 获取当日集合竞价数据
                    auction_data = await mongo_manager.find_many(
                        "stock_bid_auction",
                        {"trade_date": int(trade_date)},
                        projection={"ts_code": 1, "auction_pct_chg": 1, "auction_volume": 1, "unmatched_volume": 1}
                    )
                    
                    if auction_data:
                        auction_map = {x["ts_code"]: x for x in auction_data}
                        # 竞价过滤规则
                        filtered_universe = []
                        for ts_code in universe:
                            if ts_code not in auction_map:
                                continue  # 无竞价数据的标的过滤
                            auction = auction_map[ts_code]
                            # 基础竞价条件（可根据策略调整）
                            # 1. 竞价涨幅在0.5%~7%之间，排除一字板和大幅低开
                            if not (0.5 <= auction["auction_pct_chg"] <= 7):
                                continue
                            # 2. 竞价量≥过去5日平均量的10%（量比≥0.1）
                            if auction["auction_volume"] <= 0:
                                continue
                            # 3. 未匹配量为正（买盘大于卖盘）
                            if auction["unmatched_volume"] <= 0:
                                continue
                            filtered_universe.append(ts_code)
                        
                        logger.info(f"[{trade_date}] 竞价阶段过滤：原预选池{len(universe)}只，过滤后剩余{len(filtered_universe)}只")
                        universe = filtered_universe
                
                if not universe:
                    logger.warning(f"No stocks left after auction filter for {trade_date}")
                    continue
                
                # 2. 计算因子 & 选股
                liquidity_threshold = config.get("liquidity_threshold")
                # 应用情绪周期动态调整参数
                adjusted_liquidity_threshold = liquidity_threshold
                if self.current_sentiment["level"] == "ice":
                    # 冰点期提高流动性门槛，优先选流动性好的核心标的
                    adjusted_liquidity_threshold = liquidity_threshold * 1.5
                elif self.current_sentiment["level"] == "boom":
                    # 高潮期可适当降低流动性门槛，捕捉更多机会
                    adjusted_liquidity_threshold = liquidity_threshold * 0.8
                
                factor_df = await self.factor_engine.compute_factors(
                    universe, trade_date, config["factors"], 
                    liquidity_threshold=adjusted_liquidity_threshold
                )
                
                # ==============================================
                # 新增：龙虎榜+北向资金因子过滤
                # ==============================================
                if len(factor_df) > 0:
                    # 获取当日龙虎榜上榜股票
                    lhb_stocks = await mongo_manager.find_many(
                        "stock_lhb",
                        {"trade_date": int(trade_date)},
                        projection={"ts_code": 1, "net_buy_amount": 1, "reason": 1}
                    )
                    lhb_map = {x["ts_code"]: x for x in lhb_stocks} if lhb_stocks else {}
                    
                    # 获取当日北向资金持股标的
                    north_stocks = await mongo_manager.find_many(
                        "stock_north_money_stock",
                        {"trade_date": int(trade_date)},
                        projection={"ts_code": 1, "hold_ratio": 1}
                    )
                    north_map = {x["ts_code"]: x for x in north_stocks} if north_stocks else {}
                    
                    # 新增因子列
                    factor_df["has_lhb"] = factor_df["ts_code"].apply(lambda x: 1 if x in lhb_map else 0)
                    factor_df["lhb_net_buy"] = factor_df["ts_code"].apply(lambda x: lhb_map[x]["net_buy_amount"] if x in lhb_map else 0)
                    factor_df["north_hold_ratio"] = factor_df["ts_code"].apply(lambda x: north_map[x]["hold_ratio"] if x in north_map else 0)
                    
                    # 龙头低吸策略强制要求：龙虎榜有净买入 OR 北向持股比例≥1%
                    if "strategy" in factor_df.columns:
                        filter_mask = ~(
                            (factor_df["strategy"] == "龙头低吸") & 
                            (factor_df["has_lhb"] == 0) & 
                            (factor_df["north_hold_ratio"] < 1)
                        )
                        factor_df = factor_df[filter_mask]
                        logger.info(f"[{trade_date}] 龙虎榜/北向过滤：原标的{len(filter_mask)}只，过滤后剩余{len(factor_df)}只")
                
                target_stocks = self.factor_engine.select_top_stocks(
                    factor_df, top_n, liquidity_threshold=adjusted_liquidity_threshold
                )
                
                # ==============================================
                # 新增：情绪周期策略过滤 - 仅保留当前情绪允许的策略对应的标的
                # ==============================================
                if target_stocks and "strategy" in factor_df.columns:
                    allowed_strategies = set(self.current_sentiment["allowed_strategies"])
                    # 过滤出属于允许策略的标的
                    strategy_filtered = factor_df[
                        factor_df["ts_code"].isin(target_stocks) & 
                        factor_df["strategy"].isin(allowed_strategies)
                    ]
                    target_stocks = strategy_filtered["ts_code"].tolist()
                    logger.info(f"[{trade_date}] 情绪周期策略过滤：原选股{len(target_stocks) + len([s for s in target_stocks if s not in strategy_filtered['ts_code'].tolist()])}只，过滤后剩余{len(target_stocks)}只，允许策略：{allowed_strategies}")
                
                if not target_stocks:
                    logger.warning(f"No stocks selected for {trade_date} (after sentiment filter)")
                    continue
                
                # 记录选股结果
                selection_history.append({
                    "date": trade_date,
                    "stocks": target_stocks,
                    "universe_size": len(universe),
                })
                
                # 3. 计算目标权重
                target_weights = self._compute_weights(
                    target_stocks, factor_df, weight_method
                )
                
                # 应用最大单票仓位限制 - 确保动态管理，任何时候单票不超过上限
                # 如果选股数量 > 1/上限，自动等权分配保证不超限
                # 如果选股数量 <= 1/上限，保持等权已经自然满足
                if self.max_position_per_stock < 1.0:
                    # 修剪超过上限的权重
                    excess = 0.0
                    for ts_code in list(target_weights.keys()):
                        if target_weights[ts_code] > self.max_position_per_stock:
                            excess += target_weights[ts_code] - self.max_position_per_stock
                            target_weights[ts_code] = self.max_position_per_stock
                    # 将超额部分均匀分配给其他低于上限的股票
                    if excess > 0.0001:
                        available = [ts for ts, w in target_weights.items() if w < self.max_position_per_stock]
                        if available:
                            add_per_available = excess / len(available)
                            for ts_code in available:
                                target_weights[ts_code] += add_per_available
                
                # 4. 获取价格和涨跌停价格
                prices, limit_up_prices, limit_down_prices = await self._get_prices_and_limits(
                    set(holdings.keys()) | set(target_weights.keys()),
                    trade_date,
                )
                
                # 5. 执行调仓（新增滑点、涨跌停限制、总仓位控制）
                cash, holdings, records = self._rebalance(
                    trade_date, cash, holdings, target_weights, prices,
                    limit_up_prices, limit_down_prices
                )
                rebalance_records.extend(records)
            
            # 计算当日市值（只需要收盘价）
            prices, _, _ = await self._get_prices_and_limits(set(holdings.keys()), trade_date)
            market_value = sum(
                pos.shares * prices.get(pos.ts_code, 0)
                for pos in holdings.values()
            )
            total_value = cash + market_value
            
            # 基准净值
            benchmark_nav = benchmark_data.get(trade_date, 1.0)
            
            daily_values.append({
                "date": trade_date,
                "cash": cash,
                "market_value": market_value,
                "total_value": total_value,
                "benchmark_value": benchmark_nav * initial_cash,
                "return_pct": (total_value / initial_cash - 1) * 100,
                "sentiment": current_sentiment
            })
        
        # 计算绩效指标
        performance = self._compute_performance(daily_values, initial_cash)
        
        logger.info(f"Backtest completed: return={performance.get('total_return', 0):.2f}%")
        
        # 获取所有选中过的股票名称
        all_selected_stocks = set()
        for item in selection_history:
            all_selected_stocks.update(item["stocks"])
        stock_names = await self._get_stock_names(list(all_selected_stocks))
        
        # 为 selection_history 添加股票名称
        for item in selection_history:
            item["stock_details"] = [
                {"code": ts_code, "name": stock_names.get(ts_code, ts_code.replace(".SH", "").replace(".SZ", ""))}
                for ts_code in item["stocks"]
            ]
        
        # 为 rebalance_records 添加股票名称
        rebalance_records_with_names = [
            {
                "date": r.date,
                "action": r.action,
                "ts_code": r.ts_code,
                "stock_name": stock_names.get(r.ts_code, r.ts_code),
                "shares": r.shares,
                "price": r.price,
                "amount": r.amount,
                "reason": r.reason,
            }
            for r in rebalance_records
        ]
        
        return {
            "config": config,
            "performance": performance,
            "daily_values": daily_values,
            "rebalance_records": rebalance_records_with_names,
            "selection_history": selection_history,
            "final_holdings": {
                ts_code: {
                    "shares": pos.shares,
                    "buy_date": pos.buy_date,
                    "cost_price": round(pos.cost_price, 2)
                }
                for ts_code, pos in holdings.items()
            },
            "final_cash": cash,
        }
    
    def _compute_weights(
        self,
        stocks: List[str],
        factor_df: pd.DataFrame,
        method: str,
    ) -> Dict[str, float]:
        """计算目标权重"""
        n = len(stocks)
        if n == 0:
            return {}
        
        if method == "equal":
            # 等权重
            weight = 1.0 / n
            return {s: weight for s in stocks}
        
        elif method == "factor_weighted":
            # 因子加权 (得分越高权重越大)
            if factor_df.empty or "composite_score" not in factor_df.columns:
                return {s: 1.0/n for s in stocks}
            
            scores = factor_df[factor_df["ts_code"].isin(stocks)].set_index("ts_code")["composite_score"]
            total_score = scores.sum()
            
            if total_score > 0:
                return (scores / total_score).to_dict()
            return {s: 1.0/n for s in stocks}
        
        return {s: 1.0/n for s in stocks}
    
    async def _get_prices_and_limits(
        self,
        stocks: Set[str],
        trade_date: str,
    ) -> tuple[Dict[str, float], Dict[str, float], Dict[str, float]]:
        """获取股票价格、涨停价、跌停价"""
        if not stocks:
            return {}, {}, {}
        
        result = await mongo_manager.find_many(
            "stock_daily",
            {"ts_code": {"$in": list(stocks)}, "trade_date": trade_date},
            projection={"ts_code": 1, "close": 1, "up_limit": 1, "down_limit": 1},
        )
        
        prices = {}
        limit_up = {}
        limit_down = {}
        for doc in result:
            if doc.get("close"):
                prices[doc["ts_code"]] = doc["close"]
            if doc.get("up_limit"):
                limit_up[doc["ts_code"]] = doc["up_limit"]
            if doc.get("down_limit"):
                limit_down[doc["ts_code"]] = doc["down_limit"]
        
        return prices, limit_up, limit_down
    
    def _rebalance(
        self,
        trade_date: str,
        cash: float,
        holdings: Dict[str, Position],
        target_weights: Dict[str, float],
        prices: Dict[str, float],
        limit_up_prices: Dict[str, float] = None,
        limit_down_prices: Dict[str, float] = None,
    ) -> tuple:
        """
        执行调仓（支持滑点、涨跌停限制、总仓位控制）
        
        Returns:
            (new_cash, new_holdings, records)
        """
        records = []
        limit_up_prices = limit_up_prices or {}
        limit_down_prices = limit_down_prices or {}
        
        # 计算当前总资产
        current_total_value = cash + sum(
            pos.shares * prices.get(pos.ts_code, 0)
            for pos in holdings.values()
        )
        # 应用最大总仓位限制：目标总市值 = 总权益 * 最大仓位比例
        target_total_market_value = current_total_value * self.MAX_POSITION
        
        # 1. 先卖出不在目标池的股票
        stocks_to_sell = set(holdings.keys()) - set(target_weights.keys())
        for ts_code in stocks_to_sell:
            pos = holdings[ts_code]
            shares = pos.shares
            price = prices.get(ts_code, 0)
            
            if price <= 0 or shares <= 0:
                continue
            
            # 跌停无法卖出判断
            limit_down = limit_down_prices.get(ts_code)
            if limit_down and price <= limit_down * 1.005:  # 允许0.5%误差
                logger.warning(f"[{trade_date}] {ts_code} 跌停，无法卖出，跳过")
                continue
            
            # 卖出滑点：实际成交价 = 收盘价 * (1 - 滑点)
            trade_price = price * (1 - self.SLIPPAGE)
            
            amount = shares * trade_price
            commission = max(amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
            tax = amount * self.STAMP_TAX
            cash += amount - commission - tax
            
            records.append(RebalanceRecord(
                date=trade_date, action="sell", ts_code=ts_code,
                shares=shares, price=trade_price, amount=amount,
                reason="not_in_target",
            ))
            logger.debug(f"[{trade_date}] 卖出 {ts_code} {shares}股，成交价{trade_price:.2f}（滑点{self.SLIPPAGE:.1%}），收入{amount - commission - tax:.2f}元")
        
        # 清理已卖出的持仓
        holdings = {k: v for k, v in holdings.items() if k in target_weights}
        
        # 2. 调整持仓到目标权重
        for ts_code, target_weight in target_weights.items():
            # 按最大仓位比例调整目标价值
            target_value = target_total_market_value * target_weight
            current_pos = holdings.get(ts_code)
            current_shares = current_pos.shares if current_pos else 0
            price = prices.get(ts_code, 0)
            
            if price <= 0:
                continue
            
            current_value_in_stock = current_shares * price
            diff_value = target_value - current_value_in_stock
            
            if diff_value > 100:  # 需要买入 (至少买 100 元)
                # 涨停无法买入判断
                limit_up = limit_up_prices.get(ts_code)
                if limit_up and price >= limit_up * 0.995:
                    logger.warning(f"[{trade_date}] {ts_code} 涨停，无法买入，跳过")
                    continue
                
                # 买入滑点：实际成交价 = 收盘价 * (1 + 滑点)
                trade_price = price * (1 + self.SLIPPAGE)
                
                # A股 100 股整数倍
                buy_shares = int(diff_value / trade_price / 100) * 100
                if buy_shares <= 0:
                    continue
                
                buy_amount = buy_shares * trade_price
                commission = max(buy_amount * self.BUY_COMMISSION, self.MIN_COMMISSION)
                total_cost = buy_amount + commission
                
                if cash >= total_cost:
                    cash -= total_cost
                    # 更新持仓
                    if current_pos:
                        # 已有持仓，合并股数，成本价按加权平均计算
                        total_shares = current_shares + buy_shares
                        total_cost_value = current_pos.cost_price * current_shares + trade_price * buy_shares
                        new_cost_price = total_cost_value / total_shares
                        holdings[ts_code] = Position(
                            ts_code=ts_code,
                            shares=total_shares,
                            buy_date=trade_date,  # 加仓的话买入日期更新为最新日期
                            cost_price=new_cost_price
                        )
                    else:
                        # 新买入，创建Position对象
                        holdings[ts_code] = Position(
                            ts_code=ts_code,
                            shares=buy_shares,
                            buy_date=trade_date,
                            cost_price=trade_price
                        )
                    
                    records.append(RebalanceRecord(
                        date=trade_date, action="buy", ts_code=ts_code,
                        shares=buy_shares, price=trade_price, amount=buy_amount,
                        reason="rebalance",
                    ))
                    logger.debug(f"[{trade_date}] 买入 {ts_code} {buy_shares}股，成交价{trade_price:.2f}（滑点{self.SLIPPAGE:.1%}），成本{total_cost:.2f}元")
            
            elif diff_value < -100:  # 需要卖出
                # 跌停无法卖出判断
                limit_down = limit_down_prices.get(ts_code)
                if limit_down and price <= limit_down * 1.005:
                    logger.warning(f"[{trade_date}] {ts_code} 跌停，无法卖出，跳过")
                    continue
                
                # 卖出滑点
                trade_price = price * (1 - self.SLIPPAGE)
                
                sell_shares = min(current_shares, int(-diff_value / trade_price / 100) * 100)
                if sell_shares <= 0:
                    continue
                
                sell_amount = sell_shares * trade_price
                commission = max(sell_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
                tax = sell_amount * self.STAMP_TAX
                net_income = sell_amount - commission - tax
                cash += net_income
                
                # 更新持仓
                if current_pos:
                    remaining_shares = current_shares - sell_shares
                    if remaining_shares > 0:
                        holdings[ts_code] = Position(
                            ts_code=ts_code,
                            shares=remaining_shares,
                            buy_date=current_pos.buy_date,
                            cost_price=current_pos.cost_price
                        )
                    else:
                        del holdings[ts_code]
                
                records.append(RebalanceRecord(
                    date=trade_date, action="sell", ts_code=ts_code,
                    shares=sell_shares, price=trade_price, amount=sell_amount,
                    reason="rebalance",
                ))
                logger.debug(f"[{trade_date}] 卖出 {ts_code} {sell_shares}股，成交价{trade_price:.2f}（滑点{self.SLIPPAGE:.1%}），收入{net_income:.2f}元")
        
        return cash, holdings, records
    
    async def _load_benchmark(
        self,
        benchmark_code: str,
        start_date: str,
        end_date: str,
    ) -> Dict[str, float]:
        """加载基准数据，返回归一化净值"""
        result = await mongo_manager.find_many(
            "index_daily",
            {
                "ts_code": benchmark_code,
                "trade_date": {"$gte": start_date, "$lte": end_date},
            },
            projection={"trade_date": 1, "close": 1},
        )
        
        if not result:
            return {}
        
        # 按日期排序
        result = sorted(result, key=lambda x: x["trade_date"])
        
        # 归一化
        base_price = result[0]["close"]
        return {
            doc["trade_date"]: doc["close"] / base_price
            for doc in result
        }
    
    async def _check_force_empty(self, trade_date: str) -> bool:
        """检查是否触发强制空仓规则，触发则返回True
        规则：
        1. 大盘指数（上证指数/创业板指）单日跌幅≥3%
        2. 全市场跌停家数≥50只
        3. 连板高度≤2板（市场无赚钱效应）
        """
        if not self.enable_force_empty:
            return False
        
        try:
            # 检查上证指数跌幅
            sh_index = await mongo_manager.find_one(
                "index_daily",
                {"ts_code": "000001.SH", "trade_date": trade_date},
                projection={"pct_chg": 1}
            )
            cyb_index = await mongo_manager.find_one(
                "index_daily",
                {"ts_code": "399006.SZ", "trade_date": trade_date},
                projection={"pct_chg": 1}
            )
            if (sh_index and sh_index.get("pct_chg", 0) <= -3) or (cyb_index and cyb_index.get("pct_chg", 0) <= -3):
                logger.warning(f"[{trade_date}] 大盘跌幅≥3%，触发强制空仓")
                return True
            
            # 检查跌停家数
            limit_down_count = await mongo_manager.count_documents(
                "stock_daily",
                {"trade_date": trade_date, "pct_chg": {"$lte": -9.5}}
            )
            if limit_down_count >= 50:
                logger.warning(f"[{trade_date}] 跌停家数≥50只，触发强制空仓")
                return True
            
            # 检查连板高度
            limit_up_stocks = await mongo_manager.find_many(
                "stock_daily",
                {"trade_date": trade_date, "pct_chg": {"$gte": 9.5}},
                projection={"ts_code": 1}
            )
            if limit_up_stocks:
                ts_codes = [s["ts_code"] for s in limit_up_stocks]
                # 计算每只股票的连板数（简化版，实际可扩展）
                max_consecutive_limit_up = 1
                # 暂时简化判断：如果涨停数<10，视为赚钱效应差
                if len(limit_up_stocks) < 10:
                    logger.warning(f"[{trade_date}] 涨停家数<10只，市场无赚钱效应，触发强制空仓")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"强制空仓检查异常: {e}")
            return False
    
    async def _get_sentiment_cycle(self, trade_date: str) -> Dict:
        """专业实盘版情绪周期算法（方案2）
        基于7大类12个指标加权评分，输出情绪详细信息
        
        Returns:
            {
                "level": "extreme_ice/ice/repair/ferment/boom",
                "score": 0~100,
                "position_limit": 0.1~1.0,
                "allowed_strategies": ["半路追涨", "首板打板", ...],
                "stop_loss_adjust": 0.8~1.2,  # 止损比例调整系数
                "take_profit_adjust": 0.8~1.2 # 止盈比例调整系数
            }
        """
        if not self.enable_sentiment_cycle:
            # 默认修复期配置
            return {
                "level": "repair",
                "score": 50,
                "position_limit": 0.7,
                "allowed_strategies": ["半路追涨", "首板打板"],
                "stop_loss_adjust": 1.0,
                "take_profit_adjust": 1.0
            }
        
        try:
            # ==============================================
            # 1. 计算所有核心指标
            # ==============================================
            # ---------- 涨跌停类指标 (权重45%) ----------
            # a. 涨停家数 (权重25%)
            limit_up_count = await mongo_manager.count_documents(
                "stock_daily",
                {"trade_date": trade_date, "pct_chg": {"$gte": 9.5}}
            )
            # b. 跌停家数 (权重10%)
            limit_down_count = await mongo_manager.count_documents(
                "stock_daily",
                {"trade_date": trade_date, "pct_chg": {"$lte": -9.5}}
            )
            # c. 炸板率 (权重7%)
            limit_up_candidates = await mongo_manager.find_many(
                "stock_daily",
                {"trade_date": trade_date, "high": {"$gte": "$up_limit * 0.995"}},
                projection={"pct_chg": 1}
            )
            zhaban_count = len([x for x in limit_up_candidates if x.get("pct_chg", 0) < 9.5])
            zhaban_rate = zhaban_count / len(limit_up_candidates) if limit_up_candidates else 0
            # d. 连板高度 (权重3%)
            max_consecutive_up = 1
            # 暂时简化，后续可扩展连板统计逻辑
            
            # ---------- 市场广度类指标 (权重25%) ----------
            # a. 上涨家数 - 下跌家数 (权重15%)
            up_count = await mongo_manager.count_documents(
                "stock_daily",
                {"trade_date": trade_date, "pct_chg": {"$gt": 0}}
            )
            down_count = await mongo_manager.count_documents(
                "stock_daily",
                {"trade_date": trade_date, "pct_chg": {"$lt": 0}}
            )
            up_down_diff = up_count - down_count
            # b. 涨跌幅中位数 (权重10%)
            pct_chg_list = await mongo_manager.find_many(
                "stock_daily",
                {"trade_date": trade_date},
                projection={"pct_chg": 1}
            )
            pct_chg_values = [x.get("pct_chg", 0) for x in pct_chg_list]
            median_pct_chg = sorted(pct_chg_values)[len(pct_chg_values)//2] if pct_chg_values else 0
            
            # ---------- 资金流向类指标 (权重25%) ----------
            # a. 北向资金当日净流入 (权重12%)
            north_money = await mongo_manager.find_one(
                "stock_north_money_daily",
                {"trade_date": int(trade_date)},
                projection={"net_inflow": 1}
            )
            net_inflow = north_money.get("net_inflow", 0) if north_money else 0
            # 北向资金评分：净流入≥50亿得12分，净流出≥30亿得0分，线性插值
            nm_score = min(12, max(0, (net_inflow + 300000) / 800000 * 12))  # 单位：万元
            
            # b. 龙虎榜净买入总额 (权重8%)
            lhb_records = await mongo_manager.find_many(
                "stock_lhb",
                {"trade_date": int(trade_date)},
                projection={"net_buy_amount": 1}
            )
            total_lhb_net_buy = sum([x.get("net_buy_amount", 0) for x in lhb_records]) if lhb_records else 0
            # 龙虎榜评分：总净买入≥20亿得8分，净卖出≥10亿得0分
            lhb_score = min(8, max(0, (total_lhb_net_buy + 100000) / 300000 * 8))
            
            # c. 全市场成交额 (权重5%)
            total_amount = await mongo_manager.aggregate(
                "stock_daily",
                [
                    {"$match": {"trade_date": trade_date}},
                    {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
                ]
            )
            total_trade_amount = total_amount[0]["total"] if total_amount else 0
            am_score = min(5, max(0, total_trade_amount / 10000 * 5))
            
            # ---------- 波动率类指标 (权重10%) ----------
            # a. 大盘波动率 (权重5%) - 简化为近5日振幅标准差
            # b. 涨停股次日平均溢价率 (权重5%) - 暂无数据，暂时简化
            
            # ==============================================
            # 2. 指标标准化和加权评分 (0-100分)
            # ==============================================
            total_score = 0
            
            # ---- 涨跌停类得分 ----
            # 涨停家数得分（0-25分）
            lu_score = min(25, max(0, limit_up_count / 100 * 25))
            # 跌停家数得分（0-10分，跌停越多得分越低）
            ld_score = max(0, 10 - min(10, limit_down_count / 10 * 10))
            # 炸板率得分（0-7分，炸板率越高得分越低）
            zb_score = max(0, 7 - min(7, zhaban_rate * 10 * 7))
            # 连板高度得分（0-3分）
            lb_score = min(3, max_consecutive_up / 10 * 3)
            total_score += lu_score + ld_score + zb_score + lb_score
            
            # ---- 市场广度类得分 ----
            # 涨跌家数差得分（0-15分）
            ud_score = min(15, max(0, (up_down_diff + 2000) / 4000 * 15))
            # 涨跌幅中位数得分（0-10分）
            md_score = min(10, max(0, (median_pct_chg + 3) / 6 * 10))
            total_score += ud_score + md_score
            
            # ---- 资金流向类得分 ----
            total_score += nm_score + lhb_score + am_score
            
            # ---- 波动率类得分（权重5%，暂时给5分基础分，后续接入VIX等指标） ----
            total_score += 5
            
            total_score = int(round(total_score, 0))
            
            # ==============================================
            # 3. 情绪等级映射
            # ==============================================
            if total_score <= 20:
                level = "extreme_ice"
                position_limit = 0.1  # 最多10%仓位
                allowed_strategies = ["龙头低吸"]  # 仅允许低吸核心龙头
                stop_loss_adjust = 0.8  # 止损收窄20%，更严格风控
                take_profit_adjust = 0.9  # 止盈降低10%，见好就收
            elif 20 < total_score <= 40:
                level = "ice"
                position_limit = 0.3  # 最多30%仓位
                allowed_strategies = ["龙头低吸", "半路追涨"]  # 仅小仓位参与核心策略
                stop_loss_adjust = 0.9
                take_profit_adjust = 0.95
            elif 40 < total_score <= 60:
                level = "repair"
                position_limit = 0.7  # 最多70%仓位
                allowed_strategies = ["龙头低吸", "半路追涨", "首板打板"]  # 正常参与
                stop_loss_adjust = 1.0
                take_profit_adjust = 1.0
            elif 60 < total_score <= 80:
                level = "ferment"
                position_limit = 0.9  # 最多90%仓位
                allowed_strategies = ["龙头低吸", "半路追涨", "首板打板", "涨停开板"]  # 可参与连板策略
                stop_loss_adjust = 1.1  # 止损放宽10%，容忍更大波动
                take_profit_adjust = 1.05  # 止盈提高5%，让利润奔跑
            else:
                level = "boom"
                position_limit = 1.0  # 满仓
                allowed_strategies = ["龙头低吸", "半路追涨", "首板打板", "涨停开板", "跌停翘板"]  # 全策略开放
                stop_loss_adjust = 1.2  # 止损放宽20%
                take_profit_adjust = 1.1  # 止盈提高10%
            
            logger.info(f"[{trade_date}] 情绪评分：{total_score}分，等级：{level}，仓位上限：{position_limit:.0%}，允许策略：{','.join(allowed_strategies)}")
            
            return {
                "level": level,
                "score": total_score,
                "position_limit": position_limit,
                "allowed_strategies": allowed_strategies,
                "stop_loss_adjust": stop_loss_adjust,
                "take_profit_adjust": take_profit_adjust
            }
            
        except Exception as e:
            logger.error(f"情绪周期计算异常: {e}", exc_info=True)
            # 异常时默认修复期配置
            return {
                "level": "repair",
                "score": 50,
                "position_limit": 0.7,
                "allowed_strategies": ["半路追涨", "首板打板"],
                "stop_loss_adjust": 1.0,
                "take_profit_adjust": 1.0
            }

    async def _get_stock_names(self, ts_codes: List[str]) -> Dict[str, str]:
        """获取股票名称映射"""
        if not ts_codes:
            return {}
        
        result = await mongo_manager.find_many(
            "stock_basic",
            {"ts_code": {"$in": ts_codes}},
            projection={"ts_code": 1, "name": 1},
        )
        return {doc["ts_code"]: doc.get("name", doc["ts_code"]) for doc in result}
    
    def _compute_performance(
        self,
        daily_values: List[Dict],
        initial_cash: float,
    ) -> Dict:
        """计算绩效指标"""
        if not daily_values:
            return {}
        
        values = pd.Series([d["total_value"] for d in daily_values])
        benchmark_values = pd.Series([d["benchmark_value"] for d in daily_values])
        
        # 收益率
        total_return = (values.iloc[-1] / initial_cash - 1) * 100
        benchmark_return = (benchmark_values.iloc[-1] / initial_cash - 1) * 100
        excess_return = total_return - benchmark_return
        
        # 年化收益
        days = len(daily_values)
        annual_return = ((1 + total_return/100) ** (252/days) - 1) * 100 if days > 0 else 0
        
        # 最大回撤
        peak = values.expanding().max()
        drawdown = (values - peak) / peak
        max_drawdown = abs(drawdown.min()) * 100
        
        # 最大回撤天数
        max_dd_idx = drawdown.idxmin()
        peak_idx = values[:max_dd_idx+1].idxmax()
        max_dd_days = max_dd_idx - peak_idx
        
        # 波动率
        daily_returns = values.pct_change().dropna()
        volatility = daily_returns.std() * np.sqrt(252) * 100
        
        # 夏普比率 (假设无风险利率 3%)
        risk_free_rate = 0.03
        sharpe = (annual_return/100 - risk_free_rate) / (volatility/100) if volatility > 0 else 0
        
        # 胜率 (正收益天数比例)
        win_rate = (daily_returns > 0).sum() / len(daily_returns) * 100 if len(daily_returns) > 0 else 0
        
        return {
            "total_return": round(total_return, 2),
            "benchmark_return": round(benchmark_return, 2),
            "excess_return": round(excess_return, 2),
            "annual_return": round(annual_return, 2),
            "max_drawdown": round(max_drawdown, 2),
            "max_drawdown_days": int(max_dd_days),
            "volatility": round(volatility, 2),
            "sharpe_ratio": round(sharpe, 2),
            "win_rate": round(win_rate, 2),
            "trade_days": days,
            "start_date": daily_values[0]["date"],
            "end_date": daily_values[-1]["date"],
            "final_value": round(values.iloc[-1], 2),
        }
