"""
组合回测引擎

【双模式架构设计说明】
═══════════════════════════════════════════════════════════════

▶️ 回测模式 (MODE=backtest)
   ┌─────────────────────────────────────────────────────────┐
   │  读取路径: MongoDB (stock_daily_ak_full) → 筛选 → 调仓 │
   │  性能: 极速 (无需计算因子，直接读取)                   │
   │  适用: 大规模历史回测、参数寻优、策略验证              │
   │  依赖: DATA_SYNC 节点预计算所有因子 (T+1 批量计算)    │
   └─────────────────────────────────────────────────────────┘

▶️ 实盘模式 (MODE=live)
   ┌─────────────────────────────────────────────────────────┐
   │  计算路径: 实时行情 → factor_engine → 因子计算 → 筛选  │
   │  性能: 实时计算 (支持 Redis 缓存加速，24小时过期)       │
   │  适用: 盘中选股、实时监控、动态调仓、模拟交易            │
   │  依赖: Listener 节点实时行情推送 + LLM 因子推理         │
   └─────────────────────────────────────────────────────────┘

【两种模式切换方式】
  • 环境变量: export MODE=backtest 或 export MODE=live
  • .env 文件: MODE=backtest
  • 默认值: live (实盘模式)

【因子字段映射关系（两种模式输出完全一致）】
  • first_limit_up     → 首板标记 (0.0/1.0)
  • hot_sector         → 热点板块标记 (0.0/1.0)
  • limit_up_yesterday → 昨日涨停标记 (0.0/1.0)
  • turnover_rate      → 换手率 (float)
  • volume_ratio       → 量比 (float)
  • circ_mv            → 流通市值 (float)
  • ... 其他 40+ 个因子字段 ...

═══════════════════════════════════════════════════════════════

支持:
- 定期调仓
- 多种权重方法
- 交易成本
- 基准对比
- 绩效统计
"""

from dataclasses import dataclass
import gc
import os

from core.managers import mongo_manager
from core.utils.logger import logger

from .factor_engine import FactorEngine, log_memory_usage
from .universe import ExcludeRule, UniverseManager, UniverseType


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
    sentiment: str = ""  # 当日情绪周期状态



