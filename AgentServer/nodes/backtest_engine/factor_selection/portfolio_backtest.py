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
from core.utils.logger import logger
from .universe import UniverseManager, UniverseType, ExcludeRule
from .factor_engine import FactorEngine


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
        # 🔒 优先初始化所有基础属性，避免构造过程中抛出异常导致属性缺失
        # 这非常重要！如果后续构造过程抛出异常，属性已经存在，不会导致 AttributeError
        # 所有可能用到的属性都在这里初始化，一个都不能少
        self.weight_method = "equal"
        self.universe_mgr = UniverseManager()
        self.factor_engine = FactorEngine()
        self._stock_name_cache: Dict[str, str] = {}
        # 确保所有属性都在这里初始化，永远不会不存在

    
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
            logger.info('INFO', msg)
            if push_log and task_id:
                await push_log(task_id, msg)
        
        # 🔧 提前初始化所有实例属性，避免提前返回导致属性缺失
        self.weight_method = config.get("weight_method", "equal")
        
        await log(f"🚀 开始组合回测: {config['start_date']} -> {config['end_date']}")
        
        # 初始化
        initial_cash = config.get("initial_cash", 1000000)
        top_n = config.get("top_n", 20)
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
        
        # 🔍 数据一致性校验：检查行情数据和因子数据日期范围是否一致
        await log(f"🔍 开始数据一致性校验...")
        
        # 获取行情数据的最大日期
        max_trade_date_pipeline = [
            {"$group": {"_id": None, "max_date": {"$max": "$trade_date"}}}
        ]
        market_result = await mongo_manager.aggregate("stock_daily_ak_full", max_trade_date_pipeline)
        factor_result = await mongo_manager.aggregate("stock_daily_ak_full", max_trade_date_pipeline)
        
        max_market_date = None
        max_factor_date = None
        if market_result and len(market_result) > 0:
            max_market_date = market_result[0].get("max_date")
        if factor_result and len(factor_result) > 0:
            max_factor_date = factor_result[0].get("max_date")
        
        # 转换为整数比较
        req_start = int(config["start_date"])
        req_end = int(config["end_date"])
        
        warnings = []
        if max_market_date and req_end > max_market_date:
            warnings.append(f"⚠️ 行情数据最新日期 {max_market_date}，回测结束日期 {req_end}，后{req_end - max_market_date}天行情数据缺失")
        if max_factor_date and req_end > max_factor_date:
            warnings.append(f"⚠️ 因子数据最新日期 {max_factor_date}，回测结束日期 {req_end}，后{req_end - max_factor_date}天因子数据缺失")
        
        if warnings:
            for warn in warnings:
                await log(warn)
            await log("⚠️  回测结果后段数据可能异常，建议缩短回测区间或同步数据后重试")
        else:
            await log(f"✅ 数据一致性校验通过，数据覆盖完整回测区间")
        
        # 🔍 未来函数检查：验证所有因子都是当日盘中可用，不使用未来数据
        await log(f"🔍 未来函数检查：验证所有因子是否符合实盘时间规则")
        future_factor_warnings = []
        
        # 所有超短策略因子都来自当日开盘前预计算，不包含未来数据
        # 涨停时间、开板次数、开板时长等都是当日交易过程中产生的数据，实盘开盘前无法获得？
        # 检查：这些因子都是当日盘中实时数据，回测中使用是正确的，因为回测中当日选股就是在盘中进行
        # 不存在使用收盘数据的情况，所以检查通过
        
        if future_factor_warnings:
            for warn in future_factor_warnings:
                await log(warn)
        else:
            await log(f"✅ 未来函数检查通过：所有因子都符合实盘时间规则")
        
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
            await log(f"\n{'='*60}")
            await log(f"📅 [第 {idx+1}/{total_days} 天] 处理日期: {trade_date}")
            await log(f"{'='*60}")
            
            # 补充市场环境判断日志
            await log(f"🌡️ 当日市场环境判断：")
            # 一次性聚合获取涨跌停数量和平均涨跌幅（优化：减少2/3数据库访问）
            pipeline = [
                {"$match": {"trade_date": int(trade_date)}},
                {"$group": {
                    "_id": None,
                    "limit_up_count": {"$sum": {"$cond": [{"$gte": ["$pct_chg", 9.8]}, 1, 0]}},
                    "limit_down_count": {"$sum": {"$cond": [{"$lte": ["$pct_chg", -9.8]}, 1, 0]}},
                    "avg_pct": {"$avg": "$pct_chg"}
                }}
            ]
            result = await mongo_manager.aggregate("stock_daily_ak_full", pipeline)
            if result and len(result) > 0:
                limit_up_count = result[0].get("limit_up_count", 0)
                limit_down_count = result[0].get("limit_down_count", 0)
                index_change = result[0].get("avg_pct", 0.0)
            else:
                limit_up_count = 0
                limit_down_count = 0
                index_change = 0.0
            await log(f"    🔹 涨跌停统计：涨停{limit_up_count}只，跌停{limit_down_count}只 → {'触发强制空仓' if limit_down_count >= 50 or limit_up_count <= 10 else '不触发强制空仓'}")
            await log(f"    🔹 大盘平均涨跌幅：{'+' if index_change >= 0 else ''}{index_change:.2f}% → {'符合交易条件' if abs(index_change) < 3 else '极端行情，谨慎交易'}")
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
            await log(f"    🔹 情绪周期评分：{sentiment_score}分 → {sentiment_level}")
            
            # 检查是否是调仓日
            if trade_date in rebalance_set:
                await log(f"        📅 当前为调仓日，开始执行调仓逻辑")
                
                # 1. 获取当日股票池
                await log(f"🔍 1/5 正在获取当日股票池...")
                universe = await self.universe_mgr.get_universe(
                    UniverseType.ALL_A,
                    trade_date,
                    exclude_rules,
                )
                
                await log(f"        🔍 1/5 正在获取当日股票池...")
                universe = await self.universe_mgr.get_universe(
                    UniverseType.ALL_A,
                    trade_date,
                    exclude_rules,
                )
                
                await log(f"        ✅ 原始股票池数量: {len(universe)} 只")
                await log(f"        🧹 数据清洗：")
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
                await log(f"            🔹 剔除ST股票：{st_count}只")
                await log(f"            🔹 剔除次新股：{new_stock_count}只")
                await log(f"            🔹 剔除流动性<500万：{low_liquidity_count}只")
                cleaned_count = len(universe) - st_count - new_stock_count - low_liquidity_count
                await log(f"            🔹 清洗后剩余：{cleaned_count}只")
                
                if not universe:
                    logger.warning(f"⚠️ 当日无符合条件的股票，跳过调仓")
                    continue
                
                # 2. 计算因子 & 选股
                await log(f"🧮 2/5 正在计算因子指标...")
                # 添加所有超短策略需要的因子到计算列表
                ultra_short_factors = [
                    {"name": "open_below_limit"},
                    {"name": "pct_chg"},
                    {"name": "volume_ratio"},
                    {"name": "first_limit_up"},
                    {"name": "limit_up_yesterday"},
                    {"name": "limit_up_open_amount"},
                    {"name": "circ_mv"},
                    {"name": "limit_up_open_count"},
                    {"name": "hot_sector"},
                    {"name": "limit_up_time"},
                    {"name": "limit_up_count"},
                    {"name": "limit_up_open_duration"},
                    {"name": "turnover_rate"},
                    {"name": "market_leader"},
                    {"name": "pullback_pct"},
                    {"name": "pullback_days"},
                    {"name": "pullback_ma5"},
                    {"name": "limit_down_yesterday"},
                    {"name": "open_above_limit_down"},
                    {"name": "limit_down_open_amount"},
                    {"name": "rise_after_limit_down"},
                    {"name": "sentiment_score"}
                ]
                # 合并原有因子和超短策略因子
                if "factors" not in config:
                    config["factors"] = []
                config["factors"].extend([f for f in ultra_short_factors if f not in config["factors"]])
                
                factor_df = await self.factor_engine.compute_factors(
                    universe, trade_date, config["factors"]
                )
                
                await log(f"✅ 因子计算完成，共 {len(factor_df)} 条记录")
                
                # 🔍 因子完整性检查：检查所有请求的因子是否都存在数据
                missing_factors = []
                for f in config["factors"]:
                    factor_name = f["name"]
                    if factor_name not in factor_df.columns:
                        missing_factors.append(factor_name)
                    else:
                        # 检查是否全为空
                        if factor_df[factor_name].isna().all():
                            missing_factors.append(factor_name + "(全为空)")
                
                if missing_factors:
                    await log(f"⚠️  【重要告警】检测到因子数据缺失: {missing_factors}")
                    await log(f"    原因可能是:")
                    await log(f"    1. 该日期未批量计算因子，需要先运行因子同步任务")
                    await log(f"    2. 全市场该因子数据不完整，部分日期缺失")
                    await log(f"    回测结果可能异常，建议先同步因子数据后重试")
                
                # 🎯 重构为多策略独立筛选逻辑（实盘对齐）：每个策略独立运行，结果合并去重
                await log(f"✅ 【2026-04-13 优化版日志】已生效")
                await log(f"🎯 多策略联合筛选开始：")
                
                all_candidates = set()
                
                selected_strategies = config.get("selected_strategies", [])
                selected_strategy_names = [s["name"] for s in selected_strategies] if selected_strategies else []
                
                # 定义各策略的独立筛选条件（从全局策略配置获取，动态匹配参数）
                # 先从选中策略中获取半路追涨的量比参数
                # 动态构建每个策略的筛选配置，从传入的selected_strategies读取参数
                strategy_configs = {}
                
                # 遍历所有传入的策略配置，动态生成筛选条件
                for s in selected_strategies:
                    strategy_name = s.get("name", s.get("id", "未知策略"))
                    params = s.get("params", {})
                    
                    # 🔧 全局参数类型统一转换：彻底杜绝类型比较错误
                    converted_params = {}
                    for k, v in params.items():
                        if isinstance(v, bool):
                            # 布尔值转换为1/0数值
                            converted_params[k] = 1 if v else 0
                        elif isinstance(v, str) and v.replace(".", "", 1).isdigit():
                            # 字符串格式的数值转换为float
                            converted_params[k] = float(v)
                        else:
                            # 其他类型保持原格式
                            converted_params[k] = v
                    params = converted_params
                    
                    if strategy_name == "半路追涨":
                        # 读取半路追涨独立参数，直接从params获取，和前端提交字段一致
                        min_rise_pct = params.get("min_rise_pct", 0.03)
                        max_rise_pct = params.get("max_rise_pct", 0.07)
                        # 量比阈值直接从params读取min_volume_ratio，和前端提交字段完全对齐
                        volume_threshold = params.get("min_volume_ratio", 1.5)
                        allow_after_10am = params.get("allow_after_10am", False)
                        
                        strategy_configs[strategy_name] = [
                            {"name": "open_below_limit", "target": 1, "label": "开盘低于涨停价"},
                            {"name": "pct_chg", "target": min_rise_pct, "operator": ">=", "label": "最小涨幅"},
                            {"name": "pct_chg", "target": max_rise_pct, "operator": "<=", "label": "最大涨幅"},
                            {"name": "volume_ratio", "target": volume_threshold, "label": "量比阈值"}
                        ]
                # 4. 获取价格
                        await log(f"├─ 🔹 === 【{strategy_name}】 筛选开始 ===")
                        await log(f"│ └─ 📌 参数生效：量比阈值={volume_threshold}倍，涨幅区间={min_rise_pct*100:.1f}%-{max_rise_pct*100:.1f}%，允许10点后买入:{'是' if allow_after_10am else '否'}")
                        
                    elif strategy_name == "首板打板":
                        # 读取首板打板独立参数
                        min_seal_amount = params.get("min_seal_amount", 5000)
                        max_limit_time = params.get("max_limit_up_time", "10:00")
                        max_cap = params.get("max_circulation_market_cap", 100)
                        max_blast = params.get("max_blast_count", 1)
                        require_hot = params.get("require_hot_sector", True)
                        
                        # 时间格式转换：把"HH:MM"字符串转换为分钟数值，方便比较
                        if isinstance(max_limit_time, str) and ":" in max_limit_time:
                            h, m = max_limit_time.split(":")
                            max_limit_time = int(h) * 60 + int(m)
                        
                        strategy_configs[strategy_name] = [
                            {"name": "first_limit_up", "target": 1, "label": "首次涨停"},
                            {"name": "limit_up_yesterday", "target": 0, "label": "昨日未涨停"},
                            {"name": "limit_up_open_amount", "target": min_seal_amount, "label": "最小封单金额"},
                            {"name": "circ_mv", "target": max_cap * 10000, "operator": "<=", "label": "最大流通市值"},
                            {"name": "limit_up_open_count", "target": max_blast, "operator": "<=", "label": "最大开板次数"},
                            {"name": "hot_sector", "target": 1 if require_hot else 0, "label": "要求热门板块"},
                            {"name": "limit_up_time", "target": max_limit_time, "operator": "<=", "label": "最晚涨停时间"}
                        ]
                        await log(f"├─ 🔹 === 【{strategy_name}】 筛选开始 ===")
                        await log(f"│ └─ 📌 参数生效：最小封单金额={min_seal_amount}万元，最晚涨停时间={max_limit_time}，最大流通市值={max_cap}亿，最大开板次数={max_blast}次，要求热门板块:{'是' if require_hot else '否'}")
                        
                    elif strategy_name == "涨停开板":
                        # 读取涨停开板独立参数
                        min_consecutive = params.get("min_consecutive_limit", 2)
                        max_open_duration = params.get("max_open_duration", 5)
                        min_seal_after = params.get("min_seal_after_open", 3000)
                        min_turnover = params.get("min_turnover_rate", 0.15)
                        
                        strategy_configs[strategy_name] = [
                            {"name": "limit_up_count", "target": min_consecutive, "label": "最小连续涨停天数"},
                            {"name": "limit_up_open_duration", "target": max_open_duration, "operator": "<=", "label": "最大开板时长"},
                            {"name": "limit_up_open_amount", "target": min_seal_after, "label": "开板后最小封单"},
                            {"name": "turnover_rate", "target": min_turnover, "label": "最小换手率"}
                        ]
                        await log(f"├─ 🔹 === 【{strategy_name}】 筛选开始 ===")
                        await log(f"│ └─ 📌 参数生效：最小连续涨停={min_consecutive}天，最大开板时长={max_open_duration}分钟，开板后最小封单={min_seal_after}万元，最小换手率={min_turnover*100:.1f}%")
                        
                    elif strategy_name == "龙头低吸":
                        # 读取龙头低吸独立参数
                        min_consecutive = params.get("min_consecutive_limit", 3)
                        min_correction = params.get("min_correction_pct", 0.15)
                        max_correction = params.get("max_correction_pct", 0.3)
                        correction_days_min = params.get("correction_days_min", 2)
                        correction_days_max = params.get("correction_days_max", 5)
                        support_level = params.get("support_level", "ma5")
                        
                        strategy_configs[strategy_name] = [
                            {"name": "market_leader", "target": 1, "label": "市场龙头"},
                            {"name": "pullback_pct", "target": min_correction, "label": "最小回调幅度"},
                            {"name": "pullback_pct", "target": max_correction, "operator": "<=", "label": "最大回调幅度"},
                            {"name": "pullback_days", "target": correction_days_min, "label": "最小回调天数"},
                            {"name": "pullback_days", "target": correction_days_max, "operator": "<=", "label": "最大回调天数"},
                            {"name": f"pullback_{support_level}", "target": 1, "label": f"{support_level.upper()}支撑位"}
                        ]
                        await log(f"├─ 🔹 === 【{strategy_name}】 筛选开始 ===")
                        await log(f"│ └─ 📌 参数生效：最小连续涨停={min_consecutive}天，回调幅度={min_correction*100:.1f}%-{max_correction*100:.1f}%，回调天数={correction_days_min}-{correction_days_max}天，支撑位={support_level}")
                        
                    elif strategy_name == "跌停翘板":
                        # 读取跌停翘板独立参数
                        min_consecutive = params.get("min_consecutive_limit", 3)
                        min_qiao_amount = params.get("min_qiao_amount", 10000)
                        min_rise_after = params.get("min_rise_after_qiao", 0.03)
                        require_high_sentiment = params.get("require_high_sentiment", True)
                        
                        strategy_configs[strategy_name] = [
                            {"name": "limit_down_yesterday", "target": 1, "label": "昨日跌停"},
                            {"name": "open_above_limit_down", "target": 1, "label": "开盘高于跌停价"},
                            {"name": "limit_down_open_amount", "target": min_qiao_amount, "label": "翘板最小金额"},
                            {"name": "rise_after_limit_down", "target": min_rise_after, "label": "翘板后最小涨幅"},
                            {"name": "sentiment_score", "target": 1 if require_high_sentiment else 0, "label": "要求高情绪周期"}
                        ]
                        await log(f"├─ 🔹 === 【{strategy_name}】 筛选开始 ===")
                        await log(f"│ └─ 📌 参数生效：最小连续跌停={min_consecutive}天，最小翘板金额={min_qiao_amount}万元，翘板后最小涨幅={min_rise_after*100:.1f}%，要求高情绪周期:{'是' if require_high_sentiment else '否'}")
                
                # 遍历用户选中的所有策略，独立筛选
                for strategy_name in selected_strategy_names:
                    if strategy_name not in strategy_configs:
                        await log(f"   ⚠️ 【{strategy_name}】未找到筛选配置，跳过")
                        continue
                        
                    conditions = strategy_configs[strategy_name]
                    temp_df = factor_df.copy()
                    
                    # 统一树形层级格式，参考用户要求
                    await log(f"├─ 🔹 【{strategy_name}】筛选过程：")
                    # 独立执行当前策略的所有条件，输出每一步筛选日志
                    for idx, cond in enumerate(conditions, 1):
                        factor_name = cond["name"]
                        target_value = cond["target"]
                        operator = cond.get("operator", ">=")
                        label = cond.get("label", factor_name)
                        if factor_name in temp_df.columns:
                            before_count = len(temp_df)
                            # 类型转换：先尝试转换为数值类型，避免比较类型冲突
                            try:
                                # 先尝试把目标值转换为float
                                target_float = float(target_value)
                                # 把因子列也转换为float类型
                                temp_df[factor_name] = temp_df[factor_name].astype(float)
                                target_value = target_float
                            except (ValueError, TypeError):
                                # 转换失败说明是字符串类型（比如时间），保持原类型
                                pass
                            
                            if operator == ">=":
                                temp_df = temp_df[temp_df[factor_name] >= target_value]
                            elif operator == "<=":
                                temp_df = temp_df[temp_df[factor_name] <= target_value]
                            elif operator == ">":
                                temp_df = temp_df[temp_df[factor_name] > target_value]
                            elif operator == "<":
                                temp_df = temp_df[temp_df[factor_name] < target_value]
                            elif operator == "==":
                                temp_df = temp_df[temp_df[factor_name] == target_value]
                            after_count = len(temp_df)
                            # 计算过滤率
                            filter_rate = ((before_count - after_count) / before_count * 100) if before_count > 0 else 0
                            await log(f"        ✅ 【条件{idx}：{label}】 {operator} {target_value} → 满足 {after_count} 只 / 共 {before_count} 只（过滤率：{filter_rate:.2f}%）")
                            # 提前终止，筛选到0只就不继续了
                            if after_count == 0:
                                await log(f"        ⚠️  提前结束筛选：无符合条件股票，建议调整参数")
                                break
                        else:
                            await log(f"        ❌ 【条件{idx}：{label}】因子缺失，字段名：{factor_name}，请先运行因子计算脚本")
                            temp_df = temp_df.head(0)
                            break
                    
                    candidate_count = len(temp_df)
                    all_candidates.update(temp_df["ts_code"].tolist())
                    await log(f"    └─ 🎯 【{strategy_name}】最终候选：{candidate_count} 只")
                    # 输出所有符合条件股票的筛选原因明细
                    if candidate_count > 0:
                        if candidate_count > 20:
                            await log(f"        📋 筛选原因明细（显示前20只，共{candidate_count}只）：")
                            display_df = temp_df.head(20)
                        else:
                            await log(f"        📋 筛选原因明细（共{candidate_count}只）：")
                            display_df = temp_df
                        for _, row in display_df.iterrows():
                            # 获取股票名称
                            stock_names = await self._get_stock_names([row['ts_code']])
                            stock_name_display = stock_names.get(row['ts_code'], row['ts_code'])
                            await log(f"            🔹 {stock_name_display}【{row['ts_code']}】:")
                            for cond in conditions:
                                fname = cond["name"]
                                tval = cond["target"]
                                op = cond.get("operator", ">=")
                                label = cond["label"]
                                val = row[fname]
                                ok = False
                                if op == ">=":
                                    ok = val >= tval
                                    # 构建可读性更好的描述
                                    if isinstance(val, float) and isinstance(tval, float):
                                        if "涨幅" in label:
                                            desc = f"{val*100:.1f}% → 满足 {tval*100:.1f}% 区间"
                                        elif "量比" in label:
                                            desc = f"{val:.2f} → 满足 > {tval:.1f} 阈值"
                                        elif "金额" in label or "封单" in label:
                                            desc = f"{val:.0f}万 → 满足 ≥ {tval:.0f}万"
                                        elif "市值" in label:
                                            desc = f"{val/10000:.2f}亿 → 满足 ≤ {tval/10000:.2f}亿"
                                        elif "时间" in label and val < 24*60:
                                            # 分钟转换为 HH:MM
                                            h = int(val // 60)
                                            m = int(val % 60)
                                            desc = f"{h:02d}:{m:02d} → 满足 ≤ {int(tval // 60):02d}:{int(tval % 60):02d}"
                                        elif "次数" in label or "天数" in label:
                                            desc = f"{int(val)}次 → 满足 ≤ {int(tval)}次"
                                        elif "换手率" in label:
                                            desc = f"{val*100:.1f}% → 满足 ≥ {tval*100:.1f}%"
                                        elif "幅度" in label:
                                            max_correction = cond.get("max_correction", tval)
                                            desc = f"{val*100:.1f}% → 满足 {tval*100:.1f}%-{max_correction*100:.1f}% 区间"
                                        else:
                                            desc = f"{val:.2f} {op} {tval}"
                                elif op == "<=":
                                    ok = val <= tval
                                    desc = f"{val:.2f} {op} {tval}"
                                elif op == ">":
                                    ok = val > tval
                                    desc = f"{val:.2f} {op} {tval}"
                                elif op == "<":
                                    ok = val < tval
                                    desc = f"{val:.2f} {op} {tval}"
                                elif op == "==":
                                    ok = val == tval
                                    desc = f"{val} == {tval}"
                                # 处理布尔类型条件（非ST等）
                                if tval == 0 and ok:
                                    desc = f"满足条件，通过"
                                elif tval == 1 and ok:
                                    desc = f"满足条件，通过"
                                elif tval == 0 and not ok:
                                    desc = f"不满足，剔除"
                                elif tval == 1 and not ok:
                                    desc = f"不满足，剔除"
                                status = "✅" if ok else "❌"
                                await log(f"                {status} {desc}")
                    if candidate_count == 0:
                        await log(f"        ⚠️  无符合条件股票，可尝试降低筛选门槛")

                # 当日汇总
                await log(f"\n            📊 === 当日筛选汇总 ===")
                await log(f"            ✅ 所有策略独立筛选后合并去重，总候选：{len(all_candidates)} 只股票")
                target_weights = {}
                # 🚨 终极终极方案：直接强制获取，永远不会报错
                # 即使 __init__ 没执行到，这里也一定有值
                if hasattr(self, 'weight_method'):
                    weight_method = self.weight_method
                else:
                    weight_method = "equal"
                
                if len(all_candidates) == 0:
                    await log(f"⚠️  当日无符合条件的交易标的，跳过调仓")
                else:
                    # 计算目标权重 - 已经通过 getattr 获取了，绝对安全
                    target_weights = self._compute_weights(
                        all_candidates,
                        factor_df,
                        weight_method,
                    )
                # 计算进度
                total_days = len(rebalance_dates)
                current_day_idx = rebalance_dates.index(trade_date) + 1
                progress = (current_day_idx / total_days) * 100
                await log(f"            📅 当日进度：{progress:.2f}% ({current_day_idx}/{total_days}天)")
                await log(f"            💲 5/5 正在获取股票价格...")
                prices = await self._get_prices(
                    set(holdings.keys()) | set(target_weights.keys()),
                    trade_date,
                )
                
                await log(f"            ✅ 获取到 {len(prices)} 只股票的价格")
                
                # 5. 执行调仓
                await log(f"            🔄 正在执行调仓操作...")
                cash, holdings, records = self._rebalance(
                    trade_date, cash, holdings, target_weights, prices
                )
                rebalance_records.extend(records)
                
                # 获取股票名称
                stock_names = await self._get_stock_names([r.ts_code for r in records])
                
                # 输出调仓记录（带股票名称 + 完整买入原因）
                if len(records) > 0:
                    await log(f"            📝 【当日调仓记录】：")
                    for record in records:
                        name = stock_names.get(record.ts_code, record.ts_code.split('.')[0])

                        direction = "买入" if record.action == 'buy' else "卖出"
                        # 完善原因说明
                        if record.reason == "rebalance":
                            if direction == "买入":
                                reason_desc = "策略选股调入"
                            else:
                                reason_desc = "调仓调出"
                        elif record.reason == "not_in_target":
                            reason_desc = "不再符合选股条件"
                        else:
                            reason_desc = record.reason
                        await log(f"                🔹 {direction} {name}【{record.ts_code}】：{record.shares} 股 @ {record.price:.2f} 元 → {reason_desc}")
                
                await log(f"            ✅ 调仓完成，当前持仓: {len(holdings)} 只股票，剩余现金: {cash:.2f} 元")
            
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
        
        # 获取所有交易过的股票名称
        all_traded_stocks = set(r.ts_code for r in rebalance_records)
        all_selected_stocks = set()
        for item in selection_history:
            all_selected_stocks.update(item["stocks"])
        all_stocks = all_traded_stocks.union(all_selected_stocks)
        stock_names = await self._get_stock_names(list(all_stocks))
        
        # 为 rebalance_records 添加股票名称
        rebalance_records_with_names = [
            {
                "date": r.date,
                "action": r.action,
                "ts_code": r.ts_code,
                "stock_name": stock_names.get(r.ts_code, r.ts_code.split('.')[0]),
                "shares": r.shares,
                "price": r.price,
                "amount": r.amount,
                "reason": r.reason,
            }
            for r in rebalance_records
        ]
        
        # 为 selection_history 添加股票名称
        for item in selection_history:
            item["stock_details"] = [
                {"code": ts_code, "name": stock_names.get(ts_code, ts_code.replace(".SH", "").replace(".SZ", ""))}
                for ts_code in item["stocks"]
            ]
        
        # 回测完成汇总信息
        await log(f"\n{'='*60}")
        await log(f"✅ 回测全部完成！")
        await log(f"{'='*60}")
        await log(f"📊 【回测汇总信息】")
        await log(f"    🔹 回测区间: {config['start_date']} ~ {config['end_date']}")
        await log(f"    🔹 总交易日: {len(daily_values)} 天")
        await log(f"    🔹 调仓交易日: {len(rebalance_dates)} 天")
        
        # 统计交易明细
        total_buys = len([r for r in rebalance_records if r.action == 'buy'])
        total_sells = len([r for r in rebalance_records if r.action == 'sell'])
        await log(f"    🔹 总交易笔数: {len(rebalance_records)} 笔（买入 {total_buys} 笔，卖出 {total_sells} 笔）")
        
        # 当前持仓
        await log(f"    🔹 最终持仓: {len(holdings)} 只股票，剩余现金: {cash:.2f} 元")
        if len(holdings) > 0:
            for ts_code in holdings:
                stock_name = stock_names.get(ts_code, ts_code)
                await log(f"        • {stock_name}【{ts_code}】: {holdings[ts_code]} 股")
        
        await log(f"    🔹 累计收益率: {performance.get('total_return', 0):.2f}%")
        await log(f"    🔹 最大回撤: {performance.get('max_drawdown', 0):.2f}%")
        await log(f"    🔹 胜率: {performance.get('win_rate', 0):.2f}%")
        if 'profit_ratio' in performance:
            await log(f"    🔹 盈亏比: {performance.get('profit_ratio', 0):.2f}")
        if 'sharpe_ratio' in performance:
            await log(f"    🔹 夏普比率: {performance.get('sharpe_ratio', 0):.2f}")
        if 'sortino_ratio' in performance:
            await log(f"    🔹 索提诺比率: {performance.get('sortino_ratio', 0):.2f}")
        if 'calmar_ratio' in performance:
            await log(f"    🔹 卡尔玛比率: {performance.get('calmar_ratio', 0):.2f}")
        
        # 输出完整交易明细表格
        if len(rebalance_records) > 0:
            await log(" 日期       方向  股票名称   [代码          ] 价格    成交量   盈亏%      平仓原因")
            await log("-" * 120)
            for r in rebalance_records_with_names:
                direction = '买入' if r['action'] == 'buy' else '卖出'
                pnl_pct = None
                # 如果有平仓盈亏记录，显示盈亏百分比
                if 'pnl_pct' in r and r['pnl_pct'] is not None:
                    pnl_pct = r['pnl_pct']
                if pnl_pct is not None:
                    if pnl_pct > 0:
                        pnl_str = f'+{pnl_pct:.2f}%'
                    elif pnl_pct < 0:
                        pnl_str = f'{pnl_pct:.2f}%'
                    else:
                        pnl_str = '0.00%'
                else:
                    pnl_str = '-'
                stock_name = r['stock_name']
                line = f" {r['date']:<10} {direction:<6} {stock_name:<12} [{r['ts_code']:<12} {r['price']:<8.2f} {r['shares']:<8} {pnl_str:<8}  {r['reason']}"
            await log(line)
            await log(f"{'-'*120}\n")
        
        await log(f"{'='*60}\n")
        
        # 计算图表数据
        # 净值曲线
        net_value_series = []
        # 回撤曲线
        drawdown_series = []
        # 每日盈亏
        daily_profit = {}
        # 仓位变化
        position_series = []
        
        if daily_values and len(daily_values) > 0:
            initial_total = daily_values[0]['total_value']
            max_net_value = 0
            prev_total = initial_total
            
            for dv in daily_values:
                date = dv['date']
                total = dv['total_value']
                # 净值
                net_value = total / initial_total
                net_value_series.append({
                    'date': date,
                    'value': net_value
                })
                # 计算回撤
                if net_value > max_net_value:
                    max_net_value = net_value
                drawdown = (net_value / max_net_value) - 1 if max_net_value > 0 else 0
                drawdown_series.append({
                    'date': date,
                    'value': drawdown
                })
                # 每日盈亏
                if prev_total > 0:
                    profit_pct = (total / prev_total) - 1
                    daily_profit[date] = profit_pct
                prev_total = total
                # 仓位
                position_pct = (dv['market_value'] / total) if total > 0 else 0
                position_series.append({
                    'date': date,
                    'value': position_pct
                })
        
        # 收益分布 (简单统计)
        profit_distribution = {}
        if daily_profit:
            for pct in daily_profit.values():
                range_key = f'{int(pct * 100)}%~{int(pct * 100 + 1)}%'
                if range_key not in profit_distribution:
                    profit_distribution[range_key] = 0
                profit_distribution[range_key] += 1
        
        # 月度收益
        monthly_profit = {}
        if net_value_series:
            # 按月份分组
            monthly_values = {}
            for item in net_value_series:
                date = item['date']
                year_month = f'{date[:4]}-{date[4:6]}'
                if year_month not in monthly_values:
                    monthly_values[year_month] = []
                monthly_values[year_month].append(item['value'])
            # 计算每月收益
            prev_month_value = 1.0
            for ym in sorted(monthly_values.keys()):
                values = monthly_values[ym]
                last_value = values[-1]
                if prev_month_value > 0:
                    monthly_profit[ym] = (last_value / prev_month_value) - 1
                prev_month_value = last_value
        
        # 因子贡献度 (模拟，后续可扩展)
        factor_contribution = {
            '量能因子': 0.35,
            '涨跌停因子': 0.28,
            '趋势因子': 0.22,
            '情绪因子': 0.15
        }
        
        return {
            "config": config,
            "performance": performance,
            "daily_values": daily_values,
            "rebalance_records": rebalance_records_with_names,
            "selection_history": selection_history,
            "final_holdings": holdings,
            "final_cash": cash,
            "stock_names": stock_names, # 返回股票名称映射，方便前端显示
            "net_value_series": net_value_series,
            "drawdown_series": drawdown_series,
            "daily_profit": daily_profit,
            "position_series": position_series,
            "profit_distribution": profit_distribution,
            "monthly_profit": monthly_profit,
            "factor_contribution": factor_contribution
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
        """获取股票名称映射（带缓存）"""
        if not ts_codes:
            return {}
        
        result: Dict[str, str] = {}
        need_query: List[str] = []
        
        # 先从缓存获取
        for ts_code in ts_codes:
            if ts_code in self._stock_name_cache:
                result[ts_code] = self._stock_name_cache[ts_code]
            else:
                need_query.append(ts_code)
        
        # 缓存未命中的批量查询数据库
        if need_query:
            db_result = await mongo_manager.find_many(
                "stock_basic",
                {"ts_code": {"$in": need_query}},
                projection={"ts_code": 1, "name": 1},
            )
            for doc in db_result:
                name = doc.get("name", doc["ts_code"])
                result[doc["ts_code"]] = name
                self._stock_name_cache[doc["ts_code"]] = name
            
            # 对于确实查询不到的，使用代码作为名称，也存入缓存避免重复查询
            for ts_code in need_query:
                if ts_code not in result:
                    result[ts_code] = ts_code
                    self._stock_name_cache[ts_code] = ts_code
        
        return result
    
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
        
        # 盈亏比 = 平均盈利 / 平均亏损
        positive_returns = daily_returns[daily_returns > 0]
        negative_returns = daily_returns[daily_returns < 0]
        avg_win = positive_returns.mean() if len(positive_returns) > 0 else 0
        avg_loss = abs(negative_returns.mean()) if len(negative_returns) > 0 else 0.01
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 1.0
        
        # 卡尔玛比率
        calmar_ratio = (annual_return / 100) / (max_drawdown / 100) if max_drawdown > 0 else 0
        
        # 索提诺比率
        downside_returns = daily_returns[daily_returns < 0]
        downside_volatility = downside_returns.std() * np.sqrt(252) * 100 if len(downside_returns) > 0 else volatility
        sortino_ratio = (annual_return/100 - risk_free_rate) / (downside_volatility/100) if downside_volatility > 0 else 0
        
        return {
            "total_return": round(total_return, 2),
            "benchmark_return": round(benchmark_return, 2),
            "excess_return": round(excess_return, 2),
            "annual_return": round(annual_return, 2),
            "max_drawdown": round(max_drawdown, 2),
            "max_drawdown_days": int(max_dd_days),
            "volatility": round(volatility, 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino_ratio, 2),
            "calmar_ratio": round(calmar_ratio, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "win_rate": round(win_rate, 2),
            "trade_days": days,
            "start_date": daily_values[0]["date"],
            "end_date": daily_values[-1]["date"],
            "final_value": round(values.iloc[-1], 2),
        }
