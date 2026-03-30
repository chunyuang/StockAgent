#!/usr/bin/env python3
"""
实盘每日信号生成器
每日盘后运行，生成当日情绪评分、选股信号、交易计划
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))
sys.path.insert(0, os.path.dirname(__file__))

import asyncio
from datetime import datetime, timedelta
import pandas as pd
from typing import List, Dict

from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
from backtest_module.backtest_engine.factor_selection.universe import UniverseManager, UniverseType, ExcludeRule

class RealTradingSignalGenerator:
    """实盘信号生成器"""
    
    def __init__(self, config: Dict = None):
        self.default_config = {
            "initial_cash": 1000000,
            "max_position": 0.7,
            "max_position_per_stock": 0.2,
            "max_hold_days": 3,
            "stop_loss_pct": 0.05,
            "take_profit_pct": 0.1,
            "liquidity_threshold": 5000000,  # 500万成交额门槛
            "volume_threshold": 1.5,  # 量能放大1.5倍
            "enable_force_empty": True,
            "enable_sentiment_cycle": True,
            "enable_auction_filter": True,
            "top_n": 5,  # 最多选5只
        }
        self.config = {**self.default_config, **(config or {})}
        self.backtester = PortfolioBacktester(source="ak", **self.config)
        self.universe_mgr = UniverseManager()
    
    async def generate_signals(self, trade_date: str = None) -> Dict:
        """生成指定交易日的实盘信号"""
        if not trade_date:
            # 默认取最近一个交易日
            trade_date = self._get_latest_trade_date()
        
        print(f"========== 生成 {trade_date} 实盘信号 ==========")
        
        # 1. 计算当日情绪周期
        sentiment_info = await self.backtester._get_sentiment_cycle(trade_date)
        print(f"📊 情绪评分：{sentiment_info['score']}分，等级：{sentiment_info['level']}")
        print(f"⚖️  仓位上限：{sentiment_info['position_limit']:.0%}")
        print(f"✅ 允许策略：{', '.join(sentiment_info['allowed_strategies'])}")
        
        # 2. 检查强制空仓
        force_empty = await self.backtester._check_force_empty(trade_date)
        if force_empty:
            print("⚠️  触发强制空仓，今日无交易信号")
            return {
                "date": trade_date,
                "force_empty": True,
                "sentiment": sentiment_info,
                "signals": [],
                "trading_plan": "空仓观望，不进行任何交易"
            }
        
        # 3. 获取预选池
        exclude_rules = [ExcludeRule.ST, ExcludeRule.NEW_STOCK, ExcludeRule.LOW_LIQUIDITY]
        universe = await self.universe_mgr.get_universe(
            UniverseType.ALL_A,
            trade_date,
            exclude_rules,
        )
        print(f"🔍 预选池数量：{len(universe)}只")
        
        # 4. 竞价阶段过滤
        if self.config["enable_auction_filter"]:
            universe = await self._auction_filter(universe, trade_date)
            print(f"🔍 竞价过滤后剩余：{len(universe)}只")
        
        if not universe:
            print("⚠️  预选池为空，今日无交易信号")
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
        
        print(f"🎯 最终选中标的：{len(stock_details)}只")
        for idx, stock in enumerate(stock_details, 1):
            print(f"{idx}. {stock['ts_code']} {stock['name']} | 策略：{stock['strategy']} | 收盘价：{stock['close']:.2f} | 涨跌幅：{stock['pct_chg']:.2f}%")
        
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
        """获取策略因子配置"""
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
        """竞价阶段过滤"""
        from core.managers import mongo_manager
        
        auction_data = await mongo_manager.find_many(
            "stock_bid_auction",
            {"trade_date": int(trade_date)},
            projection={"ts_code": 1, "auction_pct_chg": 1, "auction_volume": 1, "unmatched_volume": 1}
        )
        
        if not auction_data:
            return universe
        
        auction_map = {x["ts_code"]: x for x in auction_data}
        filtered = []
        
        for ts_code in universe:
            if ts_code not in auction_map:
                continue
            auction = auction_map[ts_code]
            # 竞价过滤规则
            if not (0.5 <= auction["auction_pct_chg"] <= 7):
                continue
            if auction["auction_volume"] <= 0:
                continue
            if auction["unmatched_volume"] <= 0:
                continue
            filtered.append(ts_code)
        
        return filtered
    
    async def _get_stock_details(self, ts_codes: List[str], trade_date: str) -> List[Dict]:
        """获取股票详细信息"""
        from core.managers import mongo_manager
        
        if not ts_codes:
            return []
        
        # 获取日线数据
        daily_data = await mongo_manager.find_many(
            "stock_daily",
            {"ts_code": {"$in": ts_codes}, "trade_date": int(trade_date)},
            projection={"ts_code": 1, "close": 1, "pct_chg": 1, "amount": 1, "volume": 1, "up_limit": 1, "down_limit": 1}
        )
        daily_map = {x["ts_code"]: x for x in daily_data}
        
        # 获取股票名称
        basic_data = await mongo_manager.find_many(
            "stock_basic",
            {"ts_code": {"$in": ts_codes}},
            projection={"ts_code": 1, "name": 1, "industry": 1}
        )
        basic_map = {x["ts_code"]: x for x in basic_data}
        
        # 获取龙虎榜数据
        lhb_data = await mongo_manager.find_many(
            "stock_lhb",
            {"ts_code": {"$in": ts_codes}, "trade_date": int(trade_date)},
            projection={"ts_code": 1, "net_buy_amount": 1, "reason": 1}
        )
        lhb_map = {x["ts_code"]: x for x in lhb_data}
        
        # 合并信息
        details = []
        for ts_code in ts_codes:
            daily = daily_map.get(ts_code, {})
            basic = basic_map.get(ts_code, {})
            lhb = lhb_map.get(ts_code, {})
            
            details.append({
                "ts_code": ts_code,
                "name": basic.get("name", ts_code),
                "industry": basic.get("industry", "未知"),
                "close": daily.get("close", 0),
                "pct_chg": daily.get("pct_chg", 0),
                "amount": daily.get("amount", 0),
                "up_limit": daily.get("up_limit", 0),
                "down_limit": daily.get("down_limit", 0),
                "has_lhb": ts_code in lhb_map,
                "lhb_net_buy": lhb.get("net_buy_amount", 0),
                "lhb_reason": lhb.get("reason", ""),
                "strategy": self._get_strategy_for_stock(ts_code, daily),
            })
        
        return details
    
    def _get_strategy_for_stock(self, ts_code: str, daily_data: Dict) -> str:
        """简单判断股票所属策略"""
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
        """生成交易计划"""
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
            stop_loss_price = buy_price * (1 - self.config["stop_loss_pct"] * sentiment_info["stop_loss_adjust"])
            take_profit_price = buy_price * (1 + self.config["take_profit_pct"] * sentiment_info["take_profit_adjust"])
            
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
        """获取最近一个交易日"""
        now = datetime.now()
        # 简单处理，实际可调用交易日历接口
        if now.weekday() >= 5:  # 周末
            offset = now.weekday() - 4
            latest = now - timedelta(days=offset)
        else:
            latest = now if now.hour >= 15 else now - timedelta(days=1)
        return latest.strftime("%Y%m%d")


async def main():
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
        print(f"✅ 信号已保存到：{args.output}")
    else:
        print("\n" + "="*50)
        print(signals["trading_plan"])
        print("="*50)

if __name__ == "__main__":
    asyncio.run(main())