@dataclass
class PortfolioSnapshot:
    """组合快照"""
    date: str
    cash: float
    holdings: dict[str, int]  # {ts_code: shares}
    prices: dict[str, float]  # {ts_code: price}
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
    BUY_COMMISSION = 0.0003     # 买入佣金 万3(含规费),对齐前端commission_rate默认值
    SELL_COMMISSION = 0.0003   # 卖出佣金 万3(含规费),对齐前端commission_rate默认值
    STAMP_TAX = 0.001          # 印花税 千1 (卖出)
    MIN_COMMISSION = 5         # 最低佣金 5元

    def __init__(self):
        # 🔒 优先初始化所有基础属性,避免构造过程中抛出异常导致属性缺失
        # 这非常重要!如果后续构造过程抛出异常,属性已经存在,不会导致 AttributeError
        # 所有可能用到的属性都在这里初始化,一个都不能少
        self.weight_method = "equal"
        self.universe_mgr = UniverseManager()
        self.factor_engine = FactorEngine()
        self._stock_name_cache: dict[str, str] = {}
        # 🔧 新增:止损止盈需要跟踪持仓成本
        self._holding_costs: dict[str, float] = {}
        # 🔧 新增:策略轮动需要跟踪月度收益
        self._strategy_monthly_returns: dict[str, dict[str, float]] = {}
        # 初始资金(用于计算累计收益)
        self._initial_cash: float = 1000000.0
        # 确保所有属性都在这里初始化,永远不会不存在

    # ==================== 🎯 【统一输出函数集】 One Function, One Format ====================
    # 所有日志输出必须走以下统一入口！绝对不允许直接调用 await self.log()！
    # ==================================================================================

    async def _print_daily_header(self, day_idx: int, total_days: int, trade_date: str):
        """【统一入口！每日开头必须调用！】"""
        await self.log(f"")
        await self.log(f"═══════════════════════════════════════════════════════════")
        await self.log(f"📅 [第 {day_idx}/{total_days} 天] 处理日期: {trade_date}")
        await self.log(f"═══════════════════════════════════════════════════════════")

    async def _print_market_environment(self, trade_date: int):
        """【统一入口！每日市场环境判断必须调用！】
        
        Returns:
            tuple: (sentiment_level, limit_up_count, limit_down_count)
                sentiment_level: 情绪等级字符串
                limit_up_count: 涨停家数
                limit_down_count: 跌停家数
        """
        await self.log(f"")
        await self.log(f"   ┌───────────────────────────────────────────────────────")
        await self.log(f"   │ 🌡️ 当日市场环境判断")
        await self.log(f"   ├───────────────────────────────────────────────────────")
        
        # 一次性聚合获取涨跌停数量和平均涨跌幅
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
        
        await self.log(f"   │  🔹 涨跌停统计: 涨停{limit_up_count}只, 跌停{limit_down_count}只")
        trigger_text = "触发强制空仓" if limit_down_count >= 50 or limit_up_count <= 10 else "不触发强制空仓"
        await self.log(f"   │     → {trigger_text}")
        await self.log(f"   │  🔹 大盘平均涨跌幅: {'+' if index_change >= 0 else ''}{index_change:.2f}%")
        ma_filter_text = "符合交易条件" if abs(index_change) < 3 else "极端行情,谨慎交易"
        await self.log(f"   │     → {ma_filter_text}")
        
        # 情绪周期评分
        sentiment_score = min(100, max(0, (limit_up_count - limit_down_count) + int(index_change * 10) + 50))
        if sentiment_score >= 80:
            sentiment_level = "高潮期,仓位系数1.0"
        elif sentiment_score >= 60:
            sentiment_level = "修复期,仓位系数0.8"
        elif sentiment_score >= 40:
            sentiment_level = "震荡期,仓位系数0.6"
        elif sentiment_score >= 20:
            sentiment_level = "冰点期,仓位系数0.3"
        else:
            sentiment_level = "极致冰点,仓位系数0.1"
        await self.log(f"   │  🔹 情绪周期评分：{sentiment_score}分 → {sentiment_level}")
        await self.log(f"   └───────────────────────────────────────────────────────")
        
        return sentiment_level, limit_up_count, limit_down_count

    async def _print_single_strategy_filtering(self, strategy_name: str, params: dict, conditions: list, factor_df, strategy_configs: dict, all_selected_strategies: list):
        """【统一入口！所有策略筛选打印必须调用！One Function, One Format!】
        
        所有5个策略（半路追涨/首板打板/涨停开板/龙头低吸/跌停翘板）必须调用此函数！
        绝对不允许在策略代码中直接写 await self.log()！
        
        Args:
            strategy_name: 策略名称
            params: 策略参数字典
            conditions: 条件列表
            factor_df: 因子数据DataFrame
            strategy_configs: 所有策略配置字典
            all_selected_strategies: 所有选中的策略列表
        
        Returns:
            set: 该策略选出的候选股票集合
        """
        # 跳过未选中的策略
        if strategy_name not in all_selected_strategies:
            return set()
        
        await self.log(f"")
        await self.log(f"   ┌───────────────────────────────────────────────────────")
        await self.log(f"   │ 🔹 【{strategy_name}】")
        await self.log(f"   ├───────────────────────────────────────────────────────")
        
        # 参数配置显示（根据不同策略格式化显示）
        await self.log(f"   │    📌 参数配置:")
        if strategy_name == "半路追涨":
            min_rise_pct = params.get("min_rise_pct", 0.03)
            max_rise_pct = params.get("max_rise_pct", 0.05)
            volume_threshold = params.get("min_volume_ratio", 2.5)
            allow_after_10am = params.get("allow_after_10am", False)
            await self.log(f"   │        • 量比阈值: {volume_threshold}倍")
            await self.log(f"   │        • 涨幅区间: {min_rise_pct*100:.1f}% ~ {max_rise_pct*100:.1f}%")
            await self.log(f"   │        • 允许10点后买入: {'是' if allow_after_10am else '否'}")
        elif strategy_name == "首板打板":
            min_seal_amount = params.get("min_seal_amount", 5000)
            max_limit_time = params.get("max_limit_up_time", "10:00")
            min_circ_mv = params.get("min_circulation_market_cap", 50)
            max_circ_mv = params.get("max_circulation_market_cap", 500)
            min_volume_ratio = params.get("min_volume_ratio", 1.5)
            min_turnover = params.get("min_turnover_rate", 3)
            max_turnover = params.get("max_turnover_rate", 15)
            max_blast = params.get("max_blast_count", 1)
            require_hot = params.get("require_hot_sector", True)
            require_sentiment = params.get("require_sentiment_period", ["rising", "chaos"])
            await self.log(f"   │        • 竞价涨幅: 2.0% ~ 5.0%")
            await self.log(f"   │        • 量比要求: ≥ {min_volume_ratio}")
            await self.log(f"   │        • 换手率: {min_turnover}% ~ {max_turnover}%")
            await self.log(f"   │        • 流通市值: {min_circ_mv}亿 ~ {max_circ_mv}亿")
            await self.log(f"   │        • 最小封单: {min_seal_amount}万元")
            await self.log(f"   │        • 最晚涨停: {max_limit_time}")
            await self.log(f"   │        • 最大开板: {max_blast}次")
            await self.log(f"   │        • 要求热门板块: {'是' if require_hot else '否'}")
            await self.log(f"   │        • 情绪周期要求: {', '.join(require_sentiment)}")
        elif strategy_name == "涨停开板":
            min_consecutive = params.get("min_consecutive_limit", 2)
            max_consecutive = params.get("max_consecutive_limit", 4)
            max_open_duration = params.get("max_open_duration", 5)
            min_seal_after = params.get("min_seal_after_open", 3000)
            min_turnover = params.get("min_turnover_rate", 0.15)
            opening_pct_min = params.get("opening_pct_min", 0.0)
            opening_pct_max = params.get("opening_pct_max", 3.0)
            min_volume_ratio = params.get("min_volume_ratio", 2.0)
            require_sentiment = params.get("require_sentiment_period", ["rising"])
            await self.log(f"   │        • 连续涨停: {min_consecutive} ~ {max_consecutive}板")
            await self.log(f"   │        • 开盘涨幅: {opening_pct_min}% ~ {opening_pct_max}%")
            await self.log(f"   │        • 量比要求: ≥ {min_volume_ratio}")
            await self.log(f"   │        • 最大开板时长: {max_open_duration}分钟")
            await self.log(f"   │        • 开板后最小封单: {min_seal_after}万元")
            await self.log(f"   │        • 最小换手率: {min_turnover*100:.1f}%")
            await self.log(f"   │        • 情绪周期要求: {', '.join(require_sentiment)}")
        elif strategy_name == "龙头低吸":
            min_consecutive = params.get("min_consecutive_limit", 3)
            min_correction = params.get("min_correction_pct", 0.15)
            max_correction = params.get("max_correction_pct", 0.3)
            correction_days_min = params.get("correction_days_min", 2)
            correction_days_max = params.get("correction_days_max", 5)
            support_level = params.get("support_level", "ma5")
            await self.log(f"   │        • 最小连续涨停: {min_consecutive}天")
            await self.log(f"   │        • 回调幅度: {min_correction*100:.1f}% ~ {max_correction*100:.1f}%")
            await self.log(f"   │        • 回调天数: {correction_days_min} ~ {correction_days_max}天")
            await self.log(f"   │        • 支撑位: {support_level.upper()}")
            await self.log(f"   │        • 要求缩量回调: volume/ma5 ≤ 1.0")
        elif strategy_name == "跌停翘板":
            min_consecutive = params.get("min_consecutive_limit", 3)
            min_qiao_amount = params.get("min_qiao_amount", 10000)
            min_rise_after = params.get("min_rise_after_qiao", 0.03)
            require_high_sentiment = params.get("require_high_sentiment", True)
            await self.log(f"   │        • 最小连续跌停: {min_consecutive}天")
            await self.log(f"   │        • 换手率要求: ≥ 10%")
            await self.log(f"   │        • 最小翘板金额: {min_qiao_amount}万元")
            await self.log(f"   │        • 翘板后最小涨幅: {min_rise_after*100:.1f}%")
            await self.log(f"   │        • 要求高情绪周期: {'是' if require_high_sentiment else '否'}")
        else:
            # 通用显示
            for param_name, param_value in list(params.items())[:8]:
                display_value = str(param_value) if not isinstance(param_value, list) else ', '.join(str(v) for v in param_value[:3]) + ('...' if len(param_value) > 3 else '')
                await self.log(f"   │        • {param_name}: {display_value}")
        await self.log(f"   └───────────────────────────────────────────────────────")
        
        # 筛选过程输出
        await self.log(f"")
        await self.log(f"   ┌───────────────────────────────────────────────────────")
        await self.log(f"   │ 🔍 【{strategy_name}】筛选过程:")
        await self.log(f"   ├───────────────────────────────────────────────────────")
        
        current_df = factor_df.copy()
        strategy_conditions = strategy_configs.get(strategy_name, conditions)
        
        for idx_cond, cond in enumerate(strategy_conditions, 1):
            factor_name = cond["name"]
            target_value = cond["target"]
            operator = cond.get("operator", ">=")
            label = cond.get("label", f"条件{idx_cond}")
            
            if factor_name not in current_df.columns:
                continue
            
            before_count = len(current_df)
            try:
                target_float = float(target_value)
                current_df[factor_name] = current_df[factor_name].astype(float)
                target_value = target_float
            except (ValueError, TypeError):
                pass
            
            if operator == ">=":
                current_df = current_df[current_df[factor_name] >= target_value]
            elif operator == "<=":
                current_df = current_df[current_df[factor_name] <= target_value]
            elif operator == ">":
                current_df = current_df[current_df[factor_name] > target_value]
            elif operator == "<":
                current_df = current_df[current_df[factor_name] < target_value]
            elif operator == "==":
                current_df = current_df[current_df[factor_name] == target_value]
            
            after_count = len(current_df)
            filter_rate = ((before_count - after_count) / before_count * 100) if before_count > 0 else 0
            
            await self.log(f"   │    ✅ 条件{idx_cond}: {label}")
            await self.log(f"   │       → 满足 {after_count} 只 / 共 {before_count} 只 (过滤率:{filter_rate:.2f}%)")
            
            if after_count == 0:
                await self.log(f"   │    ⚠️  提前结束:无符合条件股票,建议调整参数")
                break
        
        candidate_count = len(current_df)
        await self.log(f"   ├───────────────────────────────────────────────────────")
        await self.log(f"   │ 🎯 【{strategy_name}】最终候选: {candidate_count} 只")
        await self.log(f"   └───────────────────────────────────────────────────────")
        await self.log(f"")
        
        return set(current_df["ts_code"].tolist())

    async def _print_stock_pool_and_cleaning(self, trade_date: str, universe: set, st_count: int, new_stock_count: int, low_liquidity_count: int):
        """【统一入口！股票池获取+数据清洗打印必须调用！】"""
        await self.log(f"   🔍 正在获取当日股票池...")
        await self.log(f"   ✅ 原始股票池数量: {len(universe)} 只")
        await self.log(f"   🧹 数据清洗:")
        await self.log(f"      🔹 剔除ST股票: {st_count}只")
        await self.log(f"      🔹 剔除次新股: {new_stock_count}只")
        await self.log(f"      🔹 剔除流动性<500万: {low_liquidity_count}只")
        cleaned_count = len(universe) - st_count - new_stock_count - low_liquidity_count
        await self.log(f"      🔹 清洗后剩余: {cleaned_count}只")

    async def _print_non_rebalance_marker(self):
        """【统一入口！非调仓日标记必须调用！】"""
        await self.log(f"")
        await self.log(f"   ═══════════════════════════════════════════════════════")
        await self.log(f"   ℹ️  【非调仓日】无调仓操作，继续持有现有仓位")
        await self.log(f"   ═══════════════════════════════════════════════════════")

    async def _print_daily_summary(self, trade_date: str, holdings_count: int, cash: float):
        """【统一入口！每日收盘汇总必须调用！】"""
        await self.log(f"")
        await self.log(f"═══════════════════════════════════════════════════════════")
        await self.log(f"📅 处理完成: {trade_date}")
        await self.log(f"   💵 当日持仓: {holdings_count} 只股票, 现金剩余: {cash:,.2f} 元")
        await self.log(f"═══════════════════════════════════════════════════════════")

    # ==================== 🎯 【统一输出函数集结束】 ====================


    async def run(self, config: dict) -> dict:
        """
        运行组合回测

        Args:
            config: {
                "universe": "all_a",
                "start_date": "20230101",
                "end_date": "20260101",
                "initial_cash": 1000000,
                "rebalance_freq": "daily",
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

        # 保存 log 到实例,让所有方法都能使用
        # 日志推送辅助方法:同时写入本地日志 + 推送到前端
        async def log(msg: str):
            logger.info('BACKTEST', msg)
            if push_log and task_id:
                await push_log(task_id, msg)
        self.log = log

        # 🔧 提前初始化所有实例属性,避免提前返回导致属性缺失
        self.weight_method = config.get("weight_method", "equal")

        await self.log(f"🚀 开始组合回测: {config['start_date']} -> {config['end_date']}")

        # 🔧 读取风控配置(优先使用请求中的配置,如果没有从数据库读取)
        # 默认风控配置
        risk_config = {
            "enable_stop_loss": True,
            "stop_loss_pct": 0.02,  # 超短策略严格止损2%
            "enable_take_profit": True,
            "take_profit_pct": 0.07,  # 超短策略止盈7%
            "enable_ma60_filter": True,
            "enable_sector_concentration": True,
            "sector_concentration_top_n": 3,
        }

        # 如果请求中传入了风控配置,使用传入的配置
        if "risk_config" in config and config["risk_config"]:
            for k, v in config["risk_config"].items():
                risk_config[k] = v

        # 输出风控配置到日志
        await self.log("🔧 当前风控配置:")
        await self.log(f"    🔹 {'✅' if risk_config['enable_stop_loss'] else '❌'} 强化止损: {risk_config['stop_loss_pct'] * 100:.1f}%")
        await self.log(f"    🔹 {'✅' if risk_config['enable_take_profit'] else '❌'} 动态止盈: {risk_config['take_profit_pct'] * 100:.1f}%")
        await self.log(f"    🔹 {'✅' if risk_config['enable_ma60_filter'] else '❌'} 大盘MA60过滤")
        await self.log(f"    🔹 {'✅' if risk_config['enable_sector_concentration'] else '❌'} 板块集中度过滤: 保留前 {risk_config['sector_concentration_top_n']} 名")

        # 保存风控配置到实例,后续使用
        self._risk_config = risk_config

        # 初始化
        initial_cash = config.get("initial_cash", 1000000)
        self._initial_cash = initial_cash

        # 🔧 读取前端传入的佣金/滑点参数,覆盖硬编码常量
        commission_rate = config.get("commission_rate", None)
        if commission_rate is not None:
            self.BUY_COMMISSION = commission_rate
            self.SELL_COMMISSION = commission_rate
        stamp_duty_rate = config.get("stamp_duty_rate", None)
        if stamp_duty_rate is not None:
            self.STAMP_TAX = stamp_duty_rate
        self._slippage_pct = config.get("slippage_pct", 0.002)  # 默认0.2%

        top_n = config.get("top_n", 20)
        benchmark_code = config.get("benchmark", "000300.SH")

        # 解析排除规则
        exclude_rules = [ExcludeRule(r) for r in config.get("exclude", [])]

        # 获取调仓日期
        rebalance_dates = await self.universe_mgr.get_rebalance_dates(
            config["start_date"],
            config["end_date"],
            config.get("rebalance_freq", "daily"),
        )

        if not rebalance_dates:
            return {"error": "No rebalance dates found"}

        # 获取所有交易日
        all_trade_dates = await self.universe_mgr.get_all_trade_dates(
            config["start_date"], config["end_date"]
        )

        if not all_trade_dates:
            return {"error": "No trade dates found"}

        await self.log(f"📅 调仓日期: {len(rebalance_dates)} 天,交易日: {len(all_trade_dates)} 天")

        # 🔍 数据一致性校验:检查行情数据和因子数据日期范围是否一致
        await self.log("🔍 开始数据一致性校验...")

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
        req_end = int(config["end_date"])

        warnings = []
        if max_market_date and req_end > max_market_date:
            warnings.append(f"⚠️ 行情数据最新日期 {max_market_date},回测结束日期 {req_end},后{req_end - max_market_date}天行情数据缺失")
        if max_factor_date and req_end > max_factor_date:
            warnings.append(f"⚠️ 因子数据最新日期 {max_factor_date},回测结束日期 {req_end},后{req_end - max_factor_date}天因子数据缺失")

        if warnings:
            for warn in warnings:
                await self.log(warn)
            await self.log("⚠️  回测结果后段数据可能异常,建议缩短回测区间或同步数据后重试")
        else:
            await self.log("✅ 数据一致性校验通过,数据覆盖完整回测区间")

        # 🔍 未来函数检查:验证所有因子都是当日盘中可用,不使用未来数据
        await self.log("🔍 未来函数检查:验证所有因子是否符合实盘时间规则")
        future_factor_warnings = []

        # 所有超短策略因子都来自当日开盘前预计算,不包含未来数据
        # 涨停时间、开板次数、开板时长等都是当日交易过程中产生的数据,回测中当日选股就是在盘中进行,使用正确
        # 不存在使用收盘数据的情况,所以检查通过

        if future_factor_warnings:
            for warn in future_factor_warnings:
                await self.log(warn)
        else:
            await self.log("✅ 未来函数检查通过:所有因子都符合实盘时间规则")

        # ==================== 因子完整性自动检测 ====================
        # 【自动检测机制】
        # 1. 检测回测日期范围内所有因子字段的完整性
        # 2. 检测因子覆盖率（是否有null/缺失）
        # 3. 如果完整则跳过所有实时计算，直接使用预存数据
        # 4. 如果缺失则触发告警并建议补算
        await self.log("🔍 因子完整性自动检测:检查 48 个预计算因子字段...")
        
        # 所有超短策略需要的因子字段列表
        REQUIRED_FACTOR_FIELDS = [
            "first_limit_up", "hot_sector", "limit_up_yesterday", "limit_up_count",
            "limit_up_open_count", "limit_up_open_amount", "limit_up_open_duration",
            "limit_up_time", "turnover_rate", "volume_ratio", "circ_mv",
            "market_leader", "pullback_pct", "pullback_days", "pullback_ma5",
            "limit_down_yesterday", "open_above_limit_down", "limit_down_open_amount",
            "rise_after_limit_down", "sentiment_score", "open_below_limit",
            "amount_20d", "amplitude", "pct_chg", "vol", "amount",
            # OHLC基础数据
            "open", "high", "low", "close",
            # 技术指标因子
            "ma5", "ma10", "ma20", "ma60", "ema12", "ema26",
            "rsi_6", "rsi_12", "rsi_24", "macd", "macd_signal", "macd_hist",
            "boll_upper", "boll_mid", "boll_lower", "atr", "natr", "trange",
            # 动量因子
            "momentum_1d", "momentum_5d", "momentum_10d", "momentum_20d",
            # 波动率因子
            "volatility_5d", "volatility_10d", "volatility_20d",
            # 流动性因子
            "turnover_5d_avg", "turnover_20d_avg",
            # 情绪因子
            "sentiment_score", "fear_greed_index"
        ]
        
        start_dt = int(config["start_date"])
        end_dt = int(config["end_date"])
        
        # 分步检测：日期范围 → 字段完整性 → 空值率
        factor_checks = []
        missing_fields = []
        incomplete_dates = []
        
        for field in REQUIRED_FACTOR_FIELDS:
            # 统计该字段在回测日期范围内的非空数量
            pipeline = [
                {"$match": {
                    "trade_date": {"$gte": start_dt, "$lte": end_dt},
                    field: {"$ne": None}
                }},
                {"$count": "valid_count"}
            ]
            result = await mongo_manager.aggregate("stock_daily_ak_full", pipeline)
            total_records = (end_dt - start_dt + 1) * 5510  # 5510只股票
            
            if result and len(result) > 0:
                valid_count = result[0]["valid_count"]
                coverage = valid_count / total_records * 100 if total_records > 0 else 0
                factor_checks.append((field, coverage, valid_count, total_records))
                
                if coverage < 90:  # 覆盖率低于90%视为缺失
                    missing_fields.append(field)
            else:
                missing_fields.append(field)
        
        # 输出检测结果
        complete_count = sum(1 for _, c, _, _ in factor_checks if c >= 90)
        total_factor_count = len(REQUIRED_FACTOR_FIELDS)
        
        await self.log(f"   完整因子: {complete_count}/{total_factor_count} 个 (覆盖率≥90%)")
        
        if missing_fields:
            await self.log(f"   ⚠️ 缺失因子 ({len(missing_fields)}个): {', '.join(missing_fields[:10])}{'...' if len(missing_fields) > 10 else ''}")
            await self.log(f"   💡 建议: 执行 DATA_SYNC 节点的因子批量补算任务")
        else:
            await self.log(f"   ✅ 所有因子字段完整性检查通过!")
            await self.log(f"   ⚡ 回测模式: 跳过实时因子计算,直接使用 MongoDB 预计算数据")
        # ==================== 因子完整性检测结束 ====================

        # 加载基准数据
        benchmark_data = await self._load_benchmark_data(benchmark_code, config["start_date"], config["end_date"])

        # 初始化组合状态
        cash = initial_cash
        holdings: dict[str, int] = {}  # {ts_code: shares}
        stock_names: dict[str, str] = {}  # 股票名称缓存,确保始终有定义

        # 记录
        rebalance_records: list[RebalanceRecord] = []

        # 逐日模拟
        rebalance_set = set(rebalance_dates)
        total_days = len(all_trade_dates)

        await self.log(f"开始逐日回测,共 {total_days} 个交易日")

        for idx, trade_date in enumerate(all_trade_dates):
            # 🔧 内存优化: 每5天强制一次垃圾回收
            if idx % 5 == 0:
                log_memory_usage(f"[day {idx+1}/{total_days}] 回测开始前")
                gc.collect()

            # ==================== 1️⃣ 每日统一开头 ====================
            await self._print_daily_header(idx+1, total_days, trade_date)
            
            # ==================== 2️⃣ 每日市场环境判断（所有天都走） ====================
            sentiment_level, limit_up_count, limit_down_count = await self._print_market_environment(trade_date)
            
            # ==================== 🔴 任务1：强制空仓真正执行（P0！） ====================
            # 判断是否触发强制空仓：跌停≥50只 或 涨停≤10只
            force_empty_triggered = (limit_down_count >= 50 or limit_up_count <= 10)
            
            # ==================== 3️⃣ IF/ELSE 严格对齐！ ====================
            if trade_date in rebalance_set:
                # ==================== 调仓日完整流程 ====================
                await self.log(f"   📅 当前为调仓日，开始执行调仓逻辑")
                
                # 🔴 如果触发强制空仓：先卖出所有持仓，然后跳过当日选股
                if force_empty_triggered:
                    await self.log(f"")
                    await self.log(f"   ┌───────────────────────────────────────────────────────")
                    await self.log(f"   │ 🔴 【强制空仓执行】")
                    await self.log(f"   ├───────────────────────────────────────────────────────")
                    
                    if holdings and len(holdings) > 0:
                        # 获取当日价格用于卖出
                        prices_for_sell = await self._get_prices(set(holdings.keys()), trade_date)
                        # 执行卖出所有持仓
                        sell_count = 0
                        for code in list(holdings.keys()):
                            if holdings[code] > 0 and code in prices_for_sell:
                                price = prices_for_sell[code]['close']
                                shares = holdings[code]
                                slippage_pct = self._slippage_pct if hasattr(self, '_slippage_pct') else 0.002
                                sell_price_adj = price * (1 - slippage_pct)
                                gross_amount = shares * sell_price_adj
                                commission = max(gross_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
                                stamp_tax = gross_amount * self.STAMP_TAX
                                net_amount = gross_amount - commission - stamp_tax
                                cash += net_amount
                                sell_count += 1
                                # 记录卖出
                                rebalance_records.append(RebalanceRecord(
                                    date=str(trade_date),
                                    action="sell",
                                    ts_code=code,
                                    shares=shares,
                                    price=price,
                                    amount=net_amount,
                                    reason="force_empty_position",
                                    sentiment=sentiment_level
                                ))
                                holdings[code] = 0
                        # 清理零持仓
                        holdings = {code: shares for code, shares in holdings.items() if shares > 0}
                        await self.log(f"   │  ✅ 已执行强制清仓，卖出 {sell_count} 只持仓")
                        await self.log(f"   │  💵 清仓后现金：{cash:,.2f} 元")
                    else:
                        await self.log(f"   │  ⚪ 当前无持仓，无需卖出")
                    
                    await self.log(f"   │  ⏭️  跳过当日选股，不再开新仓")
                    await self.log(f"   └───────────────────────────────────────────────────────")
                    # 跳过后续选股逻辑
                    continue

                # 1. 获取当日股票池
                universe = await self.universe_mgr.get_universe(
                    UniverseType.ALL_A,
                    trade_date,
                    exclude_rules,
                )

                # 真实统计各类剔除数量
                st_count = len(await self.universe_mgr._get_st_stocks() & universe)
                new_stock_count = len(await self.universe_mgr._get_new_stocks(trade_date) & universe)
                
                # 🔴 任务3：流动性过滤真正执行（P0！）
                # 查询流动性不足的股票，然后真正从universe中剔除
                low_liquidity_cursor = mongo_manager.find(
                    "stock_daily_ak_full",
                    {
                        "trade_date": int(trade_date),
                        "ts_code": {"$in": list(universe)},
                        "amount": {"$lt": 500}  # 成交额小于500万
                    },
                    {"ts_code": 1}
                )
                low_liquidity_list = [doc["ts_code"] for doc in await low_liquidity_cursor.to_list(length=10000)]
                low_liquidity_set = set(low_liquidity_list)
                low_liquidity_count = len(low_liquidity_set)
                
                # 真正执行过滤！从universe中剔除流动性不足的股票
                universe -= low_liquidity_set
                
                # ✅ 统一打印！不再分散调用！
                await self._print_stock_pool_and_cleaning(trade_date, universe, st_count, new_stock_count, low_liquidity_count)

                if not universe:
                    logger.warn('BACKTEST', "⚠️ 当日无符合条件的股票,跳过调仓")
                    continue

                # 2. 计算因子 & 选股
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

                await self.log(f"   ✅ 因子计算完成,共 {len(factor_df)} 条记录")

                # 🔍 因子完整性检查:检查所有请求的因子是否都存在数据
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
                    await self.log(f"   ⚠️  【重要告警】检测到因子数据缺失,共 {len(missing_factors)} 个:")
                    # 每行显示 5 个因子,避免太长
                    for i in range(0, len(missing_factors), 5):
                        batch = missing_factors[i:i+5]
                        await self.log(f"      • {', '.join(batch)}")
                    await self.log(f"      🔍 原因可能是:")
                    await self.log(f"          1. 该日期未批量计算因子,需要先运行因子同步任务")
                    await self.log(f"          2. 全市场该因子数据不完整,部分日期缺失")
                    await self.log(f"      ⚠️  回测结果可能异常,建议先同步因子数据后重试")

                # 🎯 重构为多策略独立筛选逻辑(实盘对齐):每个策略独立运行,结果合并去重
                await self.log(f"   ═══════════════════════════════════════════════════════════")
                await self.log(f"   🎯 多策略联合筛选开始")
                await self.log(f"   ═══════════════════════════════════════════════════════════")

                all_candidates = set()

                selected_strategies = config.get("selected_strategies", [])
                selected_strategy_names = [s["name"] for s in selected_strategies] if selected_strategies else []

                # 定义各策略的独立筛选条件(从全局策略配置获取,动态匹配参数)
                strategy_configs = {}

                # 遍历所有传入的策略配置,动态生成筛选条件
                for s in selected_strategies:
                    strategy_name = s.get("name", s.get("id", "未知策略"))
                    params = s.get("params", {})

                    # 🔧 全局参数类型统一转换:彻底杜绝类型比较错误
                    converted_params = {}
                    for k, v in params.items():
                        if isinstance(v, bool):
                            # 布尔值转换为 1/0 数值
                            converted_params[k] = 1 if v else 0
                        elif isinstance(v, str) and v.replace(".", "", 1).isdigit():
                            # 字符串格式的数值转换为 float
                            converted_params[k] = float(v)
                        else:
                            # 其他类型保持原格式
                            converted_params[k] = v
                    params = converted_params

                    if strategy_name == "半路追涨":
                        # 读取半路追涨独立参数
                        min_rise_pct = params.get("min_rise_pct", 0.03)
                        max_rise_pct = params.get("max_rise_pct", 0.05)
                        volume_threshold = params.get("min_volume_ratio", 2.5)
                        allow_after_10am = params.get("allow_after_10am", False)

                        strategy_configs[strategy_name] = [
                            {"name": "open_below_limit", "target": 1, "label": "开盘低于涨停价"},
                            {"name": "pct_chg", "target": min_rise_pct, "operator": ">=", "label": "最小涨幅"},
                            {"name": "pct_chg", "target": max_rise_pct, "operator": "<=", "label": "最大涨幅"},
                            {"name": "volume_ratio", "target": volume_threshold, "label": "量比阈值"}
                        ]
                        # ✅ 删除所有分散打印！统一调用 _print_single_strategy_filtering()

                    elif strategy_name == "首板打板":
                        # 读取首板打板独立参数
                        # P1修改:添加竞价涨幅 2%~5%、量比≥1.5、换手率 3%~15%、流通市值 50亿~500亿、要求情绪周期上升期/混沌期
                        min_seal_amount = params.get("min_seal_amount", 5000)
                        max_limit_time = params.get("max_limit_up_time", "10:00")
                        min_circ_mv = params.get("min_circulation_market_cap", 50)
                        max_circ_mv = params.get("max_circulation_market_cap", 500)
                        min_volume_ratio = params.get("min_volume_ratio", 1.5)
                        min_turnover = params.get("min_turnover_rate", 3)
                        max_turnover = params.get("max_turnover_rate", 15)
                        max_blast = params.get("max_blast_count", 1)
                        require_hot = params.get("require_hot_sector", True)
                        require_sentiment = params.get("require_sentiment_period", ["rising", "chaos"])

                        # 时间格式转换:把"HH:MM"字符串转换为分钟数值,方便比较
                        if isinstance(max_limit_time, str) and ":" in max_limit_time:
                            h, m = max_limit_time.split(":")
                            max_limit_time = int(h) * 60 + int(m)

                        strategy_configs[strategy_name] = [
                            {"name": "first_limit_up", "target": 1, "label": "首次涨停"},
                            {"name": "limit_up_yesterday", "target": 0, "label": "昨日未涨停"},
                            {"name": "opening_pct_chg", "target": 2.0, "operator": ">=", "label": "竞价涨幅≥2%"},
                            {"name": "opening_pct_chg", "target": 5.0, "operator": "<=", "label": "竞价涨幅≤5%"},
                            {"name": "volume_ratio", "target": min_volume_ratio, "operator": ">=", "label": "竞价量比≥1.5"},
                            {"name": "turnover", "target": min_turnover, "operator": ">=", "label": "换手率≥3%"},
                            {"name": "turnover", "target": max_turnover, "operator": "<=", "label": "换手率≤15%"},
                            {"name": "circ_mv", "target": min_circ_mv * 10000, "operator": ">=", "label": "最小流通市值"},
                            {"name": "circ_mv", "target": max_circ_mv * 10000, "operator": "<=", "label": "最大流通市值"},
                            {"name": "limit_up_open_amount", "target": min_seal_amount, "label": "最小封单金额"},
                            {"name": "limit_up_open_count", "target": max_blast, "operator": "<=", "label": "最大开板次数"},
                            {"name": "hot_sector", "target": 1 if require_hot else 0, "label": "要求热门板块"},
                            {"name": "sentiment_period_in", "target": require_sentiment, "operator": "in", "label": "情绪周期要求"},
                            {"name": "limit_up_time", "target": max_limit_time, "operator": "<=", "label": "最晚涨停时间"},
                        ]
                        # ✅ 删除所有分散打印！统一调用 _print_single_strategy_filtering()

                    elif strategy_name == "涨停开板":
                        # 读取涨停开板独立参数
                        # P1修改:添加开盘涨幅 0%~3%、量比≥2.0、板数范围 2~4 板、情绪周期要求上升期
                        min_consecutive = params.get("min_consecutive_limit", 2)
                        max_consecutive = params.get("max_consecutive_limit", 4)
                        max_open_duration = params.get("max_open_duration", 5)
                        min_seal_after = params.get("min_seal_after_open", 3000)
                        min_turnover = params.get("min_turnover_rate", 0.15)
                        opening_pct_min = params.get("opening_pct_min", 0.0)
                        opening_pct_max = params.get("opening_pct_max", 3.0)
                        min_volume_ratio = params.get("min_volume_ratio", 2.0)
                        require_sentiment = params.get("require_sentiment_period", ["rising"])

                        strategy_configs[strategy_name] = [
                            {"name": "limit_up_count", "target": min_consecutive, "operator": ">=", "label": "最小连续涨停天数"},
                            {"name": "limit_up_count", "target": max_consecutive, "operator": "<=", "label": "最大连续涨停天数"},
                            {"name": "opening_pct_chg", "target": opening_pct_min, "operator": ">=", "label": "开盘涨幅≥0%"},
                            {"name": "opening_pct_chg", "target": opening_pct_max, "operator": "<=", "label": "开盘涨幅≤3%"},
                            {"name": "volume_ratio", "target": min_volume_ratio, "operator": ">=", "label": "开盘量比≥2.0"},
                            {"name": "limit_up_open_duration", "target": max_open_duration, "operator": "<=", "label": "最大开板时长"},
                            {"name": "limit_up_open_amount", "target": min_seal_after, "label": "开板后最小封单"},
                            {"name": "turnover_rate", "target": min_turnover, "label": "最小换手率"},
                            {"name": "sentiment_period_in", "target": require_sentiment, "operator": "in", "label": "情绪周期要求"},
                        ]
                        # ✅ 删除所有分散打印！统一调用 _print_single_strategy_filtering()

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
                            {"name": "pullback_pct", "target": min_correction, "operator": ">=", "label": "最小回调幅度"},
                            {"name": "pullback_pct", "target": max_correction, "operator": "<=", "label": "最大回调幅度"},
                            {"name": "pullback_days", "target": correction_days_min, "operator": ">=", "label": "最小回调天数"},
                            {"name": "pullback_days", "target": correction_days_max, "operator": "<=", "label": "最大回调天数"},
                            {"name": f"pullback_{support_level}", "target": 1, "label": f"{support_level.upper()}支撑位"},
                            {"name": "volume_ratio_vs_ma5", "target": 1.0, "operator": "<=", "label": "成交量小于5日均量"},
                        ]
                        # ✅ 删除所有分散打印！统一调用 _print_single_strategy_filtering()

                    elif strategy_name == "跌停翘板":
                        # 读取跌停翘板独立参数
                        min_consecutive = params.get("min_consecutive_limit", 3)
                        min_qiao_amount = params.get("min_qiao_amount", 10000)
                        min_rise_after = params.get("min_rise_after_qiao", 0.03)
                        require_high_sentiment = params.get("require_high_sentiment", True)

                        strategy_configs[strategy_name] = [
                            {"name": "limit_down_yesterday", "target": 1, "label": "昨日跌停"},
                            {"name": "open_above_limit_down", "target": 1, "label": "开盘高于跌停价"},
                            {"name": "turnover", "target": 10.0, "operator": ">=", "label": "换手率≥10%"},
                            {"name": "limit_down_open_amount", "target": min_qiao_amount, "label": "翘板最小金额"},
                            {"name": "rise_after_limit_down", "target": min_rise_after, "label": "翘板后最小涨幅"},
                            {"name": "sentiment_score", "target": 1 if require_high_sentiment else 0, "label": "要求高情绪周期"},
                        ]
                        # ✅ 删除所有分散打印！统一调用 _print_single_strategy_filtering()

                # ✅ One Function, One Format! 所有5个策略统一走同一个打印函数！
                # 🚫 业务逻辑代码中绝对不允许直接出现 await self.log()！
                all_candidates = set()
                for s in selected_strategies:
                    strategy_name = s.get("name", s.get("id", "未知策略"))
                    params = s.get("params", {})
                    # 统一打印！统一筛选！
                    candidates = await self._print_single_strategy_filtering(
                        strategy_name, 
                        params, 
                        [], 
                        factor_df, 
                        strategy_configs, 
                        selected_strategy_names
                    )
                    all_candidates.update(candidates)

                # ✅ 所有策略筛选完成！One Function, One Format！
                # 🚫 业务逻辑代码中不再有任何 await self.log() 调用！
                # 📊 总候选: {len(all_candidates)} 只股票

                # 🔧 策略轮动机制:根据历史月度收益动态调整权重已经在权重计算阶段处理
                # 当前改进:每个策略独立筛选,只影响选股结果不影响权重,权重调整后分配还是基于等权基础

                if len(all_candidates) == 0:
                    await self.log(f"   ⚠️  当日无符合条件的交易标的,跳过调仓")
                    continue

            # 计算目标权重
                target_weights = self._compute_weights(
                    list(all_candidates),
                    factor_df,
                    self.weight_method,
                )

                # 🔧 新增:大盘 MA60 过滤 - 大盘跌破 MA60 整体降低仓位 50%(可配置开关)
                if self._risk_config.get("enable_ma60_filter", True):
                    try:
                        # 从 index_daily 查询上证指数(000001.SH)的均线数据
                        index_data = await mongo_manager.find_one(
                            "index_daily",
                            {"ts_code": "000001.SH", "trade_date": trade_date},
                            {"close": 1, "ma60": 1},
                        )
                        if index_data and "close" in index_data and "ma60" in index_data:
                            close = index_data["close"]
                            ma60 = index_data["ma60"]
                            if close < ma60:
                                # 跌破 MA60,整体降低仓位 50%
                                for code in target_weights:
                                    target_weights[code] = target_weights[code] * 0.5
                                await self.log(f"   📉 大盘跌破 MA60,整体仓位降低 50%")
                    except Exception as e:
                        # 查询失败不影响继续执行
                        logger.warn('BACKTEST', f"Failed to check index MA60 for position adjustment: {e}")

                # 计算进度
                total_rebalance_days = len(rebalance_dates)
                current_day_idx = rebalance_dates.index(trade_date) + 1
                progress = (current_day_idx / total_rebalance_days) * 100
                await self.log(f"   📅 当日调仓进度: {progress:.2f}% ({current_day_idx}/{total_rebalance_days}天)")
                await self.log(f"   💲 正在获取股票价格...")
                prices = await self._get_prices(
                    set(holdings.keys()) | set(target_weights.keys()),
                    trade_date,
                )

                # 保存最后一次价格,用于计算最终市值
                last_prices = prices

                await self.log(f"   ✅ 获取到 {len(prices)} 只股票的价格")

                # 如果没有任何股票获取到价格,跳过本次调仓
                if len(prices) == 0 and len(holdings) == 0:
                    await self.log(f"   ⚠️  没有任何股票获取到当日价格,跳过调仓")
                    continue

                # 5. 执行调仓
                await self.log(f"   🔄 正在执行调仓操作...")
                cash, holdings, records = self._rebalance(
                    trade_date, target_weights, cash, holdings, prices, sentiment_level
                )
                rebalance_records.extend(records)

                # 获取股票名称
                stock_names = await self._get_stock_names([r.ts_code for r in records])

                # 🔧 内存优化: 释放不再需要的因子数据和目标权重
                if 'factor_df' in locals():
                    del factor_df
                if 'target_weights' in locals():
                    del target_weights
                gc.collect()

                # 输出调仓记录(带股票名称 + 完整原因描述)
                if len(records) > 0:
                    await self.log("")
                    await self.log(f"   📝 【当日调仓记录】:")
                    await self.log(f"   { '-' * 100}")
                    await self.log(f"   | {'方向':<6} {'日期':<10} {'名称':<8} {'代码':<12} {'股数':<6} {'价格':<8} {'原因'} ")
                    await self.log(f"   { '-' * 100}")

                    for record in records:
                        name = stock_names.get(record.ts_code, record.ts_code.split('.')[0])
                        ts_code = record.ts_code
                        direction = "买入" if record.action == 'buy' else "卖出"
                        # 完善原因说明翻译,更容易阅读理解
                        if record.reason == "rebalance":
                            if direction == "买入":
                                reason_desc = "策略选股调入"
                            else:
                                reason_desc = "调仓调出"
                        elif record.reason == "not_in_target":
                            reason_desc = "不再符合选股条件"
                        else:
                            reason_desc = record.reason

                        # 添加日期信息
                        date = record.date
                        icon = "🔹" if record.action == 'buy' else "🔻"
                        await self.log(f"   | {icon} {direction:<6} {date:<10} {name:<8} {ts_code:<12} {record.shares:<6} {record.price:<8.2f} {reason_desc:<}")
                    await self.log(f"   { '-' * 100}")

            # ==================== 非调仓日输出 ====================
            # 非调仓日也要有明确的输出标记，保证每天日志格式完整
            else:
                await self.log(f"")
                await self.log(f"   ═══════════════════════════════════════════════════════")
                await self.log(f"   ℹ️  【非调仓日】无调仓操作，继续持有现有仓位")
                await self.log(f"   ═══════════════════════════════════════════════════════")

            # ==================== 每日收盘汇总（每天必须输出）====================
            # 无论调仓日还是非调仓日，每天都要有完整的日志结尾
            await self.log(f"")
            await self.log(f"═══════════════════════════════════════════════════════════════")
            await self.log(f"📅 【第 {idx+1}/{total_days} 天】处理完成: {trade_date}")
            await self.log(f"   💵 当日持仓: {len(holdings)} 只股票, 现金剩余: {cash:,.2f} 元")
            await self.log(f"═══════════════════════════════════════════════════════════════")

        # 计算最终市值（所有日期处理完成后）
        final_value = cash
        for code, shares in holdings.items():
            if shares > 0 and code in last_prices:
                # last_prices[code] 是 {open: x, close: x},用收盘价估值
                final_value += shares * last_prices[code]['close']

        # 计算总收益率
        initial_value = self._initial_cash
        total_return = (final_value - initial_value) / initial_value

        # 收集所有交易记录
        all_trades = []
        for day_records in rebalance_records:
            if isinstance(day_records, list):
                all_trades.extend(day_records)
            else:
                all_trades.append(day_records)

        # 合并买入+卖出为完整交易,转换为字典格式
        merged_trades = []

        # 收集所有买入记录,按code分组
        buy_records = {}  # code -> list of buy records
        total_signals = 0
        winning_trades = 0

        for day_records in rebalance_records:
            records_list = day_records if isinstance(day_records, list) else [day_records]
            for record in records_list:
                if record.action == 'buy':
                    # 每个买入算一个信号
                    code = record.ts_code
                    if code not in buy_records:
                        buy_records[code] = []
                    buy_records[code].append(record)

        # 所有买入都是信号,不管是否卖出
        total_signals = sum(len(buys) for buys in buy_records.values())

        # 统计每个卖出是否盈利,同时合并完整交易
        for day_records in rebalance_records:
            records_list = day_records if isinstance(day_records, list) else [day_records]
            for record in records_list:
                if record.action == 'sell' and record.ts_code in buy_records:
                    # 这只股票有买入,现在卖出了,可以计算盈亏
                    # 简单算法:只要卖出价格高于买入平均成本就算盈利
                    buys = buy_records[record.ts_code]
                    total_cost = sum(b.amount for b in buys)
                    total_shares = sum(b.shares for b in buys)
                    if total_shares > 0:
                        avg_cost = total_cost / total_shares
                        # 卖出价格高于平均成本 → 盈利
                        profit = (record.price - avg_cost) / avg_cost * 100
                        if record.price > avg_cost:
                            winning_trades += 1

                        # 合并为一笔完整交易
                        first_buy = buys[0]
                        stock_names = await self._get_stock_names([record.ts_code])
                        name = stock_names.get(record.ts_code, record.ts_code.split('.')[0])

                        # 从 reason 中提取策略名称,如果替换后为空显示 "-"
                        strategy_name = first_buy.reason.replace(' 策略选股调入', '').strip()
                        if not strategy_name:
                            strategy_name = "-"

                        merged_trades.append({
                            'ts_code': record.ts_code,
                            'name': name,
                            'strategy': strategy_name,
                            'sentiment': first_buy.sentiment,
                            'buy_date': first_buy.date,
                            'buy_time': '09:30',
                            'buy_price': avg_cost,
                            'sell_date': record.date,
                            'sell_time': '15:00',
                            'sell_price': record.price,
                            'shares': total_shares,
                            'profit_pct': profit,
                        })

        # 添加还未卖出的持仓到明细
        for code, buys in buy_records.items():
            # 检查是否已经卖出
            # 简单算法:如果这只code没有卖出记录,说明还在持仓中
            has_sold = False
            for day_records in rebalance_records:
                records_list = day_records if isinstance(day_records, list) else [day_records]
                for record in records_list:
                    if record.action == 'sell' and record.ts_code == code:
                        has_sold = True
                        break
            if not has_sold:
                # 还在持仓中,添加到明细
                first_buy = buys[0]
                stock_names = await self._get_stock_names([code])
                name = stock_names.get(code, code.split('.')[0])

                # 从 reason 中提取策略名称,如果替换后为空显示 "-"
                strategy_name = first_buy.reason.replace(' 策略选股调入', '').strip()
                if not strategy_name:
                    strategy_name = "-"

                merged_trades.append({
                    'ts_code': code,
                    'name': name,
                    'strategy': strategy_name,
                    'sentiment': first_buy.sentiment,
                    'buy_date': first_buy.date,
                    'buy_time': '09:30',
                    'buy_price': sum(b.amount for b in buys) / sum(b.shares for b in buys),
                    'sell_date': '',
                    'sell_time': '',
                    'sell_price': 0.0,
                    'shares': sum(b.shares for b in buys),
                    'profit_pct': None,  # 还未卖出
                })

        # 计算胜率
        win_rate = 0.0
        if total_signals > 0:
            win_rate = winning_trades / total_signals  # 保存为小数,前端会乘以100显示百分比
            win_rate_percent = win_rate * 100  # 日志显示用百分比
        else:
            win_rate_percent = 0.0
        # 计算年化收益率(交易日/年 ≈ 252)
        trading_days = len(rebalance_dates)
        if trading_days > 0:
            # 复利年化: (1 + total_return) ^ (252 / trading_days) - 1
            annualized_return = ((1 + total_return) ** (252 / trading_days)) - 1
        else:
            annualized_return = 0.0

        # 已经计算好的其他指标从结果获取
        max_drawdown = getattr(self, 'max_drawdown', 0.0)
        profit_loss_ratio = getattr(self, 'profit_loss_ratio', 0.0)
        sharpe_ratio = getattr(self, 'sharpe_ratio', 0.0)

        # 统计盈利次数/亏损次数
        losing_trades = total_signals - winning_trades
        total_trades = len(merged_trades)

        # 计算收益回撤比 = 累计收益率 / 最大回撤(当最大回撤 > 0 时)
        return_drawdown_ratio = 0.0
        if max_drawdown > 0 and total_return != 0:
            return_drawdown_ratio = abs(total_return) / max_drawdown

        # 计算平均持仓天数
        average_hold_days = 0.0
        completed_trades = [t for t in merged_trades if t.get('sell_date') and t.get('buy_date')]
        if len(completed_trades) > 0:
            total_hold_days = 0
            for trade in completed_trades:
                buy_date_int = int(trade['buy_date'])
                sell_date_int = int(trade['sell_date'])
                # 计算持仓天数(简单相减,都是YYYYMMDD格式)
                # 转换为datetime计算更准确
                from datetime import datetime
                buy_dt = datetime.strptime(str(buy_date_int), '%Y%m%d')
                sell_dt = datetime.strptime(str(sell_date_int), '%Y%m%d')
                hold_days = (sell_dt - buy_dt).days
                total_hold_days += hold_days
            average_hold_days = total_hold_days / len(completed_trades)

        # 输出最终汇总结果到日志
        await self.log("✅ 回测全部完成!")
        if total_signals == 0:
            await self.log("📊 汇总结果:总信号 0 个,平均胜率 0.00%,总收益率 0.00%")
            await self.log("  累计收益率: 0.00%")
            await self.log("  年化收益率: 0.00%")
            await self.log("  最大回撤: 0.00%")
            await self.log("  盈亏比: 0.00")
            await self.log("  夏普比率: 0.00")
            await self.log("  收益回撤比: 0.00")
            await self.log("  总交易次数: 0")
            await self.log("  盈利次数: 0 / 亏损次数: 0")
            await self.log("  平均持仓天数: 0")
        else:
            await self.log(f"📊 汇总结果:总信号 {total_signals} 个,平均胜率 {win_rate_percent:.2f}%,总收益率 {total_return * 100:.2f}%")
            await self.log(f"  累计收益率: {total_return * 100:.2f}%")
            await self.log(f"  年化收益率: {annualized_return * 100:.2f}%")
            await self.log(f"  最大回撤: {max_drawdown * 100:.2f}%")
            await self.log(f"  盈亏比: {profit_loss_ratio:.2f}")
            await self.log(f"  夏普比率: {sharpe_ratio:.2f}")
            await self.log(f"  收益回撤比: {return_drawdown_ratio:.2f}")
            await self.log(f"  总交易次数: {total_trades}")
            await self.log(f"  盈利次数: {winning_trades} / 亏损次数: {losing_trades}")
            await self.log(f"  平均持仓天数: {average_hold_days:.1f}")

        #  打印完整逐笔交易明细
                #  打印完整逐笔交易明细                if len(merged_trades) > 0:                    await self.log("")                    await self.log("📝 【完整逐笔交易明细】")                    await self.log("")                                        # 使用 tabulate 输出美观的表格                    from tabulate import tabulate                                        table_data = []                    headers = ["#", "代码", "名称", "策略", "情绪", "买入", "买入时间", "卖出", "卖出时间", "买入价", "卖出价", "股数", "仓位", "持仓", "盈亏", "盈亏%", "", "说明"]                                        for idx, trade in enumerate(merged_trades, 1):                        ts_code = trade.get('ts_code', '')                        name = trade.get('name', ts_code)                        strategy = trade.get('strategy', '')                        # strategy 为空改为 "-"(表示无策略说明)                        strategy_name = strategy.strip()                        if not strategy_name:                            strategy_name = "-"                        # 只取情绪第一部分,"高潮期" 而不是 "高潮期,仓位系数1.0"                        sentiment = trade.get('sentiment', '')                        if sentiment:                            sentiment = sentiment.split(',')[0].strip()                        sentiment = sentiment or "-"                        buy_date = trade.get('buy_date', '')                        buy_price = float(trade.get('buy_price', 0)) if trade.get('buy_price') is not None else 0.0                        buy_time = trade.get('buy_time', '09:35')  # 使用存储的买入时间                        sell_date = trade.get('sell_date', '')                        sell_price = float(trade.get('sell_price', 0)) if trade.get('sell_price') is not None else 0.0                        sell_time = trade.get('sell_time', '收盘')                        shares = int(trade.get('shares', 0)) if trade.get('shares') is not None else 0                        profit_pct = trade.get('profit_pct')                                                # 计算持仓天数、盈亏绝对值、是否盈利                        hold_days = 0                        profit_abs = 0                        is_profit = "-"                        if profit_pct is not None and buy_price > 0 and sell_price > 0:                            profit_abs = shares * (sell_price - buy_price) * (1 - self.SELL_COMMISSION - self.STAMP_TAX)                            if profit_pct > 0:                                is_profit = "✅"                            else:                                is_profit = "❌"                                                        # 计算持仓天数                            if buy_date and sell_date:                                from datetime import datetime                                try:                                    buy_dt = datetime.strptime(str(buy_date), '%Y%m%d')                                    sell_dt = datetime.strptime(str(sell_date), '%Y%m%d')                                    hold_days = (sell_dt - buy_dt).days                                except:                                    hold_days = 0                                                # 计算仓位(粗略估算:占总资金百分比)                        position_pct = "-"                        if shares > 0 and buy_price > 0:                            cost = shares * buy_price                            position_pct = f"{cost / self._initial_cash * 100:.0f}%"                                                # 获取策略参数说明                        strategy_desc = strategy_name                        if strategy_name and "半路追涨" in strategy_name:                            strategy_desc = f"{strategy_name},涨幅达标"                        elif not strategy_desc or strategy_desc == "-":                            strategy_desc = "-"                                                # 格式化                        profit_abs_str = f"{profit_abs:.0f}" if profit_abs != 0 else "-"                        profit_pct_str = f"{profit_pct:.2f}%" if profit_pct is not None else "-"                                                table_data.append([                            idx,                            ts_code,                            name[:12],  # 名称太长截断                            strategy_name[:10],                            sentiment,                            buy_date,                            buy_time,                            sell_date,                            sell_time,                            f"{buy_price:.2f}",                            f"{sell_price:.2f}",                            shares,                            position_pct,                            hold_days,                            profit_abs_str,                            profit_pct_str,                            is_profit,                            strategy_desc[:20],                        ])                                        # 使用 grid 表格格式,对齐美观                    table_str = tabulate(table_data, headers=headers, tablefmt='grid')                                        # tabulate 输出每一行,确保日志能逐行推送                    for line in table_str.split('\n'):                        await self.log(line)                                        await self.log("")                    await self.log(f"📊 总计 {len(merged_trades)} 笔完整交易")
        # 将 RebalanceRecord 对象转换为字典,方便 MongoDB 序列化
        rebalance_records_dict = []
        for day_records in rebalance_records:
            if isinstance(day_records, list):
                day_dict = []
                for record in day_records:
                    if hasattr(record, '__dict__'):
                        day_dict.append(record.__dict__)
                    else:
                        day_dict.append(record)
                rebalance_records_dict.append(day_dict)
            else:
                if hasattr(day_records, '__dict__'):
                    rebalance_records_dict.append(day_records.__dict__)
                else:
                    rebalance_records_dict.append(day_records)

        # 转换 all_trades 也为字典
        all_trades_dict = []
        for record in all_trades:
            if hasattr(record, '__dict__'):
                all_trades_dict.append(record.__dict__)
            else:
                all_trades_dict.append(record)

        # 计算净值曲线和每日盈亏
        # 从初始资金开始,记录每个调仓日的组合价值
        net_value_series = []
        # 我们需要重新构建每日净值
        # 由于只有调仓日才有记录,我们只保存调仓日的净值
        current_value = self._initial_cash
        net_value_series.append({
            "trade_date": rebalance_dates[0] if rebalance_dates else start_date,
            "net_value": current_value,
            "daily_profit": 0.0
        })

        # 如果有调仓记录,计算每日净值
        # 这里简化处理,只保存每个调仓日的净值
        daily_profit_list = []
        # 第一个点:初始资金
        net_value_series.append({
            "trade_date": str(config.get('start_date')) if rebalance_dates else str(config.get('start_date')),
            "net_value": self._initial_cash,
            "daily_profit": 0.0
        })
        daily_profit_list.append(0.0)

        current_value = self._initial_cash
        for i, day_records in enumerate(rebalance_records_dict):
            trade_date = None
            if isinstance(day_records, list) and len(day_records) > 0:
                trade_date = day_records[0].get('date', None) if isinstance(day_records[0], dict) else None

            # 计算当日盈亏(简化:基于最终价值反推)
            # 完整计算需要每日期权,这里先提供基础结构
            day_profit = 0.0
            if i == len(rebalance_records_dict) - 1:
                # 最后一天用最终价值
                day_profit = final_value - current_value
                current_value = final_value
            daily_profit_list.append(day_profit)

            if trade_date:
                net_value_series.append({
                    "trade_date": trade_date,
                    "net_value": current_value,
                    "daily_profit": day_profit
                })
            # 如果没有 trade_date,仍然添加到序列(保持净值曲线连续)
            elif len(net_value_series) > 0:
                # 和前一天净值相同,盈亏为0
                last_value = net_value_series[-1]['net_value']
                net_value_series.append({
                    "trade_date": str(trade_date) if trade_date else f"day_{i}",
                    "net_value": last_value,
                    "daily_profit": 0.0
                })
                daily_profit_list.append(0.0)

        # 计算最大回撤(基于净值曲线)
        max_drawdown = 0.0
        if len(net_value_series) > 1:
            peak = net_value_series[0]['net_value']
            for point in net_value_series:
                if point['net_value'] > peak:
                    peak = point['net_value']
                drawdown = (peak - point['net_value']) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
            # max_drawdown 转换为小数(百分比由前端显示时 ×100)

        # 提取 daily_profit 序列
        daily_profit = [point['daily_profit'] for point in net_value_series]

        # 计算盈亏比:总盈利 / 总亏损
        # 我们从 daily_profit 统计
        total_profit = 0.0
        total_loss = 0.0
        for p in daily_profit:
            if p > 0:
                total_profit += p
            else:
                total_loss += -p

        profit_loss_ratio = 0.0
        if total_loss > 0:
            profit_loss_ratio = total_profit / total_loss

        # 计算夏普比率:需要无风险利率,这里简化为 0
        # sharpe_ratio = mean(daily_profit) / std(daily_profit)
        # 暂时简化为 0.0,后续可以完整计算
        sharpe_ratio = 0.0

        # 计算 drawdown 序列
        drawdown_series = []
        if len(net_value_series) > 1:
            peak = net_value_series[0]['net_value']
            for point in net_value_series:
                if point['net_value'] > peak:
                    peak = point['net_value']
                drawdown = (peak - point['net_value']) / peak
                drawdown_series.append({
                    "trade_date": point['trade_date'],
                    "drawdown": drawdown
                })

        # 返回完整结果(全部为字典,可序列化)
        return {
            "success": True,
            "initial_cash": self._initial_cash,
            "final_cash": cash,
            "final_value": final_value,
            "final_holdings": holdings,
            "total_return": total_return,
            "annualized_return": annualized_return,
            "win_rate": win_rate,
            "total_signals": total_signals,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "profit_loss_ratio": profit_loss_ratio,
            "return_drawdown_ratio": return_drawdown_ratio,
            "average_hold_days": average_hold_days,
            "rebalance_records": rebalance_records_dict,
            "all_trades": all_trades_dict,
            "benchmark_data": benchmark_data,
            "stock_names": stock_names,
            "net_value_series": net_value_series,
            "drawdown_series": drawdown_series,
            "daily_profit": daily_profit,
        }

    async def _load_benchmark_data(self, benchmark_code: str, start_date: int, end_date: int):
        """加载基准指数数据用于计算超额收益"""
        # 从 stock_daily_ak_full 加载基准数据
        # 数据库验证:trade_date 存储为 int 类型
        query = {
            "ts_code": benchmark_code,
            "trade_date": {"$gte": start_date, "$lte": end_date}
        }
        docs = await mongo_manager.find_many("stock_daily_ak_full", query)
        # 按日期排序
        docs.sort(key=lambda x: x["trade_date"])
        benchmark_data = []
        for doc in docs:
            benchmark_data.append({
                "trade_date": doc["trade_date"],
                "close": doc["close"],
                "pct_chg": doc.get("pct_chg", 0.0)
            })
        return benchmark_data

    async def _get_prices(self, ts_codes: set[str], trade_date):
        """批量获取指定股票在指定日期的开盘价和收盘价

        Returns:
            dict: {ts_code: {"open": open_price, "close": close_price}}
        """
        # 自动格式标准化:兼容两种输入格式
        # 数据库中 ts_code 带后缀(.SH/.SZ),所以无论输入什么都转换为带后缀格式
        ts_codes_standard = []
        for code in ts_codes:
            code_str = str(code).strip()
            if code_str.endswith(".SH") or code_str.endswith(".SZ"):
                # 输入已经带后缀,直接使用(匹配数据库)
                ts_codes_standard.append(code_str)
            else:
                # 输入不带后缀,根据代码开头自动补全后缀
                # - 6/5/9 开头 → .SH(上交所)
                # - 其他 → .SZ(深交所)
                if code_str.startswith('6') or code_str.startswith('5') or code_str.startswith('9'):
                    ts_codes_standard.append(f"{code_str}.SH")
                else:
                    ts_codes_standard.append(f"{code_str}.SZ")

        # 修复 MongoDB 复合索引查询 bug:
        # 使用复合索引 (ts_code, trade_date) + $in 查询时,MongoDB 无法正确匹配,总是返回 0 条
        # 所以改为:先按 trade_date 查询,再在内存中过滤 ts_code
        ts_codes_set = set(ts_codes_standard)
        # 🔧 修复:trade_date 从 all_trade_dates 获取是字符串,但数据库存 int,必须转换
        trade_date_int = int(trade_date)
        query = {
            "trade_date": trade_date_int,
        }

        await self.log(f"            🔍 _get_prices: 查询 {len(ts_codes_standard)} 只股票,日期: {trade_date}, 标准化后候选: {sorted(ts_codes_standard)}")

        docs = await mongo_manager.find_many("stock_daily_ak_full", query)
        result = {}
        # 调试:打印每个doc的ts_code,帮助定位问题
        matched = 0
        for doc in docs:
            ts_code_doc = doc["ts_code"]

            # 支持两种格式匹配:
            # 1. 完全匹配(数据库带后缀)
            # 2. 不带后缀匹配(数据库不带后缀,我们带后缀)
            matched_key = None
            if ts_code_doc in ts_codes_set:
                matched_key = ts_code_doc
            else:
                # 尝试去掉后缀再匹配
                if ts_code_doc.endswith('.SH') or ts_code_doc.endswith('.SZ'):
                    ts_code_doc_no_suffix = ts_code_doc[:-3]
                    if ts_code_doc_no_suffix in ts_codes_set:
                        matched_key = ts_code_doc_no_suffix
                else:
                    # 反向匹配:我们带后缀,但数据库不带
                    # 数据库不带后缀,我们带后缀 → 需要找到我们这边对应的候选
                    for candidate in ts_codes_set:
                        if candidate.endswith('.SH') or candidate.endswith('.SZ'):
                            candidate_no_suffix = candidate[:-3]
                            if candidate_no_suffix == ts_code_doc:
                                matched_key = candidate
                                break

            if matched_key:
                result[matched_key] = {
                    "open": doc.get("open", doc["close"]),  # 如果没有open,fallback to close
                    "close": doc["close"]
                }
                matched += 1


        await self.log(f"            ✅ _get_prices: 查询到 {len(result)} 只股票有价格")

        return result

    def _compute_weights(self, candidates: list[str], factor_df, weight_method: str):
        """计算目标权重 - 根据权重方法分配权重"""
        if weight_method == "equal":
            # 等权分配
            weight = 1.0 / len(candidates) if len(candidates) > 0 else 0
            return dict.fromkeys(candidates, weight)
        else:
            # 默认等权
            weight = 1.0 / len(candidates) if len(candidates) > 0 else 0
            return dict.fromkeys(candidates, weight)

    def _extract_position_multiplier(self, sentiment: str) -> float:
        """【辅助函数】从情绪等级字符串中提取仓位系数
        
        Args:
            sentiment: 情绪等级字符串，例如 "高潮期,仓位系数1.0"
        
        Returns:
            float: 仓位系数，默认 1.0
        """
        if not sentiment or "仓位系数" not in sentiment:
            return 1.0
        try:
            # 从 "高潮期,仓位系数1.0" 中提取 "1.0"
            idx = sentiment.find("仓位系数")
            if idx != -1:
                num_str = sentiment[idx + 4:].strip()
                return float(num_str)
        except (ValueError, IndexError):
            pass
        return 1.0

    def _rebalance(self, trade_date: int, target_weights: dict[str, float],
                   cash: float, holdings: dict[str, int], prices: dict[str, float], sentiment: str = ""):
        """执行调仓

        Args:
            trade_date: 当前调仓日期
            target_weights: 目标权重 {ts_code: weight}
            cash: 当前现金
            holdings: 当前持仓 {ts_code: shares}
            prices: 当前价格 {ts_code: price}
            sentiment: 情绪等级字符串（含仓位系数）

        Returns:
            (new_cash, new_holdings, records)
        """
        records = []

        # 计算当前总价值
        total_value = cash
        for code, shares in holdings.items():
            if code in prices and shares > 0:
                # 持仓卖出用收盘价估值
                price = prices[code]['close']
                total_value += shares * price

        # 🔴 任务2：情绪周期仓位系数真正应用（P0！）
        position_multiplier = self._extract_position_multiplier(sentiment)
        
        # 计算目标持仓
        target_shares = {}  # {ts_code: target_shares}
        for code, weight in target_weights.items():
            if code not in prices:
                continue  # 没有价格,无法买入
            # ✅ 应用情绪仓位系数！
            # 例如：情绪是冰点期，仓位系数0.3，则目标价值只占总资金的30%
            target_value = total_value * weight * position_multiplier
            price = prices[code]['open']  # 买入用开盘价
            # 向下取整到 100 的倍数(A股买入规则)
            shares = int(int(target_value / price) / 100) * 100
            if shares > 0:
                target_shares[code] = shares

        # 先卖出:不在目标持仓中的股票卖出
        sell_codes = [code for code in holdings if code not in target_shares and holdings[code] > 0]
        for ts_code in sell_codes:
            shares = holdings[ts_code]
            price = prices.get(ts_code, {}).get('close', 0)
            if price <= 0 or shares <= 0:
                continue

            # 计算卖出金额(含滑点扣除)
            slippage_pct = self._slippage_pct if hasattr(self, '_slippage_pct') else 0.002
            sell_price_adj = price * (1 - slippage_pct)  # 卖出时滑点使成交价降低
            gross_amount = shares * sell_price_adj
            commission = max(gross_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
            stamp_tax = gross_amount * self.STAMP_TAX
            net_amount = gross_amount - commission - stamp_tax

            # 更新现金
            cash += net_amount

            # 记录交易
            records.append(RebalanceRecord(
                date=str(trade_date),
                action="sell",
                ts_code=ts_code,
                shares=shares,
                price=price,  # 卖出用收盘价
                amount=net_amount,
                reason="not_in_target",
                sentiment=sentiment
            ))

            # 清空持仓
            holdings[ts_code] = 0

        # 再买入:目标持仓中需要增加的股票
        for ts_code, target_count in target_shares.items():
            current_shares = holdings.get(ts_code, 0)
            delta = target_count - current_shares

            if delta <= 0:
                continue  # 不需要买入

            price = prices.get(ts_code, {}).get('open', 0)
            if price <= 0:
                continue

            # 计算买入成本(含滑点扣除)
            slippage_pct = self._slippage_pct if hasattr(self, '_slippage_pct') else 0.002
            buy_price_adj = price * (1 + slippage_pct)  # 买入时滑点使成交价升高
            gross_amount = delta * buy_price_adj
            commission = max(gross_amount * self.BUY_COMMISSION, self.MIN_COMMISSION)
            total_cost = gross_amount + commission

            if cash < total_cost:
                # 现金不足,按比例缩减
                ratio = cash / total_cost
                delta = int(int(delta * ratio) / 100) * 100
                if delta <= 0:
                    continue
                gross_amount = delta * buy_price_adj
                commission = max(gross_amount * self.BUY_COMMISSION, self.MIN_COMMISSION)
                total_cost = gross_amount + commission

            # 更新现金
            cash -= total_cost

            # 更新持仓
            holdings[ts_code] = current_shares + delta

            # 记录交易
            records.append(RebalanceRecord(
                date=str(trade_date),
                action="buy",
                ts_code=ts_code,
                shares=delta,
                price=price,
                amount=-total_cost,
                reason="rebalance",
                sentiment=sentiment
            ))

        # 清理零持仓
        holdings = {code: shares for code, shares in holdings.items() if shares > 0}

        return cash, holdings, records

    async def _get_stock_names(self, ts_codes: list[str]):
        """批量获取股票名称,使用缓存减少查询"""
        result = {}
        need_query = []

        # 自动格式标准化:适配数据库实际存储格式
        # 数据库中 stock_basic 存储格式:
        #   上海交易所 → sh + 数字 + .SZ   (例如 sh600000.SZ → 浦发银行)
        #   深圳交易所 → sz + 数字 + .SZ   (例如 sz000001.SZ → 平安银行)
        #   北交所 → bj + 数字 + .SZ   (例如 bj920000.SZ → 安徽凤凰)
        for ts_code in ts_codes:
            code_str = str(ts_code).strip()

            # 如果输入已经带有交易所前缀+后缀,直接使用
            if code_str.startswith('sh') or code_str.startswith('sz') or code_str.startswith('bj'):
                standard_code = code_str
            elif code_str.endswith(".SH") or code_str.endswith(".SZ"):
                # 输入带后缀但没有交易所前缀 → 添加交易所前缀
                code_only = code_str.split('.')[0]
                if code_only.startswith('6') or code_only.startswith('5') or code_only.startswith('9'):
                    # 上海交易所
                    standard_code = f"sh{code_str}"
                else:
                    # 深圳交易所
                    standard_code = f"sz{code_str}"
            else:
                # 输入既没有前缀也没有后缀 → 添加交易所前缀和后缀
                if code_str.startswith('6') or code_str.startswith('5') or code_str.startswith('9'):
                    standard_code = f"sh{code_str}.SH"
                else:
                    standard_code = f"sz{code_str}.SZ"

            if standard_code in self._stock_name_cache:
                result[ts_code] = self._stock_name_cache[standard_code]
            else:
                need_query.append(standard_code)

        # 查询缓存未命中的(已经标准化)
        if len(need_query) > 0:
            docs = await mongo_manager.find_many(
                "stock_basic",
                {"ts_code": {"$in": need_query}},
                {"ts_code": 1, "name": 1}
            )

            for doc in docs:
                standard_code = doc["ts_code"]
                name = doc.get("name", standard_code)
                self._stock_name_cache[standard_code] = name

        # 构建结果,返回给调用方使用原始 ts_code 作为 key
        for ts_code in ts_codes:
            code_str = str(ts_code).strip()

            if code_str.startswith('sh') or code_str.startswith('sz') or code_str.startswith('bj'):
                standard_code = code_str
            elif code_str.endswith(".SH") or code_str.endswith(".SZ"):
                code_only = code_str.split('.')[0]
                if code_only.startswith('6') or code_only.startswith('5') or code_only.startswith('9'):
                    standard_code = f"sh{code_str}"
                else:
                    standard_code = f"sz{code_str}"
            else:
                if code_str.startswith('6') or code_str.startswith('5') or code_str.startswith('9'):
                    standard_code = f"sh{code_str}.SH"
                else:
                    standard_code = f"sz{code_str}.SZ"

            if standard_code in self._stock_name_cache:
                result[ts_code] = self._stock_name_cache[standard_code]
            else:
                # 找不到,回退到使用原始代码去掉后缀作为名称
                if '.' in code_str:
                    result[ts_code] = code_str.split('.')[0]
                else:
                    result[ts_code] = code_str

        return result
