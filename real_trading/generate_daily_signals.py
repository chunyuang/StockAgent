#!/usr/bin/env python3
"""
实盘每日信号生成器
每日盘后运行，生成当日情绪评分、选股信号、交易计划
"""
import sys
import logging

logger = logging.getLogger(__name__)
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))  # FIXME: 使用sys.path.insert做模块查找是反模式，应改用setup.py/pyproject.toml将项目安装到venv中
sys.path.insert(0, os.path.dirname(__file__))

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict

from core.managers import mongo_manager
from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
from backtest_module.backtest_engine.factor_selection.universe import UniverseManager, UniverseType, ExcludeRule

class RealTradingSignalGenerator:
    """实盘信号生成器
    
    每日盘后运行，生成次日交易信号，流程：
    1. 计算当日情绪周期评分 → 判断仓位上限和允许策略
    2. 检查强制空仓条件 → 触发则不生成信号
    3. 获取预选池（全A股，排除ST/次新股）
    4. 竞价阶段过滤（涨幅0.5%~7%、有成交量、有未匹配量）
    5. 计算多因子并排序（动量/量能/涨停/换手/波动/龙虎榜/北向）
    6. 情绪周期过滤（仅保留允许策略的标的）
    7. 选出TOP N标的
    8. 生成交易计划（含建议买入价、止损止盈价）
    """
    
    def __init__(self, config: Dict = None):
        """初始化信号生成器
        
        Args:
            config: 可选配置覆盖，支持的字段：
                - initial_cash: 初始资金，默认100万
                - max_position: 最大总仓位，默认0.7（70%）
                - max_position_per_stock: 单票最大仓位，默认0.2（20%）
                - max_hold_days: 最大持仓天数，默认3
                - stop_loss_pct: 止损比例，默认0.05（5%）
                - take_profit_pct: 止盈比例，默认0.1（10%）
                - liquidity_threshold: 成交额门槛，默认500万
                - volume_threshold: 量能放大倍数，默认1.5
                - top_n: 最多选N只标的，默认5
        """
        self.default_config = {
            "initial_cash": 1000000,
            "max_position": 0.7,          # 总仓位上限70%，留30%现金防风险
            "max_position_per_stock": 0.2, # 单票最大仓位20%，分散风险
            "max_hold_days": 3,            # 超短核心：最多持仓3天
            "stop_loss_pct": 0.02,         # 止损2%，超短必须严格止损
            "take_profit_pct": 0.07,       # 止盈7%，超短快进快出
            "liquidity_threshold": 5000000, # 500万成交额门槛，避免流动性陷阱
            "volume_threshold": 1.5,       # 量能放大1.5倍
            "slippage": 0.002,             # 滑点0.2%，超短打板滑点较大
            "enable_force_empty": True,
            "enable_sentiment_cycle": True,
            "enable_auction_filter": True,
            "top_n": 5,  # 最多选5只
        }
        self.config = {**self.default_config, **(config or {})}
        # 只传递PortfolioBacktester接受的初始化参数
        self.backtester = PortfolioBacktester(
            source="ak",
            slippage=self.config.get("slippage", 0.001),
            max_position=self.config.get("max_position", 0.7)
        )
        # 补充回测引擎缺少的实盘配置属性
        self.backtester.enable_sentiment_cycle = self.config.get("enable_sentiment_cycle", True)
        self.backtester.enable_force_empty = self.config.get("enable_force_empty", True)
        self.universe_mgr = UniverseManager()
    
    async def generate_signals(self, trade_date: str = None) -> Dict:
        """生成指定交易日的实盘信号
        
        执行完整的信号生成流水线：情绪周期→强制空仓检查→预选池→竞价过滤→
        因子计算→策略过滤→选股→生成交易计划
        
        Args:
            trade_date: 交易日期（YYYYMMDD），默认取最近一个交易日
        
        Returns:
            Dict: {
                date: 交易日期,
                force_empty: 是否强制空仓,
                sentiment: 情绪周期信息,
                universe_size: 预选池数量,
                signals: 选中的标的列表,
                trading_plan: Markdown格式交易计划,
                generated_at: 生成时间
            }
        """
        if not trade_date:
            # 默认取最近一个交易日
            trade_date = self._get_latest_trade_date()
        
        logger.info(f"========== 生成 {trade_date} 实盘信号 ==========")
        
        # 1. 计算当日情绪周期
        sentiment_info = await self.backtester._get_sentiment_cycle(trade_date)
        logger.info(f"📊 情绪评分：{sentiment_info['score']}分，等级：{sentiment_info['level']}")
        logger.info(f"⚖️  仓位上限：{sentiment_info['position_limit']:.0%}")
        logger.info(f"✅ 允许策略：{', '.join(sentiment_info['allowed_strategies'])}")
        
        # 2. 检查强制空仓
        force_empty = await self.backtester._check_force_empty(trade_date)
        if force_empty:
            logger.warning("⚠️  触发强制空仓，今日无交易信号")
            return {
                "date": trade_date,
                "force_empty": True,
                "sentiment": sentiment_info,
                "signals": [],
                "trading_plan": "空仓观望，不进行任何交易"
            }
        
        # 3. 获取预选池
        exclude_rules = [ExcludeRule.ST, ExcludeRule.NEW_STOCK]
        universe = await self.universe_mgr.get_universe(
            UniverseType.ALL_A,
            trade_date,
            exclude_rules,
        )
        logger.debug(f"🔍 预选池数量：{len(universe)}只")
        
        # 4. 竞价阶段过滤
        if self.config["enable_auction_filter"]:
            universe = await self._auction_filter(universe, trade_date)
            logger.debug(f"🔍 竞价过滤后剩余：{len(universe)}只")
        
        if not universe:
            logger.warning("⚠️  预选池为空，今日无交易信号")
            return {
                "date": trade_date,
                "force_empty": False,
                "sentiment": sentiment_info,
                "signals": [],
                "trading_plan": "无符合条件标的，空仓观望"
            }
        
        # 5. 计算因子 & 选股
        factor_df = await self.backtester.factor_engine.compute_factors(
            universe, trade_date, self._get_factors_config(),
            liquidity_threshold=self.config["liquidity_threshold"]
        )
        
        # 6. 情绪周期策略过滤
        allowed_strategies = set(sentiment_info["allowed_strategies"])
        if "strategy" in factor_df.columns:
            factor_df = factor_df[factor_df["strategy"].isin(allowed_strategies)]
        
        # 7. 选择TOP标的
        target_stocks = self.backtester.factor_engine.select_top_stocks(
            factor_df, self.config["top_n"],
            liquidity_threshold=self.config["liquidity_threshold"]
        )
        
        # 8. 获取股票详细信息
        stock_details = await self._get_stock_details(target_stocks, trade_date)
        
        # 9. 生成交易计划
        trading_plan = self._generate_trading_plan(stock_details, sentiment_info)
        
        logger.info(f"🎯 最终选中标的：{len(stock_details)}只")
        for idx, stock in enumerate(stock_details, 1):
            logger.info(f"{idx}. {stock['ts_code']} {stock['name']} | 策略：{stock['strategy']} | 收盘价：{stock['close']:.2f} | 涨跌幅：{stock['pct_chg']:.2f}%")
        
        return {
            "date": trade_date,
            "force_empty": False,
            "sentiment": sentiment_info,
            "universe_size": len(universe),
            "signals": stock_details,
            "trading_plan": trading_plan,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def _get_factors_config(self) -> List[Dict]:
        """获取策略因子权重配置
        
        返回7个因子的名称和权重，用于多因子打分排序：
        - momentum_5d: 5日动量（权重0.2）
        - volume_increase: 量能放大（权重0.2）
        - limit_up_count: 涨停次数（权重0.2）
        - turnover_rate: 换手率（权重0.15）
        - volatility_20d: 20日波动率（权重0.15）
        - has_lhb: 龙虎榜（权重0.05）
        - north_hold_ratio: 北向持股比例（权重0.05）
        
        Returns:
            List[Dict]: 因子配置列表
        """
        return [
            {"name": "momentum_5d", "weight": 0.2},
            {"name": "volume_increase", "weight": 0.2},
            {"name": "limit_up_count", "weight": 0.2},
            {"name": "turnover_rate", "weight": 0.15},
            {"name": "volatility_20d", "weight": 0.15},
            {"name": "has_lhb", "weight": 0.05},
            {"name": "north_hold_ratio", "weight": 0.05},
        ]
    
    async def _auction_filter(self, universe: List[str], trade_date: str) -> List[str]:
        """竞价阶段过滤
        
        从MongoDB获取集合竞价数据，过滤掉不符合竞价特征的标的：
        - 竞价涨幅必须在0.5%~7%之间（排除一字涨停和低开）
        - 竞价成交量 > 0（排除无成交的）
        - 未匹配量 > 0（排除无买盘的）
        
        Args:
            universe: 待过滤的股票代码列表
            trade_date: 交易日期（YYYYMMDD）
        
        Returns:
            List[str]: 过滤后的股票代码列表
        """
        from core.managers import mongo_manager
        
        try:
            auction_data = await mongo_manager.find_many(
                "stock_bid_auction",
                {"trade_date": int(trade_date)},
                projection={"ts_code": 1, "auction_pct_chg": 1, "auction_volume": 1, "unmatched_volume": 1}
            )
        except (ConnectionError, OSError, ValueError) as e:
            logger.error(f"⚠️  获取竞价数据失败: {e}，跳过竞价过滤")
            return universe
        except Exception as e:
            logger.error(f"⚠️  获取竞价数据异常: {e}，跳过竞价过滤")
            return universe
        
        if not auction_data:
            return universe
        
        auction_map = {x.get("ts_code", ""): x for x in auction_data if x.get("ts_code")}
        filtered = []
        
        for ts_code in universe:
            if ts_code not in auction_map:
                continue
            auction = auction_map[ts_code]
            # 竞价过滤规则 - 使用get防止KeyError
            auction_pct = auction.get("auction_pct_chg", 0)
            auction_vol = auction.get("auction_volume", 0)
            unmatched_vol = auction.get("unmatched_volume", 0)
            if not (0.5 <= auction_pct <= 7):
                continue
            if auction_vol <= 0:
                continue
            if unmatched_vol <= 0:
                continue
            filtered.append(ts_code)
        
        return filtered
    
    async def _get_stock_details(self, ts_codes: List[str], trade_date: str) -> List[Dict]:
        """获取股票详细信息，合并日线/基础/龙虎榜数据
        
        从MongoDB三张表聚合数据：
        - stock_daily_ak_full: 日线行情（收盘价、涨跌幅、涨跌停价）
        - stock_basic: 股票基础信息（名称、行业）
        - stock_lhb: 龙虎榜数据（净买入、上榜原因）
        
        Args:
            ts_codes: 股票代码列表
            trade_date: 交易日期（YYYYMMDD）
        
        Returns:
            List[Dict]: 每只股票的详细信息字典
        """
        from core.managers import mongo_manager
        
        if not ts_codes:
            return []
        
        # 获取日线数据
        daily_map = {}
        try:
            daily_data = await mongo_manager.find_many(
                "stock_daily_ak_full",
                {"ts_code": {"$in": ts_codes}, "trade_date": int(trade_date)},
                projection={"ts_code": 1, "close": 1, "pct_chg": 1, "amount": 1, "volume": 1, "up_limit": 1, "down_limit": 1}
            )
            if daily_data:
                daily_map = {x.get("ts_code", ""): x for x in daily_data if x.get("ts_code")}
        except Exception as e:
            logger.error(f"⚠️  获取日线数据失败: {e}")
        
        # 获取股票名称
        basic_map = {}
        try:
            basic_data = await mongo_manager.find_many(
                "stock_basic",
                {"ts_code": {"$in": ts_codes}},
                projection={"ts_code": 1, "name": 1, "industry": 1}
            )
            if basic_data:
                basic_map = {x.get("ts_code", ""): x for x in basic_data if x.get("ts_code")}
        except Exception as e:
            logger.error(f"⚠️  获取基础数据失败: {e}")
        
        # 获取龙虎榜数据
        lhb_map = {}
        try:
            lhb_data = await mongo_manager.find_many(
                "stock_lhb",
                {"ts_code": {"$in": ts_codes}, "trade_date": int(trade_date)},
                projection={"ts_code": 1, "net_buy_amount": 1, "reason": 1}
            )
            if lhb_data:
                lhb_map = {x.get("ts_code", ""): x for x in lhb_data if x.get("ts_code")}
        except Exception as e:
            logger.error(f"⚠️  获取龙虎榜数据失败: {e}")
        
        # 合并信息
        details = []
        for ts_code in ts_codes:
            daily = daily_map.get(ts_code, {})
            basic = basic_map.get(ts_code, {})
            lhb = lhb_map.get(ts_code, {})
            
            # 使用.get()防止数据缺失导致KeyError
            close_price = daily.get("close", 0) if isinstance(daily, dict) else 0
            pct_chg = daily.get("pct_chg", 0) if isinstance(daily, dict) else 0
            details.append({
                "ts_code": ts_code,
                "name": basic.get("name", ts_code) if isinstance(basic, dict) else ts_code,
                "industry": basic.get("industry", "未知") if isinstance(basic, dict) else "未知",
                "close": close_price,
                "pct_chg": pct_chg,
                "amount": daily.get("amount", 0) if isinstance(daily, dict) else 0,
                "up_limit": daily.get("up_limit", 0) if isinstance(daily, dict) else 0,
                "down_limit": daily.get("down_limit", 0) if isinstance(daily, dict) else 0,
                "has_lhb": ts_code in lhb_map,
                "lhb_net_buy": lhb.get("net_buy_amount", 0) if isinstance(lhb, dict) else 0,
                "lhb_reason": lhb.get("reason", "") if isinstance(lhb, dict) else "",
                "strategy": self._get_strategy_for_stock(ts_code, daily if isinstance(daily, dict) else {}),
            })
        
        return details
    
    def _get_strategy_for_stock(self, ts_code: str, daily_data: Dict) -> str:
        """根据行情数据判断股票所属策略类型
        
        简单规则：
        - 涨停板附近 → '首板打板'
        - 涨幅≥5%但未涨停 → '半路追涨'
        - 其他 → '龙头低吸'
        
        Args:
            ts_code: 股票代码
            daily_data: 当日行情数据字典
        
        Returns:
            str: 策略名称
        """
        pct_chg = daily_data.get("pct_chg", 0)
        limit_up = daily_data.get("up_limit", 0)
        close = daily_data.get("close", 0)
        
        if abs(pct_chg - 10) < 0.5 and abs(close - limit_up) < 0.01:
            return "首板打板"
        elif pct_chg >= 5:
            return "半路追涨"
        else:
            return "龙头低吸"
    
    def _generate_trading_plan(self, signals: List[Dict], sentiment_info: Dict) -> str:
        """生成Markdown格式交易计划
        
        内容包括：
        - 情绪等级和仓位上限
        - 可选标的列表（含建议买入价、仓位、止损止盈价）
        - 交易纪律提醒
        
        Args:
            signals: 选中的标的信号列表
            sentiment_info: 情绪周期信息字典
        
        Returns:
            str: Markdown格式交易计划文本
        """
        if not signals:
            return "无符合条件标的，建议空仓观望"
        
        plan = [
            f"### 今日交易计划（{sentiment_info['level']}，仓位上限{sentiment_info['position_limit']:.0%}）",
            "",
            "#### 可选标的（按优先级排序）："
        ]
        
        total_value = self.config["initial_cash"] * sentiment_info["position_limit"]
        per_stock_value = total_value / min(len(signals), self.config["top_n"])
        
        for idx, stock in enumerate(signals, 1):
            buy_price = stock["close"] * 1.01  # 预计买入价格（比收盘价高1%，应对高开）
            buy_shares = int(per_stock_value / buy_price / 100) * 100
            stop_loss_pct = self.config["stop_loss_pct"] * sentiment_info.get("stop_loss_adjust", 1.0)
            take_profit_pct = self.config["take_profit_pct"] * sentiment_info.get("take_profit_adjust", 1.0)
            stop_loss_price = buy_price * (1 - stop_loss_pct)
            take_profit_price = buy_price * (1 + take_profit_pct)
            
            plan.append(f"{idx}. **{stock['name']}({stock['ts_code']})**")
            plan.append(f"   策略：{stock['strategy']} | 行业：{stock['industry']}")
            plan.append(f"   建议买入价：≤{buy_price:.2f} | 仓位：{buy_shares}股（约{per_stock_value:.0f}元）")
            plan.append(f"   止损价：{stop_loss_price:.2f}（跌幅{self.config['stop_loss_pct'] * sentiment_info['stop_loss_adjust'] * 100:.1f}%）")
            plan.append(f"   止盈价：{take_profit_price:.2f}（涨幅{self.config['take_profit_pct'] * sentiment_info['take_profit_adjust'] * 100:.1f}%）")
            if stock["has_lhb"]:
                plan.append(f"   🎉 今日上榜龙虎榜，净买入{stock['lhb_net_buy']/10000:.1f}万，上榜原因：{stock['lhb_reason']}")
            plan.append("")
        
        plan.append("#### 交易纪律：")
        plan.append("1. 严格执行止损，触及止损价立即卖出，不得抱有幻想")
        plan.append("2. 单票仓位不得超过20%，总仓位不得超过上限")
        plan.append(f"3. 所有持仓最多持有{self.config['max_hold_days']}天，到期强制卖出")
        plan.append("4. 优先买排名靠前的标的，开盘不及预期直接放弃")
        
        return "\n".join(plan)
    
    def _get_latest_trade_date(self) -> str:
        """获取最近一个交易日（简单逻辑，未接入交易日历API）
        
        规则：
        - 周末 → 回退到周五
        - 工作日15:00后 → 当天
        - 工作日15:00前 → 前一天
        
        Returns:
            str: 交易日期（YYYYMMDD）
        """
        now = datetime.now()
        # 简单处理，实际可调用交易日历接口
        if now.weekday() >= 5:  # 周末
            offset = now.weekday() - 4
            latest = now - timedelta(days=offset)
        else:
            latest = now if now.hour >= 15 else now - timedelta(days=1)
        return latest.strftime("%Y%m%d")


async def main():
    # 初始化MongoDB连接
    await mongo_manager.initialize()
    
    import argparse
    parser = argparse.ArgumentParser(description="实盘每日信号生成器")
    parser.add_argument("--date", help="指定日期(YYYYMMDD)，默认最近一个交易日")
    parser.add_argument("--output", help="输出文件路径，默认打印到控制台")
    
    args = parser.parse_args()
    
    generator = RealTradingSignalGenerator()
    signals = await generator.generate_signals(args.date)
    
    # 输出结果
    if args.output:
        import json
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(signals, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ 信号已保存到：{args.output}")
    else:
        logger.info("\n" + "="*50)
        logger.info(signals["trading_plan"])
        logger.info("="*50)

if __name__ == "__main__":
    asyncio.run(main())
