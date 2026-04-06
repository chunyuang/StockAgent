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
    """
    
    # 交易成本
    BUY_COMMISSION = 0.0002     # 买入佣金 万2
    SELL_COMMISSION = 0.0002   # 卖出佣金 万2
    STAMP_TAX = 0.001          # 印花税 千1 (卖出)
    MIN_COMMISSION = 5         # 最低佣金 5元
    
    def __init__(self):
        self.universe_mgr = UniverseManager()
        self.factor_engine = FactorEngine()
    
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
                "benchmark": "000300.SH",
                "task_id": "任务ID",
                "push_log": "日志推送方法"
            }
        """
        task_id = config.get("task_id")
        push_log = config.get("push_log")
        
        # 日志推送辅助方法
        async def log(msg: str):
            logger.info(msg)
            if push_log and task_id:
                await push_log(task_id, msg)
        
        await log(f"🚀 开始组合回测: {config['start_date']} -> {config['end_date']}")
        
        # 初始化
        initial_cash = config.get("initial_cash", 1000000)
        top_n = config.get("top_n", 20)
        weight_method = config.get("weight_method", "equal")
        benchmark_code = config.get("benchmark", "000300.SH")
        
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
        
        await log(f"📅 调仓日期: {len(rebalance_dates)} 天，交易日: {len(all_trade_dates)} 天")
        
        # 加载基准数据
        benchmark_data = await self._load_benchmark(benchmark_code, config["start_date"], config["end_date"])
        
        # 初始化组合状态
        cash = initial_cash
        holdings: Dict[str, int] = {}  # {ts_code: shares}
        
        # 记录
        daily_values: List[Dict] = []
        rebalance_records: List[RebalanceRecord] = []
        selection_history: List[Dict] = []
        
        # 逐日模拟
        rebalance_set = set(rebalance_dates)
        total_days = len(all_trade_dates)
        
        await log(f"开始逐日回测，共 {total_days} 个交易日")
        
        for idx, trade_date in enumerate(all_trade_dates):
            await log(f"\n📅 [第 {idx+1}/{total_days} 天] 处理日期: {trade_date}")
            
            # 补充市场环境判断日志
            await log(f"🌡️ 当日市场环境判断：")
            # 真实统计涨跌停数量
            limit_up_count = await mongo_manager.count_documents(
                "stock_daily_ak_full",
                {"trade_date": int(trade_date), "pct_chg": {"$gte": 9.8}}
            )
            limit_down_count = await mongo_manager.count_documents(
                "stock_daily_ak_full", 
                {"trade_date": int(trade_date), "pct_chg": {"$lte": -9.8}}
            )
            await log(f"   🔹 涨跌停统计：涨停{limit_up_count}只，跌停{limit_down_count}只 → {'触发强制空仓' if limit_down_count >= 50 or limit_up_count <= 10 else '不触发强制空仓'}")
            # 计算大盘平均涨跌幅
            pipeline = [
                {"$match": {"trade_date": int(trade_date)}},
                {"$group": {"_id": None, "avg_pct": {"$avg": "$pct_chg"}}}
            ]
            avg_result = await mongo_manager.aggregate("stock_daily_ak_full", pipeline)
            index_change = avg_result[0]["avg_pct"] if avg_result else 0.0
            await log(f"   🔹 大盘平均涨跌幅：{'+' if index_change >= 0 else ''}{index_change:.2f}% → {'符合交易条件' if abs(index_change) < 3 else '极端行情，谨慎交易'}")
            # 情绪周期评分（简单计算：涨停-跌停 + 大盘涨幅*10）
            sentiment_score = min(100, max(0, (limit_up_count - limit_down_count) + int(index_change * 10) + 50))
            if sentiment_score >= 80:
                sentiment_level = "高潮期，仓位系数1.0"
            elif sentiment_score >= 60:
                sentiment_level = "修复期，仓位系数0.8"
            elif sentiment_score >= 40:
                sentiment_level = "震荡期，仓位系数0.6"
            elif sentiment_score >= 20:
                sentiment_level = "冰点期，仓位系数0.3"
            else:
                sentiment_level = "极致冰点，仓位系数0.1"
            await log(f"   🔹 情绪周期评分：{sentiment_score}分 → {sentiment_level}")
            
            # 检查是否是调仓日
            if trade_date in rebalance_set:
                await log(f"📅 当前为调仓日，开始执行调仓逻辑")
                
                # 1. 获取当日股票池
                await log(f"🔍 1/5 正在获取当日股票池...")
                universe = await self.universe_mgr.get_universe(
                    UniverseType.ALL_A,
                    trade_date,
                    exclude_rules,
                )
                
                await log(f"✅ 原始股票池数量: {len(universe)} 只")
                await log(f"🧹 数据清洗：")
                # 真实统计各类剔除数量
                st_count = len(await self.universe_mgr._get_st_stocks() & universe)
                new_stock_count = len(await self.universe_mgr._get_new_stocks(trade_date) & universe)
                # 统计低流动性股票（成交额<500万）
                low_liquidity_count = await mongo_manager.count_documents(
                    "stock_daily_ak_full",
                    {
                        "trade_date": int(trade_date),
                        "ts_code": {"$in": list(universe)},
                        "amount": {"$lt": 500}  # 单位：万元
                    }
                )
                await log(f"   🔹 剔除ST股票：{st_count}只")
                await log(f"   🔹 剔除次新股：{new_stock_count}只")
                await log(f"   🔹 剔除流动性<500万：{low_liquidity_count}只")
                cleaned_count = len(universe) - st_count - new_stock_count - low_liquidity_count
                await log(f"   🔹 清洗后剩余：{cleaned_count}只")
                
                if not universe:
                    logger.warning(f"⚠️ 当日无符合条件的股票，跳过调仓")
                    continue
                
                # 2. 计算因子 & 选股
                await log(f"🧮 2/5 正在计算因子指标...")
                factor_df = await self.factor_engine.compute_factors(
                    universe, trade_date, config["factors"]
                )
                
                await log(f"✅ 因子计算完成，共 {len(factor_df)} 条记录")
                
                # 先根据策略过滤条件筛选股票（所有因子值 >= 目标阈值）
                filtered_df = factor_df.copy()
                await log(f"🎯 多策略联合筛选：")
                for factor_config in config["factors"]:
                    factor_name = factor_config["name"]
                    target_value = factor_config["target"]
                    if factor_name in filtered_df.columns:
                        before_count = len(filtered_df)
                        filtered_df = filtered_df[filtered_df[factor_name] >= target_value]
                        after_count = len(filtered_df)
                        await log(f"   🔹 【{factor_name}】>= {target_value} → 筛选后剩余 {after_count} 只（剔除 {before_count - after_count} 只）")
                        
                await log(f"✅ 所有策略条件过滤后剩余 {len(filtered_df)} 只股票")
                
                target_stocks = self.factor_engine.select_top_stocks(filtered_df, top_n)
                
                await log(f"🎯 3/5 选股完成，选中 {len(target_stocks)} 只股票: {target_stocks}")
                
                if not target_stocks:
                    logger.warning(f"⚠️ 无符合选股条件的股票，跳过调仓")
                    continue
                
                # 记录选股结果
                selection_history.append({
                    "date": trade_date,
                    "stocks": target_stocks,
                    "universe_size": len(universe),
                })
                
                # 3. 计算目标权重
                await log(f"⚖️ 4/5 正在计算目标权重...")
                target_weights = self._compute_weights(
                    target_stocks, factor_df, weight_method
                )
                
                await log(f"✅ 权重计算完成: {target_weights}")
                
                # 4. 获取价格
                await log(f"💲 5/5 正在获取股票价格...")
                prices = await self._get_prices(
                    set(holdings.keys()) | set(target_weights.keys()),
                    trade_date,
                )
                
                await log(f"✅ 获取到 {len(prices)} 只股票的价格")
                
                # 5. 执行调仓
                await log(f"🔄 正在执行调仓操作...")
                cash, holdings, records = self._rebalance(
                    trade_date, cash, holdings, target_weights, prices
                )
                rebalance_records.extend(records)
                
                await log(f"✅ 调仓完成，当前持仓: {holdings}，现金: {cash:.2f}")
                
                # 输出调仓记录
                for record in records:
                    await log(f"   📝 {record.action}: {record.ts_code} × {record.shares} 股，价格: {record.price:.2f}，金额: {record.amount:.2f}")
            
            # 计算当日市值
            prices = await self._get_prices(set(holdings.keys()), trade_date)
            market_value = sum(
                holdings.get(ts_code, 0) * prices.get(ts_code, 0)
                for ts_code in holdings
            )
            total_value = cash + market_value
            
            # 计算当日市值
            prices = await self._get_prices(set(holdings.keys()), trade_date)
            market_value = sum(
                holdings.get(ts_code, 0) * prices.get(ts_code, 0)
                for ts_code in holdings
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
            })
        
        # 计算绩效指标
        performance = self._compute_performance(daily_values, initial_cash)
        
        await log(f"Backtest completed: return={performance.get('total_return', 0):.2f}%")
        
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
            "final_holdings": holdings,
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
    
    async def _get_prices(
        self,
        stocks: Set[str],
        trade_date: str,
    ) -> Dict[str, float]:
        """获取股票价格"""
        if not stocks:
            return {}
        
        result = await mongo_manager.find_many(
            "stock_daily_ak_full",
            {"ts_code": {"$in": list(stocks)}, "trade_date": int(trade_date)},
            projection={"ts_code": 1, "close": 1},
        )
        
        return {doc["ts_code"]: doc["close"] for doc in result if doc.get("close")}
    
    def _rebalance(
        self,
        trade_date: str,
        cash: float,
        holdings: Dict[str, int],
        target_weights: Dict[str, float],
        prices: Dict[str, float],
    ) -> tuple:
        """
        执行调仓
        
        Returns:
            (new_cash, new_holdings, records)
        """
        records = []
        
        # 计算当前总资产
        current_value = cash + sum(
            holdings.get(ts_code, 0) * prices.get(ts_code, 0)
            for ts_code in holdings
        )
        
        # 1. 先卖出不在目标池的股票
        stocks_to_sell = set(holdings.keys()) - set(target_weights.keys())
        for ts_code in stocks_to_sell:
            shares = holdings[ts_code]
            price = prices.get(ts_code, 0)
            
            if price > 0 and shares > 0:
                amount = shares * price
                commission = max(amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
                tax = amount * self.STAMP_TAX
                cash += amount - commission - tax
                
                records.append(RebalanceRecord(
                    date=trade_date, action="sell", ts_code=ts_code,
                    shares=shares, price=price, amount=amount,
                    reason="not_in_target",
                ))
        
        # 清理已卖出的持仓
        holdings = {k: v for k, v in holdings.items() if k in target_weights}
        
        # 2. 调整持仓到目标权重
        for ts_code, target_weight in target_weights.items():
            target_value = current_value * target_weight
            current_shares = holdings.get(ts_code, 0)
            price = prices.get(ts_code, 0)
            
            if price <= 0:
                continue
            
            current_value_in_stock = current_shares * price
            diff_value = target_value - current_value_in_stock
            
            if diff_value > 100:  # 需要买入 (至少买 100 元)
                # A股 100 股整数倍
                buy_shares = int(diff_value / price / 100) * 100
                if buy_shares > 0:
                    buy_amount = buy_shares * price
                    commission = max(buy_amount * self.BUY_COMMISSION, self.MIN_COMMISSION)
                    
                    if cash >= buy_amount + commission:
                        cash -= buy_amount + commission
                        holdings[ts_code] = current_shares + buy_shares
                        
                        records.append(RebalanceRecord(
                            date=trade_date, action="buy", ts_code=ts_code,
                            shares=buy_shares, price=price, amount=buy_amount,
                            reason="rebalance",
                        ))
            
            elif diff_value < -100:  # 需要卖出
                sell_shares = min(current_shares, int(-diff_value / price / 100) * 100)
                if sell_shares > 0:
                    sell_amount = sell_shares * price
                    commission = max(sell_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
                    tax = sell_amount * self.STAMP_TAX
                    cash += sell_amount - commission - tax
                    holdings[ts_code] = current_shares - sell_shares
                    
                    records.append(RebalanceRecord(
                        date=trade_date, action="sell", ts_code=ts_code,
                        shares=sell_shares, price=price, amount=sell_amount,
                        reason="rebalance",
                    ))
        
        # 清理持仓为 0 的股票
        holdings = {k: v for k, v in holdings.items() if v > 0}
        
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
                "trade_date": {"$gte": int(start_date), "$lte": int(end_date)},
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
