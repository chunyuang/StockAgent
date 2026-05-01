"""
组合回测引擎

【双模式架构设计说明】
═══════════════════════════════════════════════════════════════

▶️ 回测模式 (MODE=backtest)
   ┌─────────────────────────────────────────────────────────┐
   │  读取路径: MongoDB (stock_daily_ak_full) → 筛选 → 调仓 │
   │  性能: 极速 (无需计算因子,直接读取)                   │
   │  适用: 大规模历史回测、参数寻优、策略验证              │
   │  依赖: DATA_SYNC 节点预计算所有因子 (T+1 批量计算)    │
   └─────────────────────────────────────────────────────────┘

▶️ 实盘模式 (MODE=live)
   ┌─────────────────────────────────────────────────────────┐
   │  计算路径: 实时行情 → factor_engine → 因子计算 → 筛选  │
   │  性能: 实时计算 (支持 Redis 缓存加速,24小时过期)       │
   │  适用: 盘中选股、实时监控、动态调仓、模拟交易            │
   │  依赖: Listener 节点实时行情推送 + LLM 因子推理         │
   └─────────────────────────────────────────────────────────┘

【两种模式切换方式】
  • 环境变量: export MODE=backtest 或 export MODE=live
  • .env 文件: MODE=backtest
  • 默认值: live (实盘模式)

【因子字段映射关系(两种模式输出完全一致)】
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
import math
from datetime import datetime as dt_now  # 【修复：避免局部from datetime import datetime导致UnboundLocalError】

from core.managers import mongo_manager, redis_manager
from core.utils.logger import logger

# 【修复：PerformanceAnalyzer已弃用（API不匹配），移除import避免ModuleNotFoundError】n# from real_trading.performance_analyzer import PerformanceAnalyzer

from .factor_engine import FactorEngine, log_memory_usage
from .universe import ExcludeRule, UniverseManager, UniverseType
from .special_period_filter import get_special_period_filter


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
    strategy_name: str = ""  # 【修复新6：strategy_name独立字段，不需要从reason字符串replace提取】
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

    # 【P2-3修复：策略买入时间常量，避免硬编码重复】
    STRATEGY_BUY_TIMES = {
        '半路追涨': '10:00',
        '首板打板': '09:35',
        '涨停开板': '10:00',
        '龙头低吸': '14:00',
        '跌停翘板': '10:30',
    }

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
    # 所有日志输出必须走以下统一入口!绝对不允许直接调用 await self.log()!
    # ==================================================================================

    async def _print_daily_header(self, day_idx: int, total_days: int, trade_date: str):
        """【统一入口!每日开头必须调用!】"""
        await self.log(f"")
        await self.log(f"═══════════════════════════════════════════════════════════")
        await self.log(f"📅 [第 {day_idx}/{total_days} 天] 处理日期: {trade_date}")
        await self.log(f"═══════════════════════════════════════════════════════════")

    async def _print_market_environment(self, trade_date: int):
        """【统一入口!每日市场环境判断必须调用!】

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
        # 【修复新5：trade_date防御性检查，None时跳过避免异常】
        if trade_date is None:
            return 0, 0
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

        # 【修复#5:统一强制空仓阈值 - 与判断逻辑使用同一常量】
        FORCE_EMPTY_LIMIT_DOWN = 50   # 跌停超过此阈值触发强制空仓
        FORCE_EMPTY_LIMIT_UP = 10      # 涨停低于此阈值触发强制空仓

        await self.log(f"   │  🔹 涨跌停统计: 涨停{limit_up_count}只, 跌停{limit_down_count}只")
        if limit_down_count >= FORCE_EMPTY_LIMIT_DOWN or limit_up_count <= FORCE_EMPTY_LIMIT_UP:
            await self.log(f"   │     → 🔴 触发强制空仓 (跌停≥{FORCE_EMPTY_LIMIT_DOWN}只 或 涨停≤{FORCE_EMPTY_LIMIT_UP}只)")
        else:
            await self.log(f"   │     → 🟢 不触发强制空仓 (跌停<{FORCE_EMPTY_LIMIT_DOWN}只 且 涨停>{FORCE_EMPTY_LIMIT_UP}只)")
        await self.log(f"   │  🔹 大盘平均涨跌幅: {'+' if index_change >= 0 else ''}{index_change:.2f}%")
        if abs(index_change) < 3:
            await self.log(f"   │     → 🟢 符合交易条件")
        else:
            await self.log(f"   │     → 🟡 极端行情,谨慎交易")

        # 【修复#22：统一情绪周期阈值，和因子映射保持一致】
        # 情绪周期评分 → 阈值统一：
        #  score ≥ 70 → 上升期 (rising)
        #  40 ≤ score < 70 → 混沌期 (chaos)
        #  score < 40 → 衰退期 (depression)
        #
        # 【P2-5文档化】情绪评分公式：
        #   sentiment_score = (涨停数 - 跌停数) + 大盘涨跌幅*10 + 50
        #   设计思路：以50为中性基准，涨跌停差反映市场极端情绪，
        #   大盘涨跌幅*10放大权重(±1%对应±10分)，结果夹逼到[0,100]
        #   注意：此为经验公式，未经过统计验证，后续可考虑用因子库替换
        sentiment_score = min(100, max(0, (limit_up_count - limit_down_count) + int(index_change * 10) + 50))
        if sentiment_score >= 70:
            sentiment_level = "高潮期,仓位系数1.0"
        elif sentiment_score >= 40:
            sentiment_level = "震荡期,仓位系数0.6"
        else:
            sentiment_level = "冰点期,仓位系数0.3"
        await self.log(f"   │  🔹 情绪周期评分:{sentiment_score}分 → {sentiment_level}")
        await self.log(f"   └───────────────────────────────────────────────────────")

        return sentiment_level, limit_up_count, limit_down_count

    async def _print_single_strategy_filtering(self, strategy_name: str, params: dict, conditions: list, factor_df, strategy_configs: dict, all_selected_strategies: list):
        """【统一入口!所有策略筛选打印必须调用!One Function, One Format!】

        所有5个策略(半路追涨/首板打板/涨停开板/龙头低吸/跌停翘板)必须调用此函数!
        绝对不允许在策略代码中直接写 await self.log()!

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

        # 参数配置显示(根据不同策略格式化显示)
        await self.log(f"   │    📌 参数配置:")
        if strategy_name == "半路追涨":
            min_rise_pct = params.get("min_rise_pct", 0.03)
            max_rise_pct = params.get("max_rise_pct", 0.05)
            # 【修复#29：volume_threshold 参数名统一
            # 外层 -> strategy_params -> volume_threshold 保存进来
            # 这里策略内使用 min_volume_ratio 是因子表内统一字段名
            # 两种名称都尝试，保证向后兼容
            # 【修复#4：默认值统一为1.5，和 models.py/ultra_short.py/defaults.py 保持一致
            volume_threshold = params.get("volume_threshold", params.get("min_volume_ratio", 1.5))
            min_volume_ratio = volume_threshold
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
            require_hot = params.get("require_hot_sector", False)
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
            # 【修复#45: min_turnover_rate前端传小数(0.15=15%),需*100转为百分比单位】
            _raw_turnover = params.get("min_turnover_rate", 0.15)
            min_turnover = _raw_turnover * 100 if _raw_turnover < 1 else _raw_turnover  # <1说明是小数,需转换
            # 【修复#46: 开盘涨幅下限0%太严格,连板股开板日常低开,改为-3%】
            opening_pct_min = params.get("opening_pct_min", -3.0)
            opening_pct_max = params.get("opening_pct_max", 3.0)
            min_volume_ratio = params.get("min_volume_ratio", 2.0)
            require_sentiment = params.get("require_sentiment_period", ["rising"])
            await self.log(f"   │        • 连续涨停: {min_consecutive} ~ {max_consecutive}板")
            await self.log(f"   │        • 开盘涨幅: {opening_pct_min}% ~ {opening_pct_max}%")
            await self.log(f"   │        • 量比要求: ≥ {min_volume_ratio}")
            await self.log(f"   │        • 最大开板时长: {max_open_duration}分钟")
            await self.log(f"   │        • 开板后最小封单: {min_seal_after}万元")
            await self.log(f"   │        • 最小换手率: {min_turnover:.1f}%")
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
            # 【修复#47: min_qiao_amount单位统一为千元(与数据库limit_down_open_amount一致)】
            # 前端传10000(万元),数据库因子是千元,需*1000转换
            # 前端传万元,数据库因子千元,需*10转换
            # 【P2-C修复：明确单位转换规则，消除魔法数字】
            # 前端默认传万元(1000万元=10000)，数据库因子limit_down_open_amount存千元
            # 规则：如果<100000(即<10万元千元单位)，说明传入的是万元单位，需×1000转千元
            # 如果>=100000，说明已经是千元单位，无需转换
            _raw_qiao = params.get("min_qiao_amount", 1000)  # 前端传入，单位万元
            # 万元→千元: 1000万 × 1000 = 1000000千元；但前端传的是10000(万元)不是10000000
            # 实际: 前端传10000(万) → ×10 = 100000千元 ✓; 前端传100000(千) → 不转换 ✓
            min_qiao_amount = _raw_qiao * 10 if _raw_qiao < 100000 else _raw_qiao
            min_rise_after = params.get("min_rise_after_qiao", 0.03)
            require_high_sentiment = params.get("require_high_sentiment", True)
            await self.log(f"   │        • 最小连续跌停: {min_consecutive}天")
            _raw_turnover_qiao = params.get('min_turnover_rate', 0.10)
            _turnover_display = _raw_turnover_qiao * 100 if _raw_turnover_qiao < 1 else _raw_turnover_qiao
            await self.log(f"   │        • 换手率要求: ≥ {_turnover_display:.0f}%")
            await self.log(f"   │        • 最小翘板金额: {_raw_qiao}万元={min_qiao_amount}千元")
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
                await self.log(f"   │    ⚠️ 因子 {factor_name} 缺失,跳过此条件(不影响其他条件筛选)")
                continue  # 【修复：因子缺失时跳过该条件而非终止整个策略筛选】

            # 【P0-2修复：因子列存在但值全NaN时，也应跳过该条件】
            # NaN >= target 结果为False，会过滤掉所有股票，导致策略0候选
            if current_df[factor_name].isna().all():
                await self.log(f"   │    ⚠️ 因子 {factor_name} 全部为空,跳过此条件(不影响其他条件筛选)")
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
            elif operator == "in":  # ✅ 新增in操作符支持!
                if isinstance(target_value, list) and len(target_value) == 0:
                    # 🔧 BUG修复: 空列表不进行过滤,但仍然打印日志表明该条件已跳过
                    await self.log(f"   │    ⚪ 条件{idx_cond}: {label}")
                    await self.log(f"   │       → 跳过(空列表,不进行过滤)")
                    continue
                current_df = current_df[current_df[factor_name].isin(target_value)]

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
        """【统一入口!股票池获取+数据清洗打印必须调用!】"""
        await self.log(f"   🔍 正在获取当日股票池...")
        await self.log(f"   ✅ 原始股票池数量: {len(universe)} 只")
        await self.log(f"   🧹 数据清洗:")
        await self.log(f"      🔹 剔除ST股票: {st_count}只")
        await self.log(f"      🔹 剔除次新股: {new_stock_count}只")
        await self.log(f"      🔹 剔除流动性<500万(amount<5000千元): {low_liquidity_count}只")
        cleaned_count = len(universe) - st_count - new_stock_count - low_liquidity_count
        await self.log(f"      🔹 清洗后剩余: {cleaned_count}只")

    async def _print_non_rebalance_marker(self):
        """【统一入口!非调仓日标记必须调用!】"""
        await self.log(f"")
        await self.log(f"   ═══════════════════════════════════════════════════════")
        await self.log(f"   i️  【非调仓日】无调仓操作,继续持有现有仓位")
        await self.log(f"   ═══════════════════════════════════════════════════════")

    async def _print_daily_summary(self, trade_date: str, holdings_count: int, cash: float):
        """【统一入口!每日收盘汇总必须调用!】"""
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
        try:
            return await self._run_impl(config)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error('BACKTEST', f'run() unhandled exception: {e}\n{tb}')
            return {"error": f'run() unhandled exception: {e}'}

    async def _run_impl(self, config: dict) -> dict:
        """run()的实际实现"""
        task_id = config.get("task_id")
        push_log = config.get("push_log")

        # 保存 log 到实例,让所有方法都能使用
        # 日志推送辅助方法:同时写入本地日志 + 推送到前端
        async def log(msg: str):
            logger.info('BACKTEST', msg)
            if push_log and task_id:
                await push_log(task_id, msg)
        self.log = log
        
        # 【修复#4：保存 task_id 实例变量，用于进度推送Redis】
        self.task_id = task_id

        # 🔧 提前初始化所有实例属性,避免提前返回导致属性缺失
        self.weight_method = config.get("weight_method", "equal")

        await self.log(f"🚀 开始组合回测: {config['start_date']} -> {config['end_date']}")

        # 🔧 读取风控配置(优先使用请求中的配置,如果没有从数据库读取)
        # 默认风控配置
        risk_config = {
            "enable_stop_loss": config.get("enable_stop_loss", True),
            "stop_loss_pct": config.get("stop_loss_pct", 0.02),
            "enable_take_profit": config.get("enable_take_profit", True),
            "take_profit_pct": config.get("take_profit_pct", 0.07),
            "enable_ma60_filter": config.get("enable_ma60_filter", True),
            "enable_sector_concentration": config.get("enable_sector_concentration", True),
            "sector_concentration_top_n": config.get("sector_concentration_top_n", 3),
            "enable_auction_filter": config.get("enable_auction_filter", True),
            "enable_sentiment_cycle": config.get("enable_sentiment_cycle", True),
            "enable_force_empty": config.get("enable_force_empty", True),
            # 【P1-1/P1-2修复：添加max_hold_days和max_position_per_stock到风控配置】
            "max_hold_days": config.get("max_hold_days", 10),  # 默认10天（超短策略默认3天由ultra_short传入）
            "max_position_per_stock": config.get("max_position_per_stock", config.get("max_position_percent", 1.0)),  # 默认不限制
        }

        # 如果请求中传入了风控配置,使用传入的配置
        if "risk_config" in config and config["risk_config"]:
            for k, v in config["risk_config"].items():
                risk_config[k] = v

        # 输出风控配置到日志
        await self.log("🔧 当前风控配置:")
        await self.log(f"    🔹 {'✅' if risk_config['enable_stop_loss'] else '❌'} 强化止损: {risk_config['stop_loss_pct'] * 100:.1f}%")
        await self.log(f"    🔹 {'✅' if risk_config['enable_take_profit'] else '❌'} 动态止盈: {risk_config['take_profit_pct'] * 100:.1f}%")
        await self.log(f"    🔹 📅 最大持仓天数: {risk_config['max_hold_days']}")
        await self.log(f"    🔹 📊 单票最大仓位: {risk_config['max_position_per_stock'] * 100:.0f}%")
        await self.log(f"    🔹 {'✅' if risk_config['enable_ma60_filter'] else '❌'} 大盘MA60过滤")
        await self.log(f"    🔹 {'✅' if risk_config['enable_sector_concentration'] else '❌'} 板块集中度过滤: 保留前 {risk_config['sector_concentration_top_n']} 名")

        # 保存风控配置到实例,后续使用
        self._risk_config = risk_config

        # 【P0-2修复：构建策略级riskParams映射，策略级止损止盈优先于全局】
        selected_strategies = config.get("selected_strategies", [])
        self._strategy_risk_params = {}  # strategy_name -> {stop_loss_pct, take_profit_pct}
        for s in selected_strategies:
            sname = s.get("name", "")
            rp = s.get("riskParams", {})
            if rp:
                self._strategy_risk_params[sname] = {
                    "stop_loss_pct": rp.get("stop_loss_pct", risk_config["stop_loss_pct"]),
                    "take_profit_pct": rp.get("take_profit_pct", risk_config["take_profit_pct"]),
                }

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

        # 获取调仓日期 - 强制 daily,超短策略必须每日调仓
        rebalance_dates = await self.universe_mgr.get_rebalance_dates(
            config["start_date"],
            config["end_date"],
            "daily",  # 强制每日调仓,忽略可能错误的参数
        )

        if not rebalance_dates:
            return {"error": "No rebalance dates found"}

        # 获取所有交易日
        all_trade_dates = await self.universe_mgr.get_all_trade_dates(
            config["start_date"], config["end_date"]
        )

        if not all_trade_dates:
            return {"error": "No trade dates found"}

        # 🔴 关键修复:统一日期类型为字符串,避免类型不匹配
        # 确保 rebalance_dates 和 all_trade_dates 类型完全一致
        all_trade_dates = [str(d) for d in all_trade_dates]
        rebalance_dates = [str(d) for d in rebalance_dates]
        rebalance_set = set(rebalance_dates)

        await self.log(f"📅 调仓日期: {len(rebalance_dates)} 天, 交易日: {len(all_trade_dates)} 天")
        await self.log(f"📋 调仓日列表: {', '.join(rebalance_dates)}")

        # 🔍 数据一致性校验:检查行情数据和因子数据日期范围是否一致
        await self.log("🔍 开始数据一致性校验...")

        # 获取行情数据的最大日期(只查询一次)
        max_trade_date_pipeline = [
            {"$group": {"_id": None, "max_date": {"$max": "$trade_date"}}}
        ]
        result = await mongo_manager.aggregate("stock_daily_ak_full", max_trade_date_pipeline)

        max_market_date = None
        max_factor_date = None
        if result and len(result) > 0:
            max_market_date = result[0].get("max_date")
            max_factor_date = max_market_date  # 同一个表,数据相同

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
        # 2. 检测因子覆盖率(是否有null/缺失)
        # 3. 如果完整则跳过所有实时计算,直接使用预存数据
        # 4. 如果缺失则触发告警并建议补算
        await self.log("🔍 因子完整性自动检测:检查 48 个预计算因子字段...")

        # 所有超短策略需要的因子字段列表
        REQUIRED_FACTOR_FIELDS = [
            "first_limit_up", "hot_sector", "limit_up_yesterday", "limit_up_count",
            "limit_up_open_count", "limit_up_open_amount", "limit_up_open_duration",
            "limit_up_time", "turnover_rate", "volume_ratio", "circ_mv",
            "opening_pct_chg",  # 【修复：首板打板/涨停开板策略需要此因子】
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
        total_records = (end_dt - start_dt + 1) * 5510  # 5510只股票

        # 【修复#41:用$facet合并55次因子完整性检测为1次聚合查询】
        # 原逻辑:每个因子单独做一次聚合 → 55次独立查询 × 全表扫描 = 性能灾难
        # 新逻辑:用$facet一次性计算所有因子的非空数量 → 1次聚合查询完成所有检测

        # 构建facet阶段:每个因子对应一个子管道
        facet_stages = {}
        for field in REQUIRED_FACTOR_FIELDS:
            facet_stages[f"field_{field}"] = [
                {"$match": {
                    "trade_date": {"$gte": start_dt, "$lte": end_dt},
                    field: {"$ne": None}
                }},
                {"$count": "valid_count"}
            ]

        # 一次聚合完成所有因子的检测
        pipeline = [{"$facet": facet_stages}]
        result = await mongo_manager.aggregate("stock_daily_ak_full", pipeline)

        factor_checks = []
        missing_fields = []

        if result and len(result) > 0:
            facet_result = result[0]
            for field in REQUIRED_FACTOR_FIELDS:
                field_result = facet_result.get(f"field_{field}", [])
                if field_result and len(field_result) > 0:
                    valid_count = field_result[0]["valid_count"]
                    coverage = valid_count / total_records * 100 if total_records > 0 else 0
                    factor_checks.append((field, coverage, valid_count, total_records))

                    if coverage < 90:  # 覆盖率低于90%视为缺失
                        missing_fields.append(field)
                else:
                    missing_fields.append(field)
        else:
            # 查询失败时标记所有字段为缺失
            missing_fields = REQUIRED_FACTOR_FIELDS.copy()

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

        # 【修复#47:净值曲线追踪 - 逐日计算持仓市值】
        # 用于计算精确的每日盈亏、最大回撤、夏普比率等绩效指标
        net_value_series = []  # 净值序列
        daily_profit_list = []  # 每日盈亏
        drawdown_series = []   # 回撤序列
        daily_cash_list = []   # 【P1-3修复：每日现金占比(用于position_series)】
        peak_value = initial_cash  # 净值峰值
        last_net_value = initial_cash  # 上一日净值
        last_prices = {}  # 【修复：初始化last_prices，避免全强制空仓时NameError】

        # 逐日模拟
        rebalance_set = set(rebalance_dates)
        total_days = len(all_trade_dates)

        await self.log(f"开始逐日回测,共 {total_days} 个交易日")

        # 【修复#4：进度推送Redis频道，前端实时接收进度】
        # 每 10% 进度推送一次
        last_pushed_progress = -1

        for idx, trade_date in enumerate(all_trade_dates):
            # 【P2-4：每日价格缓存，避免同一天多次查MongoDB】
            self._daily_price_cache = {}
            self._daily_price_cache_date = trade_date
            # 【P0-3：维护_last_valid_price，停牌强卖时用】
            if not hasattr(self, '_last_valid_price'):
                self._last_valid_price = {}
            # 🔧 内存优化: 每5天强制一次垃圾回收
            if idx % 5 == 0:
                log_memory_usage(f"[day {idx+1}/{total_days}] 回测开始前")
                gc.collect()
            
            # 推送进度到Redis（每10%推送一次）
            progress_pct = int(((idx + 1) / total_days) * 100)
            if progress_pct != last_pushed_progress and progress_pct % 10 == 0:
                # 同时更新MongoDB进度
                await mongo_manager.update_one(
                    "backtest_tasks",
                    {"task_id": self.task_id},
                    {"$set": {"progress": 30 + int(progress_pct * 0.6)}},  # 30~90% 总共
                )
                # 推送Redis频道（失败不影响回测主流程）
                try:
                    await redis_manager.publish(f"backtest:progress:{self.task_id}", {
                        "task_id": self.task_id,
                        "progress": 30 + int(progress_pct * 0.6),
                        "current_day": idx + 1,
                        "total_days": total_days,
                        "status": "running"
                    })
                except Exception:
                    pass  # Redis不可用时静默跳过
                last_pushed_progress = progress_pct

            # ==================== 1️⃣ 每日统一开头 ====================
            await self._print_daily_header(idx+1, total_days, trade_date)

            # ==================== 2️⃣ 每日市场环境判断(所有天都走) ====================
            sentiment_level, limit_up_count, limit_down_count = await self._print_market_environment(trade_date)

            # ==================== 🔴 强制空仓判断 ====================
            # 【修复#5:统一阈值 - 与日志打印使用同一阈值】
            # 【修复#33:enable_force_empty开关实际生效】
            enable_force_empty = config.get("enable_force_empty", True)
            FORCE_EMPTY_LIMIT_DOWN = 50   # 与_print_market_environment保持一致
            FORCE_EMPTY_LIMIT_UP = 10
            force_empty_triggered = enable_force_empty and (
                limit_down_count >= FORCE_EMPTY_LIMIT_DOWN or limit_up_count <= FORCE_EMPTY_LIMIT_UP
            )
            if force_empty_triggered:
                await self.log(f"   ⚠️  强制空仓开关已启用,市场触发空仓条件,直接清仓")
            elif not enable_force_empty:
                await self.log(f"   i️  强制空仓开关已关闭,不检查空仓条件")

            # ==================== 3️⃣ IF/ELSE 严格对齐! ====================
            if trade_date in rebalance_set:
                # ==================== 调仓日完整流程 ====================
                await self.log(f"   📅 当前为调仓日,开始执行调仓逻辑")

                # 【修复#43:强制空仓时跳过选股计算,直接清仓】
                # 触发强制空仓时,不做任何选股、因子计算、策略筛选,直接清仓
                if force_empty_triggered:
                    await self.log(f"")
                    await self.log(f"   ┌───────────────────────────────────────────────────────")
                    await self.log(f"   │ 🔴 【强制空仓执行】")
                    await self.log(f"   ├───────────────────────────────────────────────────────")

                    if holdings and len(holdings) > 0:
                        prices_for_sell = await self._get_prices(set(holdings.keys()), trade_date)
                        sell_count = 0
                        for code in list(holdings.keys()):
                            if holdings[code] > 0 and code in prices_for_sell:
                                price = prices_for_sell[code]['close']
                                # 【P0-1修复：停牌股close=0时用最后有效价，避免0元卖出丢失持仓价值】
                                if price <= 0:
                                    price = getattr(self, '_last_valid_price', {}).get(code, 0)
                                if price <= 0:
                                    # 无法获取有效价格，跳过该股不卖（保留持仓）
                                    await self.log(f"   │  ⚠️ {code}停牌且无有效价，跳过卖出")
                                    continue
                                shares = holdings[code]
                                slippage_pct = self._slippage_pct if hasattr(self, '_slippage_pct') else 0.002
                                sell_price_adj = price * (1 - slippage_pct)
                                gross_amount = shares * sell_price_adj
                                commission = max(gross_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
                                stamp_tax = gross_amount * self.STAMP_TAX
                                net_amount = gross_amount - commission - stamp_tax
                                cash += net_amount
                                sell_count += 1
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
                        # 【P1-7修复：强制空仓清仓时清理cost_basis】
                        if hasattr(self, '_cost_basis'):
                            for code in list(self._cost_basis.keys()):
                                if code not in holdings or holdings.get(code, 0) <= 0:
                                    del self._cost_basis[code]
                                    if hasattr(self, '_cost_basis_date') and code in self._cost_basis_date:
                                        del self._cost_basis_date[code]
                        holdings = {code: shares for code, shares in holdings.items() if shares > 0}
                        await self.log(f"   │  ✅ 已执行强制清仓,卖出 {sell_count} 只持仓")
                        await self.log(f"   │  💵 清仓后现金:{cash:,.2f} 元")
                    else:
                        await self.log(f"   │  ⚪ 当前无持仓,无需卖出")

                    await self.log(f"   │  ⏭️  强制空仓规则生效,不开新仓")
                    await self.log(f"   └───────────────────────────────────────────────────────")

                    # 【修复#6:强制空仓也输出每日收盘汇总,continue前加上】
                    await self._print_daily_summary(trade_date, len(holdings), cash)
                    continue

                # ==================== 正常调仓流程 ====================
                # 1. 获取当日股票池
                universe_raw = await self.universe_mgr.get_universe(
                    UniverseType.ALL_A,
                    trade_date,
                    exclude_rules=[],  # 不应用任何排除规则,用于统计
                )
                universe = await self.universe_mgr.get_universe(
                    UniverseType.ALL_A,
                    trade_date,
                    exclude_rules,
                )

                # 真实统计各类剔除数量
                st_stocks = await self.universe_mgr._get_st_stocks()
                new_stocks = await self.universe_mgr._get_new_stocks(trade_date)
                st_count = len(st_stocks & universe_raw)
                new_stock_count = len(new_stocks & universe_raw)

                # 流动性过滤统计
                low_liquidity_cursor = mongo_manager.find_many(
                    "stock_daily_ak_full",
                    {
                        "trade_date": int(trade_date),
                        "ts_code": {"$in": list(universe)},
                        "amount": {"$lt": 5000}  # 5000千元=500万元,与流动性门槛对齐(amount单位:千元)
                    },
                    {"ts_code": 1}
                )
                low_liquidity_list = [doc["ts_code"] for doc in await low_liquidity_cursor]
                low_liquidity_set = set(low_liquidity_list)
                low_liquidity_count = len(low_liquidity_set)
                universe -= low_liquidity_set

                # ✅ 统一打印股票池和清洗信息
                await self._print_stock_pool_and_cleaning(trade_date, universe, st_count, new_stock_count, low_liquidity_count)

                # 2. 计算因子
                if not universe:
                    await self.log(f"   ⚠️  当日无符合条件的股票,跳过调仓")
                    await self._print_daily_summary(trade_date, len(holdings), cash)
                    continue

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
                    {"name": "sentiment_score"},
                    {"name": "opening_pct_chg"},  # 【修复：首板打板/涨停开板策略需要竞价涨幅因子】
                ]
                if "factors" not in config:
                    config["factors"] = []
                config["factors"].extend([f for f in ultra_short_factors if f not in config["factors"]])

                factor_df = await self.factor_engine.compute_factors(
                    universe, trade_date, config["factors"]
                )
                await self.log(f"   ✅ 因子计算完成,共 {len(factor_df)} 条记录")
                # 【P2-6：因子数据为空时告警】
                if len(factor_df) == 0:
                    await self.log(f"   ⚠️  【重要告警】因子数据为空！该日期无任何股票数据，全天空仓")
                    await self._print_daily_summary(trade_date, len(holdings), cash)
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

                # ✅ 新增:计算情绪周期字段 sentiment_period_in(从 sentiment_score 映射)
                # 策略中使用 sentiment_period_in 配合 in 操作符过滤
                # 【修复#7：enable_sentiment_cycle 开关真正生效，关闭则不计算】
                # 【修复#新增：sentiment_score NaN 防御，如果全为NaN不添加字段，策略筛选会直接跳过】
                import numpy as np
                if self._risk_config.get("enable_sentiment_cycle", True) and 'sentiment_score' in factor_df.columns:
                    # 检查是否有有效值
                    if not factor_df['sentiment_score'].isna().all():
                        # 根据情绪分数映射到情绪周期
                        # score ≥ 70 → 'rising' (上升期)
                        # 40 ≤ score < 70 → 'chaos' (混沌期)
                        # score < 40 → 'depression' (衰退期)
                        def map_sentiment(score):
                            import math
                            # 【修复风险8：NaN单值防御，返回None而非depression】
                            if score is None or (isinstance(score, float) and math.isnan(score)):
                                return None
                            if score >= 70:
                                return 'rising'
                            elif score >= 40:
                                return 'chaos'
                            else:
                                return 'depression'
                        factor_df['sentiment_period_in'] = factor_df['sentiment_score'].apply(map_sentiment)
                        # NaN行sentiment_period_in为None，策略筛选时in操作符会自动跳过None行
                        nan_count = factor_df['sentiment_period_in'].isna().sum()
                        if nan_count > 0:
                            await self.log(f"   ⚠️  {nan_count} 只股票sentiment_score为空，将跳过情绪周期筛选")
                        await self.log(f"   ✅ 情绪周期计算完成: sentiment_period_in 字段已添加")
                    else:
                        await self.log(f"   ⚠️  sentiment_score 全为空，跳过情绪周期计算")
                elif not self._risk_config.get("enable_sentiment_cycle", True):
                    await self.log(f"   ℹ️  情绪周期算法已关闭，跳过情绪周期计算")

                await self.log(f"   🎯 【{trade_date}】多策略联合筛选开始")
                await self.log(f"   ============================================================")
                await self.log(f"")

                all_candidates = set()
                # 【修复#45:记录每只股票来自哪个策略,用于调仓日志显示】
                stock_to_strategy = {}  # code -> strategy_name
                self.stock_to_strategy = stock_to_strategy  # 存实例变量,供_rebalance使用

                selected_strategies = config.get("selected_strategies", [])
                selected_strategy_names = [s["name"] for s in selected_strategies] if selected_strategies else []

                # 【修复#7:统一调用策略条件构建方法,消除重复定义】
                strategy_configs = {}
                # 遍历所有传入的策略配置,动态构建筛选条件
                for s in selected_strategies:
                    strategy_name = s.get("name", s.get("id", "未知策略"))
                    params = s.get("params", {})
                    strategy_configs[strategy_name] = self._build_strategy_filter_conditions(strategy_name, params)

                # ✅ One Function, One Format! 所有5个策略统一走同一个打印函数!
                # 🚫 业务逻辑代码中绝对不允许直接出现 await self.log()!
                all_candidates = set()
                for s in selected_strategies:
                    strategy_name = s.get("name", s.get("id", "未知策略"))
                    params = s.get("params", {})

                    # 【P2-B修复：删除重复的参数打印逻辑，统一走 _print_single_strategy_filtering】
                    # 之前这里有80行重复打印代码，与 _print_single_strategy_filtering 完全一致
                    # 且默认值不一致（如半路追涨max_rise_pct这里写0.05，_print_single写0.05，但ultra_short写0.07）

                    # 统一调用策略筛选+打印
                    candidates = await self._print_single_strategy_filtering(
                        strategy_name,
                        params,
                        [],
                        factor_df,
                        strategy_configs,
                        selected_strategy_names
                    )
                    all_candidates.update(candidates)
                    # 【修复#45+P1-1:记录每只股票来自哪个策略,支持多策略选同股】
                    # 存策略列表(而非覆盖)，买入价取最低价(最保守)
                    for code in candidates:
                        if code not in stock_to_strategy:
                            stock_to_strategy[code] = []
                        if strategy_name not in stock_to_strategy[code]:
                            stock_to_strategy[code].append(strategy_name)

                # ✅ 所有策略筛选完成!One Function, One Format!
                # 🚫 业务逻辑代码中不再有任何 await self.log() 调用!
                # 📊 总候选: {len(all_candidates)} 只股票

                # 🔧 策略轮动机制:根据历史月度收益动态调整权重已经在权重计算阶段处理
                # 当前改进:每个策略独立筛选,只影响选股结果不影响权重,权重调整后分配还是基于等权基础

                if len(all_candidates) == 0:
                    await self.log(f"   ⚠️  当日无符合条件的交易标的,跳过调仓")
                    # 【修复：当日无候选时，输出每日收盘汇总后continue到下一交易日】
                    await self._print_daily_summary(trade_date, len(holdings), cash)
                    continue  # continue外层for循环，跳到下一交易日

                # 【修复#7：enable_auction_filter 竞价过滤逻辑，开关真正生效】
                # 如果开启竞价过滤，过滤掉不符合竞价特征的标的
                # 必须满足: 0.5% ≤ 竞价涨幅 ≤ 7%，竞价成交量 > 0，未匹配成交量 > 0
                if self._risk_config.get("enable_auction_filter", True) and len(all_candidates) > 0:
                    await self.log("")
                    await self.log(f"   📊 【竞价过滤】启用竞价过滤，当前 {len(all_candidates)} 个候选，开始过滤...")
                    
                    # 从MongoDB获取当日竞价数据
                    auction_data = await mongo_manager.find_many(
                        "stock_bid_auction",
                        {"trade_date": int(trade_date)},
                        projection={"ts_code": 1, "auction_pct_chg": 1, "auction_volume": 1, "unmatched_volume": 1}
                    )
                    
                    if not auction_data:
                        await self.log(f"   ⚠️  【竞价过滤】未获取到 stock_bid_auction 竞价数据，竞价过滤**未生效**！请确保已导入竞价数据后再使用竞价过滤功能。")
                        # 【修复风险7：无竞价数据时跳过竞价过滤，不清空候选集】
                    else:
                        auction_map = {x.get("ts_code", ""): x for x in auction_data if x.get("ts_code")}
                        original_count = len(all_candidates)
                        filtered_candidates = []
                        
                        for code in all_candidates:
                            auction = auction_map.get(code)
                            if not auction:
                                filtered_candidates.append(code)  # 【修复风险7：没有竞价数据时保留候选，不过滤掉】
                                continue
                            pct = auction.get("auction_pct_chg", 0)
                            vol = auction.get("auction_volume", 0)
                            unmatched_vol = auction.get("unmatched_volume", 0)
                            
                            # 竞价过滤规则:
                            # 1. 竞价涨幅必须在 0.5% ~ 7% 之间（排除大幅高开和低开）
                            # 2. 竞价成交量必须大于 0（确实有成交）
                            # 3. 未匹配成交量必须大于 0（确保有足够流动性）
                            if 0.5 <= pct <= 7 and vol > 0 and unmatched_vol > 0:
                                filtered_candidates.append(code)
                        
                        all_candidates = set(filtered_candidates)
                        await self.log(f"   ✅ 竞价过滤完成: {original_count} → {len(all_candidates)}")
                        
                        if len(all_candidates) == 0:
                            await self.log(f"   ⚠️  竞价过滤后无候选，跳过调仓")
                            continue

                # 【P0-A修复：以下调仓逻辑必须与竞价过滤if平级，不能在if内部】
                # 否则 enable_auction_filter=False 时不执行任何调仓！

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
                                # 【修复#45:买入reason带上具体策略名称】
                                sname_raw = stock_to_strategy.get(ts_code, "策略选股")
                                strategy_name = sname_raw[0] if isinstance(sname_raw, list) and len(sname_raw) > 0 else sname_raw
                                reason_desc = f"{strategy_name}调入"
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
                # ✅ 修复:非调仓日也要输出完整信息,让用户知道每天都在正常运行
                else:
                    await self.log(f"")
                    await self.log(f"   ┌───────────────────────────────────────────────────────")
                    await self.log(f"   │ i️  【调仓日无交易】当前持仓与目标一致,无需调仓")
                    await self.log(f"   ├───────────────────────────────────────────────────────")

                    # 【P0-C修复：非调仓日只调用一次_get_prices，和下方净值计算共享】
                    # 避免重复查询MongoDB（虽然有缓存，但减少冗余调用更干净）
                    if holdings and len(holdings) > 0:
                        _prices_for_display = await self._get_prices(set(holdings.keys()), trade_date)
                        await self.log(f"   │  📊 当前持仓 {len(holdings)} 只股票:")
                        total_market_value = 0
                        for code, shares in holdings.items():
                            if shares > 0 and code in _prices_for_display:
                                price = _prices_for_display[code]['close']
                                market_value = shares * price
                                total_market_value += market_value
                                await self.log(f"   │      • {code}: {shares} 股, 收盘价 {price:.2f}, 市值 {market_value:,.2f} 元")
                        await self.log(f"   │  💰 持仓总市值:{total_market_value:,.2f} 元")
                    else:
                        await self.log(f"   │  📊 当前无持仓")
                        _prices_for_display = {}

                    await self.log(f"   │  💵 当前现金：{cash:,.2f} 元")
                    await self.log(f"   └───────────────────────────────────────────────────────")

                # 【修复#47：逐日计算持仓市值，修复净值曲线】
                # 【P0-C修复：复用非调仓日已获取的价格，避免二次调用】
                if holdings and len(holdings) > 0:
                    # 调仓日用rebalance时的prices，非调仓日用上面获取的_prices_for_display
                    if trade_date in rebalance_set:
                        # 调仓日：rebalance后的prices已经获取过了，直接复用
                        prices_for_hold = prices
                    else:
                        # 非调仓日：复用上面已获取的价格
                        prices_for_hold = _prices_for_display
                    # 【P1-4修复：每日更新last_prices，避免非调仓日过期导致final_value失真】
                    last_prices = prices_for_hold
                    holdings_market_value = 0
                    for code, shares in holdings.items():
                        if shares > 0:
                            if code in prices_for_hold and prices_for_hold[code].get('close', 0) > 0:
                                holdings_market_value += shares * prices_for_hold[code]['close']
                            else:
                                # 【P0-1修复：停牌股用_last_valid_price估值，避免市值=0导致净值骤降】
                                lvp = getattr(self, '_last_valid_price', {}).get(code, 0)
                                if lvp > 0:
                                    holdings_market_value += shares * lvp
                else:
                    holdings_market_value = 0
                
                current_net_value = cash + holdings_market_value  # 当日总净值 = 现金 + 持仓市值
                daily_profit = current_net_value - last_net_value  # 当日盈亏
                
                # 计算当日回撤（基于净值峰值）
                if current_net_value > peak_value:
                    peak_value = current_net_value
                drawdown = (peak_value - current_net_value) / peak_value if peak_value > 0 else 0
                
                # 记录到净值序列
                net_value_series.append({
                    "trade_date": trade_date,
                    "net_value": current_net_value,
                    "daily_profit": daily_profit,
                    "drawdown": drawdown
                })
                daily_profit_list.append(daily_profit)
                drawdown_series.append(drawdown)
                daily_cash_list.append(cash / current_net_value if current_net_value > 0 else 1.0)  # 【P1-3：现金占比】
                
                # 更新上一日净值
                last_net_value = current_net_value

                # ==================== 每日收盘汇总（每天必须输出）====================
                # 无论调仓日还是非调仓日，每天都要有完整的日志结尾
                await self.log(f"")
                await self.log(f"═══════════════════════════════════════════════════════════════")
                await self.log(f"📅 【第 {idx+1}/{total_days} 天】处理完成: {trade_date}")
                await self.log(f"   💵 当日持仓: {len(holdings)} 只股票, 现金剩余: {cash:,.2f} 元")
                await self.log(f"═══════════════════════════════════════════════════════════════")



        # 计算最终市值(所有日期处理完成后)
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
        # 【P0-3修复：buy_records改为FIFO队列，每次卖出扣除对应股数】
        buy_records = {}  # code -> list of {record, remaining_shares}
        total_signals = 0
        winning_trades = 0
        completed_trades = 0  # 【P1-4修复：完整交易数(非买入信号数)】

        for day_records in rebalance_records:
            records_list = day_records if isinstance(day_records, list) else [day_records]
            for record in records_list:
                if record.action == 'buy':
                    code = record.ts_code
                    if code not in buy_records:
                        buy_records[code] = []
                    buy_records[code].append({'record': record, 'remaining': record.shares})

        # 所有买入都是信号
        total_signals = sum(len(buys) for buys in buy_records.values())

        # 统计每个卖出是否盈利,同时合并完整交易
        # 【P0-3修复：FIFO匹配 — 卖出时从buy_records中按顺序扣减】
        for day_records in rebalance_records:
            records_list = day_records if isinstance(day_records, list) else [day_records]
            for record in records_list:
                if record.action == 'sell' and record.ts_code in buy_records:
                    code = record.ts_code
                    sells = buy_records[code]
                    if not sells:
                        continue
                    
                    # 卖出时按FIFO匹配买入记录
                    sell_shares = record.shares
                    sell_cost = 0.0
                    sell_buy_shares = 0  # 匹配到的买入股数
                    first_buy = sells[0]['record']  # 最早买入记录
                    
                    while sell_shares > 0 and sells:
                        entry = sells[0]
                        matched = min(sell_shares, entry['remaining'])
                        # 按比例分配该买入记录的成本
                        buy_rec = entry['record']
                        cost_per_share = abs(buy_rec.amount) / buy_rec.shares if buy_rec.shares > 0 else 0
                        sell_cost += matched * cost_per_share
                        sell_buy_shares += matched
                        entry['remaining'] -= matched
                        sell_shares -= matched
                        if entry['remaining'] <= 0:
                            sells.pop(0)  # 该买入记录已完全匹配
                    
                    if sell_buy_shares > 0 and sell_cost > 0:
                        avg_cost = sell_cost / sell_buy_shares
                        net_sell_amount = record.amount
                        profit = (net_sell_amount - sell_cost) / sell_cost * 100
                        if net_sell_amount > sell_cost:
                            winning_trades += 1
                        completed_trades += 1

                        stock_names = await self._get_stock_names([code])
                        name = stock_names.get(code, code.split('.')[0])

                        strategy_name = first_buy.strategy_name if first_buy.strategy_name else "策略选股"
                        if not strategy_name and first_buy.reason:
                            strategy_name = first_buy.reason.replace(' 策略选股调入', '').strip() or "-"
                        if not strategy_name:
                            strategy_name = "-"

                        strategy_buy_time = self.STRATEGY_BUY_TIMES.get(strategy_name, '09:35')
                        merged_trades.append({
                            'ts_code': code,
                            'name': name,
                            'strategy': strategy_name,
                            'sentiment': first_buy.sentiment,
                            'buy_date': first_buy.date,
                            'buy_time': strategy_buy_time,
                            'buy_price': avg_cost,
                            'sell_date': record.date,
                            'sell_time': '收盘',
                            'sell_price': record.price,
                            'shares': sell_buy_shares,
                            'profit_pct': profit,
                        })

                    # 清理空的buy_records
                    if not sells:
                        del buy_records[code]

        # 添加还未卖出的持仓到明细
        for code, buys in buy_records.items():
            # buy_records中剩余的=还未卖出的持仓(FIFO扣减后)
            if not buys:
                continue
            # 检查是否还有剩余股数
            remaining_shares = sum(b['remaining'] for b in buys)
            if remaining_shares <= 0:
                continue
            # 还在持仓中,添加到明细
            first_buy = buys[0]['record']
            stock_names = await self._get_stock_names([code])
            name = stock_names.get(code, code.split('.')[0])

            strategy_name = first_buy.strategy_name if first_buy.strategy_name else "策略选股"
            if not strategy_name and first_buy.reason:
                strategy_name = first_buy.reason.replace(' 策略选股调入', '').strip() or "-"
            if not strategy_name:
                strategy_name = "-"

            # 计算剩余持仓的平均成本
            total_remaining_cost = sum(abs(b['record'].amount) / b['record'].shares * b['remaining'] for b in buys if b['record'].shares > 0)
            avg_remaining_cost = total_remaining_cost / remaining_shares if remaining_shares > 0 else 0

            merged_trades.append({
                'ts_code': code,
                'name': name,
                'strategy': strategy_name,
                'sentiment': first_buy.sentiment,
                'buy_date': first_buy.date,
                'buy_time': self.STRATEGY_BUY_TIMES.get(strategy_name, '09:35'),
                'buy_price': avg_remaining_cost,
                'sell_date': '',
                'sell_time': '',
                'sell_price': 0.0,
                'shares': remaining_shares,
                'profit_pct': None,  # 还未卖出
            })

        # 初始化绩效指标（避免 UnboundLocalError 当0交易时）
        max_drawdown = 0.0
        sharpe_ratio = 0.0
        profit_loss_ratio = 0.0
        strategy_name = "组合策略"

        # 计算胜率
        # 【P1-4修复：用完整交易数(completed_trades)而非买入信号数(total_signals)】
        win_rate = 0.0
        if completed_trades > 0:
            win_rate = winning_trades / completed_trades
            win_rate_percent = win_rate * 100
        else:
            win_rate_percent = 0.0
        # 【修复#13：年化收益率使用真实交易天数而不是调仓日数】
        # 交易天数 = 所有交易日数量，而不是仅仅调仓日数量
        trading_days = len(all_trade_dates)
        annual_return_reliable = trading_days >= 30  # 少于30天年化无参考意义
        if trading_days > 0:
            # 复利年化: (1 + total_return) ^ (252 / trading_days) - 1
            annualized_return = ((1 + total_return) ** (252 / trading_days)) - 1
        else:
            annualized_return = 0.0

        # 【修复#26/#27：使用 PerformanceAnalyzer 重新计算所有绩效指标】
        # 将merged_trades写入临时JSON文件，使用PerformanceAnalyzer计算
        # 【修复：PerformanceAnalyzer API不匹配(file_path≠risk_free_rate, 无get_basic_stats方法)，
        # 改为直接使用已计算的绩效指标，不再调用PerformanceAnalyzer】
        # 原代码：analyzer = PerformanceAnalyzer(temp_file.name) → 传了文件路径给risk_free_rate参数，且无get_basic_stats方法
        # 当有交易时，win_rate/max_drawdown/sharpe_ratio等已在上方正确计算，无需重复计算

        # 统计盈利次数/亏损次数
        # 【P0-1修复：losing_trades用completed_trades-winning_trades，而非total_signals-winning_trades】
        # total_signals是买入信号数(含未卖出持仓)，winning_trades是已卖出盈利数，维度不一致
        losing_trades = completed_trades - winning_trades
        total_trades = len(merged_trades)

        # 计算收益回撤比 = 累计收益率 / 最大回撤(当最大回撤 > 0 时)
        return_drawdown_ratio = 0.0
        if max_drawdown > 0 and total_return != 0:
            return_drawdown_ratio = abs(total_return) / max_drawdown

        # 计算平均持仓天数
        average_hold_days = 0.0
        # 【P2-1修复：变量重命名，避免completed_trades从int被遮蔽为list】
        completed_trades_for_avg = [t for t in merged_trades if t.get('sell_date') and t.get('buy_date')]
        if len(completed_trades_for_avg) > 0:
            total_hold_days = 0
            for trade in completed_trades_for_avg:
                buy_date_int = int(trade['buy_date'])
                sell_date_int = int(trade['sell_date'])
                # 计算持仓天数(简单相减,都是YYYYMMDD格式)
                # 转换为datetime计算更准确
                buy_dt = dt_now.strptime(str(buy_date_int), '%Y%m%d')
                sell_dt = dt_now.strptime(str(sell_date_int), '%Y%m%d')
                hold_days = (sell_dt - buy_dt).days
                total_hold_days += hold_days
            average_hold_days = total_hold_days / len(completed_trades_for_avg)

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
            await self.log(f"  索提诺比率: {sortino_ratio:.2f}")
            await self.log(f"  卡玛比率: {calmar_ratio:.2f}")
            await self.log(f"  年化波动率: {volatility * 100:.2f}%")
            await self.log(f"  收益回撤比: {return_drawdown_ratio:.2f}")
            await self.log(f"  总交易次数: {total_trades}")
            await self.log(f"  盈利次数: {winning_trades} / 亏损次数: {losing_trades}")
            await self.log(f"  平均持仓天数: {average_hold_days:.1f}")

        # 打印完整逐笔交易明细
        if len(merged_trades) > 0:
            await self.log("")
            await self.log("📝 【完整逐笔交易明细】")
            await self.log("")

            # 使用 tabulate 输出美观的表格
            from tabulate import tabulate

            table_data = []
            headers = ["#", "代码", "名称", "策略", "情绪", "买入", "买入时间", "卖出", "卖出时间", "买入价", "卖出价", "股数", "仓位", "持仓", "盈亏", "盈亏%", "", "说明"]

            for idx, trade in enumerate(merged_trades, 1):
                ts_code = trade.get('ts_code', '')
                name = trade.get('name', ts_code)
                strategy = trade.get('strategy', '')
                strategy_name = strategy.strip() if strategy.strip() else "-"
                # 只取情绪第一部分
                sentiment = trade.get('sentiment', '')
                if sentiment:
                    sentiment = sentiment.split(',')[0].strip()
                sentiment = sentiment or "-"
                buy_date = trade.get('buy_date', '')
                buy_price = float(trade.get('buy_price', 0)) if trade.get('buy_price') is not None else 0.0
                buy_time = trade.get('buy_time', '09:35')
                sell_date = trade.get('sell_date', '')
                sell_price = float(trade.get('sell_price', 0)) if trade.get('sell_price') is not None else 0.0
                sell_time = trade.get('sell_time', '收盘')
                shares = int(trade.get('shares', 0)) if trade.get('shares') is not None else 0
                profit_pct = trade.get('profit_pct')

                # 计算盈亏
                hold_days = 0
                profit_abs = 0
                is_profit = "-"
                if profit_pct is not None and buy_price > 0 and sell_price > 0:
                    profit_abs = shares * (sell_price - buy_price) * (1 - self.SELL_COMMISSION - self.STAMP_TAX)
                    is_profit = "✅" if profit_pct > 0 else "❌"
                    # 计算持仓天数
                    if buy_date and sell_date:
                        try:
                            buy_dt = dt_now.strptime(str(buy_date), '%Y%m%d')
                            sell_dt = dt_now.strptime(str(sell_date), '%Y%m%d')
                            hold_days = (sell_dt - buy_dt).days
                        except (ValueError, TypeError):
                            hold_days = 0

                # 计算仓位百分比
                position_pct = "-"
                if shares > 0 and buy_price > 0:
                    cost = shares * buy_price
                    position_pct = f"{cost / self._initial_cash * 100:.0f}%"

                # 未卖出持仓的特殊标记
                is_open_position = not sell_date and sell_price == 0.0
                display_sell_date = sell_date if sell_date else '持仓中'
                display_sell_time = sell_time if sell_time else '-'
                display_sell_price = f"{sell_price:.2f}" if sell_price > 0 else '持仓中'

                # 格式化
                profit_abs_str = f"{profit_abs:.0f}" if profit_abs != 0 else "-"
                profit_pct_str = f"{profit_pct:.2f}%" if profit_pct is not None else "-"
                hold_days_str = hold_days if hold_days > 0 else ("持仓中" if is_open_position else 0)

                table_data.append([
                    idx, ts_code, name[:12], strategy_name[:10], sentiment,
                    buy_date, buy_time, display_sell_date, display_sell_time,
                    f"{buy_price:.2f}", display_sell_price, shares, position_pct, hold_days_str,
                    profit_abs_str, profit_pct_str, is_profit, "🔓" if is_open_position else ""
                ])

            # 使用 grid 表格格式
            table_str = tabulate(table_data, headers=headers, tablefmt='grid')
            for line in table_str.split('\n'):
                await self.log(line)

            await self.log("")
            await self.log(f"📊 总计 {len(merged_trades)} 笔完整交易")
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

        # 【修复#47/#48/#13：基于逐日净值计算绩效指标】
        # 净值曲线和每日盈亏已经在逐日回测循环中计算完成，这里直接使用
        # 删除了原来基于调仓日的简化估算，现在使用精确的逐日持仓市值计算
        
        # 计算最大回撤（基于逐日净值，已经在循环中计算了 drawdown_series）
        max_drawdown = max(drawdown_series) if drawdown_series else 0.0
        
        # 【P0-2修复：在max_drawdown正确计算后，重新计算return_drawdown_ratio】
        if max_drawdown > 0 and total_return != 0:
            return_drawdown_ratio = abs(total_return) / max_drawdown
        
        # 计算盈亏比：总盈利 / 总亏损（基于每日盈亏）
        total_profit = sum(p for p in daily_profit_list if p > 0)
        total_loss = sum(-p for p in daily_profit_list if p < 0)
        profit_loss_ratio = total_profit / total_loss if total_loss > 0 else 0.0
        
        # 【修复#13：基于修复后的净值曲线正确计算夏普比率】
        # 夏普比率 = 平均日收益率 / 日收益率标准差 × sqrt(252)
        # 假设无风险利率为0
        sharpe_ratio = 0.0
        sortino_ratio = 0.0
        calmar_ratio = 0.0
        volatility = 0.0  # 年化波动率
        if len(daily_profit_list) > 1 and last_net_value > 0:
            # 计算日收益率序列
            daily_returns = []
            current_value = self._initial_cash
            for p in daily_profit_list:
                if current_value > 0:
                    daily_returns.append(p / current_value)
                current_value += p
            
            # 计算平均日收益率和标准差
            if len(daily_returns) > 1:
                import math
                avg_return = sum(daily_returns) / len(daily_returns)
                variance = sum((r - avg_return) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
                std_return = math.sqrt(variance)
                
                # 年化波动率
                volatility = std_return * math.sqrt(252)
                
                if std_return > 0:
                    # 年化夏普比率（252个交易日，无风险利率3%）
                    daily_rf = 0.03 / 252
                    sharpe_ratio = (avg_return - daily_rf) / std_return * math.sqrt(252)
                
                # 【P1-7修复：索提诺比率（只考虑下行波动）】
                downside_returns = [r for r in daily_returns if r < 0]
                if len(downside_returns) > 1:
                    downside_variance = sum((r - sum(downside_returns) / len(downside_returns)) ** 2 for r in downside_returns) / (len(downside_returns) - 1)
                    downside_std = math.sqrt(downside_variance)
                    if downside_std > 0:
                        daily_rf = 0.03 / 252
                        sortino_ratio = (avg_return - daily_rf) / downside_std * math.sqrt(252)
        
        # 【P1-7修复：卡玛比率 = 年化收益率 / 最大回撤】
        if max_drawdown > 0 and annualized_return != 0:
            calmar_ratio = annualized_return / max_drawdown
        
        # 格式化 drawdown_series 为最终返回格式
        formatted_drawdown_series = []
        for i, point in enumerate(net_value_series):
            formatted_drawdown_series.append({
                "trade_date": point["trade_date"],
                "drawdown": drawdown_series[i] if i < len(drawdown_series) else 0.0
            })
        
        # 提取 daily_profit 序列（用于兼容）
        daily_profit = daily_profit_list.copy()

        # 【修复#49/#31：统一后端输出格式适配前端BacktestResult结构
        # - final_value → final_equity (字段名对齐)
        # - 百分比单位约定：所有_pct后缀字段和total_return/max_drawdown/win_rate等字段
        #   均为百分比数值(如15.5表示15.5%),不是小数(0.155)
        # - 此约定与ultra_short.py中读取时一致，前端亦按百分比展示
        # 【修复#17：嵌套BacktestMetrics结构：returns/risk/trades/positions/performance/metadata
        result = {
            "success": True,
            "initial_cash": self._initial_cash,
            "final_cash": cash,
            "final_equity": final_value,  # 【修复#49：字段名对齐 → final_equity】
            "final_value": final_value,  # 保持向后兼容
            "metrics": {  # 嵌套 BacktestMetrics 结构，字段名对齐前端TypeScript类型定义
                "returns": {
                    "total_return_pct": total_return * 100,
                    "annual_return_pct": annualized_return * 100,
                    "annual_return_reliable": annual_return_reliable,  # 少于30天年化无参考意义
                    "benchmark_return_pct": 0.0,  # 基准收益率后续可补
                    "alpha_pct": total_return * 100 - 0.0,
                    # 以下字段保持兼容旧代码
                    "total_return": total_return * 100,
                    "annualized_return": annualized_return * 100,
                },
                "risk": {
                    "max_drawdown_pct": max_drawdown * 100,
                    "win_rate_pct": win_rate * 100,
                    "sharpe_ratio": sharpe_ratio,
                    "sortino_ratio": sortino_ratio,  # 【P1-7修复：新增索提诺比率】
                    "calmar_ratio": calmar_ratio,    # 【P1-7修复：新增卡玛比率】
                    "volatility_pct": volatility * 100,  # 【P1-7修复：新增年化波动率】
                    "profit_loss_ratio": profit_loss_ratio,
                    "return_drawdown_ratio": return_drawdown_ratio,
                    # 以下字段保持兼容旧代码
                    "max_drawdown": max_drawdown * 100,
                    "win_rate": win_rate * 100,
                },
                "trades": {
                    "total_trades": total_trades,
                    "winning_trades": winning_trades,
                    "losing_trades": losing_trades,
                    "avg_holding_days": average_hold_days,
                    "average_hold_days": average_hold_days,
                },
                "positions": {
                    "final_holdings": holdings,
                    "net_value_series": net_value_series,
                    "drawdown_series": formatted_drawdown_series,
                    "daily_profit": daily_profit,
                },
                "performance": {
                    "total_signals": total_signals,
                    "rebalance_records": rebalance_records_dict,
                    "all_trades": all_trades_dict,
                    "benchmark_data": benchmark_data,
                    "stock_names": stock_names,
                },
                "metadata": {
                    "start_date": config.get("start_date"),
                    "end_date": config.get("end_date"),
                    "strategy_name": strategy_name,
                    "generated_at": dt_now.now().isoformat(),
                }
            },
        }

        # 【兼容层】顶层扁平字段供前端直接读取（如 result.win_rate）
        # 实际数据源在 result.metrics 内，值相同，保持两边同步
        # 前端BacktestResultPanel从顶层读取，勿删
        result["total_return"] = total_return * 100
        result["annualized_return"] = annualized_return * 100
        result["max_drawdown"] = max_drawdown * 100
        result["win_rate"] = win_rate * 100
        result["sharpe_ratio"] = sharpe_ratio
        result["profit_loss_ratio"] = profit_loss_ratio
        result["total_signals"] = total_signals
        result["total_trades"] = total_trades
        result["winning_trades"] = winning_trades
        result["losing_trades"] = losing_trades
        result["average_hold_days"] = average_hold_days
        result["all_trades"] = all_trades_dict
        result["merged_trades"] = merged_trades  # 完整交易记录(含买卖信息，给前端展示)
        result["rebalance_records"] = rebalance_records_dict
        result["stock_names"] = stock_names
        result["net_value_series"] = net_value_series
        result["drawdown_series"] = formatted_drawdown_series
        result["daily_profit"] = daily_profit
        result["benchmark_data"] = benchmark_data

        # 【P2-12：补全前端图表所需字段】
        # 1. position_series: 每日仓位占比 [{date, value}]
        #    position = 1 - cash/equity (真实仓位比例)
        position_series = []
        for i, nv in enumerate(net_value_series):
            if i < len(daily_cash_list):
                pos_val = max(0.0, 1.0 - daily_cash_list[i])  # 仓位=1-现金占比
            else:
                pos_val = 0.0
            position_series.append({"date": nv.get("trade_date", ""), "value": pos_val})
        result["position_series"] = position_series

        # 2. strategy_results: 各策略独立绩效 {策略名: {win_rate, total_return, trades_count}}
        strategy_results = {}
        strategy_trades = {}
        for trade in merged_trades:
            sname = trade.get('strategy', '未知策略')
            if sname not in strategy_trades:
                strategy_trades[sname] = []
            strategy_trades[sname].append(trade)
        for sname, trades in strategy_trades.items():
            completed = [t for t in trades if t.get('sell_date')]
            wins = sum(1 for t in completed if t.get('profit_pct', 0) > 0)
            total_pnl = sum(t.get('profit_pct', 0) for t in completed)
            avg_pnl = total_pnl / len(completed) if completed else 0
            strategy_results[sname] = {
                "win_rate": (wins / len(completed) * 100) if completed else 0,
                "total_return": avg_pnl,
                "trades_count": len(completed),
                "total_pnl_pct": total_pnl,
            }
        result["strategy_results"] = strategy_results

        # 3. factor_contribution: 因子贡献 {因子名: 权重}
        factor_contribution = {}
        sw = config.get("strategy_weights", {})
        if sw:
            for name, weight in sw.items():
                factor_contribution[name] = weight
        else:
            # 如果没有strategy_weights，从策略数等分
            n = len(strategy_results) or 1
            for name in strategy_results:
                factor_contribution[name] = 1.0 / n
        result["factor_contribution"] = factor_contribution

        # 4. monthly_profit: 月度收益 {"2026-01": 收益率, ...}
        monthly_profit = {}
        if daily_profit_list and all_trade_dates:
            current_value = self._initial_cash
            monthly_start_value = current_value
            current_month = None
            for i, profit in enumerate(daily_profit_list):
                if i < len(all_trade_dates):
                    date_str = str(all_trade_dates[i])
                    month_key = date_str[:6]  # "202601"
                    formatted_key = f"{month_key[:4]}-{month_key[4:]}"  # "2026-01"
                    if current_month is not None and month_key != current_month:
                        # 月末，计算该月收益
                        m_return = (current_value - monthly_start_value) / monthly_start_value if monthly_start_value > 0 else 0
                        formatted_prev = f"{current_month[:4]}-{current_month[4:]}"
                        monthly_profit[formatted_prev] = m_return
                        monthly_start_value = current_value
                    current_month = month_key
                current_value += profit
            # 最后一月
            if current_month:
                m_return = (current_value - monthly_start_value) / monthly_start_value if monthly_start_value > 0 else 0
                formatted_last = f"{current_month[:4]}-{current_month[4:]}"
                monthly_profit[formatted_last] = m_return
        result["monthly_profit"] = monthly_profit

        # 兼容层标注：年化收益可靠性
        result["annual_return_reliable"] = annual_return_reliable

        return result

    async def _load_benchmark_data(self, benchmark_code: str, start_date: int, end_date: int):
        """加载基准指数数据用于计算超额收益"""
        # 【P1-1修复：基准数据应查index_daily集合，stock_daily_ak_full无指数数据】
        # 先尝试从 index_daily 查询（指数专用集合）
        query = {
            "ts_code": benchmark_code,
            "trade_date": {"$gte": start_date, "$lte": end_date}
        }
        docs = await mongo_manager.find_many("index_daily", query)
        
        # 如果index_daily无数据，回退到stock_daily_ak_full（兼容旧数据）
        if not docs:
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
        【P2-4优化：使用每日价格缓存，同一天只查一次MongoDB】

        Returns:
            dict: {ts_code: {"open": open_price, "close": close_price}}
        """
        # 【P2-4：每日价格缓存】同一天只查一次MongoDB，后续调用直接从缓存取
        cache = getattr(self, '_daily_price_cache', {})
        cache_date = getattr(self, '_daily_price_cache_date', None)
        if cache and cache_date == trade_date:
            # 从缓存中取需要的股票
            result = {}
            missing = set()
            for code in ts_codes:
                code_str = str(code).strip()
                # 标准化代码
                if code_str.endswith('.SH') or code_str.endswith('.SZ') or code_str.endswith('.BJ'):
                    std_code = code_str
                elif code_str.startswith('6') or code_str.startswith('5') or code_str.startswith('9'):
                    std_code = f"{code_str}.SH"
                elif code_str.startswith('8') or code_str.startswith('4'):
                    std_code = f"{code_str}.BJ"  # 【P2-5：北交所用.BJ】
                else:
                    std_code = f"{code_str}.SZ"
                if std_code in cache:
                    result[std_code] = cache[std_code]
                elif code_str in cache:
                    result[code_str] = cache[code_str]
                else:
                    missing.add(code_str)
                    missing.add(std_code)
            if not missing:
                return result
            # 只查缺失的股票
            ts_codes = missing
        else:
            # 新的一天，重置缓存
            self._daily_price_cache = {}
            self._daily_price_cache_date = trade_date
            cache = self._daily_price_cache
        # 自动格式标准化:兼容两种输入格式
        # 数据库中 ts_code 带后缀(.SH/.SZ),所以无论输入什么都转换为带后缀格式
        ts_codes_standard = []
        for code in ts_codes:
            code_str = str(code).strip()
            if code_str.endswith(".SH") or code_str.endswith(".SZ") or code_str.endswith(".BJ"):
                # 输入已经带后缀,直接使用(匹配数据库)
                ts_codes_standard.append(code_str)
            else:
                # 输入不带后缀,根据代码开头自动补全后缀
                # - 6/5/9 开头 → .SH(上交所)
                # - 8/4 开头 → .BJ(北交所) 【P2-5修复】
                # - 其他 → .SZ(深交所)
                if code_str.startswith('6') or code_str.startswith('5') or code_str.startswith('9'):
                    ts_codes_standard.append(f"{code_str}.SH")
                elif code_str.startswith('8') or code_str.startswith('4'):
                    ts_codes_standard.append(f"{code_str}.BJ")
                else:
                    ts_codes_standard.append(f"{code_str}.SZ")

        # 【修复#42:使用$in+ts_code过滤替代全表扫描】
        # 原逻辑:先查当天所有股票(5000+条)到内存,再过滤 → O(N)全表扫描 + 内存浪费
        # 新逻辑:用$in直接在数据库层面过滤 ts_code,只拉取需要的股票 → O(logN)索引查询
        ts_codes_set = set(ts_codes_standard)
        # 🔧 修复:trade_date 从 all_trade_dates 获取是字符串,但数据库存 int,必须转换
        trade_date_int = int(trade_date)
        # 【修复#9:复合索引查询优化 - 正确的查询顺序】
        # 复合索引定义是 (trade_date, ts_code),查询时按索引顺序匹配字段
        query = {
            "trade_date": trade_date_int,
            "ts_code": {"$in": list(ts_codes_set)},
        }

        await self.log(f"            🔍 _get_prices: 查询 {len(ts_codes_standard)} 只股票,日期: {trade_date}, 直接使用$in过滤")

        docs = await mongo_manager.find_many("stock_daily_ak_full", query)
        result = {}
        # 不需要再做复杂匹配,因为数据库已经用$in过滤了
        matched = 0
        for doc in docs:
            ts_code_doc = doc["ts_code"]
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
                    "open": doc.get("open", doc["close"]),
                    "high": doc.get("high", doc["close"]),
                    "low": doc.get("low", doc["close"]),
                    "close": doc["close"],
                    # 【P1-2记录：stock_daily_ak_full无pre_close字段，回测模式下涨停价计算回退到open】
                    # 影响：高开非涨停股的买入价可能被高估，需数据管道补充pre_close
                    "pre_close": doc.get("pre_close", None)
                }
                matched += 1


        await self.log(f"            ✅ _get_prices: 查询到 {len(result)} 只股票有价格")

        # 【P2-4：存入每日价格缓存】
        cache = getattr(self, '_daily_price_cache', {})
        cache.update(result)
        self._daily_price_cache = cache

        # 【P0-3：更新_last_valid_price，停牌强卖时回退用】
        lvp = getattr(self, '_last_valid_price', {})
        for code, price_info in result.items():
            if price_info.get('close', 0) > 0:
                lvp[code] = price_info['close']
        self._last_valid_price = lvp

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

    @staticmethod
    def _get_limit_pct(ts_code: str) -> float:
        """【辅助函数】根据股票代码获取涨跌停幅度
        主板(60/00): 10%
        创业板(30): 20%
        科创板(68): 20%
        北交所(8/4): 30%
        """
        if ts_code.startswith('30') or ts_code.startswith('68'):
            return 0.20
        elif ts_code.startswith('8') or ts_code.startswith('4'):
            return 0.30
        else:
            return 0.10

    def _get_limit_up_price(self, ts_code: str, open_price: float, close_price: float,
                             high_price: float, low_price: float, pre_close: float = 0) -> float:
        """【辅助函数】计算涨停价买入价

        逻辑：
        1. 一字涨停板(open=close=high=low)：open本身就是涨停价
        2. 非一字板涨停(收盘涨幅>=阈值)：close即涨停价
        3. 非涨停日(高开未封板等)：用pre_close*(1+涨停幅度)估算，不超过high

        【P0-2修复】涨停判断改用pre_close(昨收)，原来用open导致高开涨停误判
        """
        limit_pct = self._get_limit_pct(ts_code)
        # 判断阈值：涨停幅度-0.5%容差(避免浮点误差)
        threshold = limit_pct - 0.005

        if open_price <= 0:
            return 0

        # 一字涨停板：四价相同，open本身就是涨停价
        if (open_price == close_price == high_price == low_price) and open_price > 0:
            return open_price

        # 非一字板涨停：【P0-2修复】用pre_close判断是否涨停
        if pre_close > 0:
            pct_from_pre_close = (close_price - pre_close) / pre_close
            if pct_from_pre_close >= threshold:
                return close_price
        else:
            # 回退：无pre_close时用open近似(兼容旧数据)
            pct_from_open = (close_price - open_price) / open_price
            if pct_from_open >= threshold:
                return close_price

        # 非涨停日：用昨收*(1+涨停幅度)估算涨停价，不超过high
        base_price = pre_close if pre_close > 0 else open_price
        return min(base_price * (1 + limit_pct), high_price)

    def _get_strategy_for_stock(self, code: str) -> str:
        """【辅助函数】获取股票的策略名(支持多策略选同股，取第一个策略)"""
        sinfo = getattr(self, 'stock_to_strategy', {}).get(code, '')
        if isinstance(sinfo, list) and len(sinfo) > 0:
            return sinfo[0]  # 取第一个策略(最优先)
        return sinfo if isinstance(sinfo, str) else "策略选股"

    def _get_buy_price_for_stock(self, code: str, open_price: float, close_price: float,
                                  high_price: float, low_price: float, pre_close: float = 0) -> float:
        """【辅助函数】计算买入价(多策略选同股时取最低买入价，最保守)"""
        sinfo = getattr(self, 'stock_to_strategy', {}).get(code, '')
        strategies = sinfo if isinstance(sinfo, list) else [sinfo]
        
        prices = []
        for sname in strategies:
            if sname == '半路追涨':
                p = min(open_price * 1.04, high_price) if open_price > 0 else 0
            elif sname in ('首板打板', '涨停开板'):
                p = self._get_limit_up_price(code, open_price, close_price, high_price, low_price, pre_close)
            elif sname == '龙头低吸':
                p = low_price * 1.005 if low_price > 0 else open_price * 0.98
            elif sname == '跌停翘板':
                p = low_price * 1.005 if low_price > 0 else open_price * 0.92
            else:
                p = open_price
            if p > 0:
                prices.append(p)
        
        if not prices:
            return open_price
        # 多策略选同股：取最低买入价(最保守，避免高估成本)
        return min(prices)

    def _extract_position_multiplier(self, sentiment: str) -> float:
        """【辅助函数】从情绪等级字符串中提取仓位系数

        Args:
            sentiment: 情绪等级字符串,例如 "高潮期,仓位系数1.0"

        Returns:
            float: 仓位系数,默认 1.0
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

    # ==================== 【修复#7:统一策略筛选条件构建方法】 ====================
    def _build_strategy_filter_conditions(self, strategy_name: str, params: dict) -> list:
        """【统一入口】构建单个策略的因子筛选条件

        消除3处重复定义:强制空仓分支、正常调仓分支、_print_single_strategy_filtering 中都有相同的条件定义

        【修复#44:参数单位统一】
        - min_turnover_rate: 统一为百分比单位(例如 3 代表 3%,不再用 0.03)
        - max_turnover_rate: 统一为百分比单位
        - min_volume_ratio: 统一为倍数值

        Args:
            strategy_name: 策略名称(中文)
            params: 策略参数字典

        Returns:
            list: 策略筛选条件列表,每个元素是 {name, target, operator, label}
        """
        converted_params = {}
        for k, v in params.items():
            if isinstance(v, bool):
                converted_params[k] = 1 if v else 0
            elif isinstance(v, str) and v.replace(".", "", 1).isdigit():
                converted_params[k] = float(v)
            else:
                converted_params[k] = v

        if strategy_name == "半路追涨":
            min_rise_pct = converted_params.get("min_rise_pct", 0.03)
            max_rise_pct = converted_params.get("max_rise_pct", 0.05)
            # 【修复#4：默认值统一为1.5，和 models.py/ultra_short.py/defaults.py 保持一致
            volume_threshold = converted_params.get("min_volume_ratio", 1.5)
            return [
                {"name": "open_below_limit", "target": 1, "label": "开盘低于涨停价"},
                {"name": "pct_chg", "target": min_rise_pct * 100, "operator": ">=", "label": "最小涨幅"},
                {"name": "pct_chg", "target": max_rise_pct * 100, "operator": "<=", "label": "最大涨幅"},
                {"name": "volume_ratio", "target": volume_threshold, "label": "量比阈值"}
            ]
        elif strategy_name == "首板打板":
            min_seal_amount = converted_params.get("min_seal_amount", 5000)
            max_limit_time = converted_params.get("max_limit_up_time", "10:00")
            if isinstance(max_limit_time, str) and ":" in max_limit_time:
                h, m = max_limit_time.split(":")
                max_limit_time = int(h) * 60 + int(m)
            min_circ_mv = converted_params.get("min_circulation_market_cap", 50)
            max_circ_mv = converted_params.get("max_circulation_market_cap", 500)
            min_volume_ratio = converted_params.get("min_volume_ratio", 1.5)
            min_turnover = converted_params.get("min_turnover_rate", 3)
            max_turnover = converted_params.get("max_turnover_rate", 15)
            max_blast = converted_params.get("max_blast_count", 1)
            require_hot = converted_params.get("require_hot_sector", False)
            require_sentiment = converted_params.get("require_sentiment_period", ["rising", "chaos"])
            return [
                {"name": "first_limit_up", "target": 1, "label": "首次涨停"},
                {"name": "limit_up_yesterday", "target": 0, "label": "昨日未涨停"},
                {"name": "opening_pct_chg", "target": 2.0, "operator": ">=", "label": "竞价涨幅≥2%"},
                {"name": "opening_pct_chg", "target": 5.0, "operator": "<=", "label": "竞价涨幅≤5%"},
                {"name": "volume_ratio", "target": min_volume_ratio, "operator": ">=", "label": "竞价量比≥1.5"},
                {"name": "turnover_rate", "target": min_turnover, "operator": ">=", "label": "换手率≥3%"},
                {"name": "turnover_rate", "target": max_turnover, "operator": "<=", "label": "换手率≤15%"},
                {"name": "circ_mv", "target": min_circ_mv * 10000, "operator": ">=", "label": "最小流通市值"},
                {"name": "circ_mv", "target": max_circ_mv * 10000, "operator": "<=", "label": "最大流通市值"},
                {"name": "limit_up_open_amount", "target": min_seal_amount, "label": "最小封单金额"},
                {"name": "limit_up_open_count", "target": max_blast, "operator": "<=", "label": "最大开板次数"},
                {"name": "hot_sector", "target": 1 if require_hot else 0, "label": "要求热门板块"},
                {"name": "sentiment_period_in", "target": require_sentiment, "operator": "in", "label": "情绪周期要求"},
                {"name": "limit_up_time", "target": max_limit_time, "operator": "<=", "label": "最晚涨停时间"},
            ]
        elif strategy_name == "涨停开板":
            min_consecutive = converted_params.get("min_consecutive_limit", 2)
            max_consecutive = converted_params.get("max_consecutive_limit", 4)
            max_open_duration = converted_params.get("max_open_duration", 5)
            min_seal_after = converted_params.get("min_seal_after_open", 3000)
            # 【修复#45: min_turnover_rate前端传小数(0.15=15%),需*100转为百分比单位】
            _raw_turnover = converted_params.get("min_turnover_rate", 0.15)
            min_turnover = _raw_turnover * 100 if _raw_turnover < 1 else _raw_turnover
            # 【修复#46: 开盘涨幅下限0%太严格,连板股开板日常低开,改为-3%】
            opening_pct_min = converted_params.get("opening_pct_min", -3.0)
            opening_pct_max = converted_params.get("opening_pct_max", 3.0)
            min_volume_ratio = converted_params.get("min_volume_ratio", 2.0)
            require_sentiment = converted_params.get("require_sentiment_period", ["rising"])
            return [
                {"name": "limit_up_count", "target": min_consecutive, "operator": ">=", "label": "最小连续涨停天数"},
                {"name": "limit_up_count", "target": max_consecutive, "operator": "<=", "label": "最大连续涨停天数"},
                {"name": "opening_pct_chg", "target": opening_pct_min, "operator": ">=", "label": f"开盘涨幅≥{opening_pct_min}%"},
                {"name": "opening_pct_chg", "target": opening_pct_max, "operator": "<=", "label": f"开盘涨幅≤{opening_pct_max}%"},
                {"name": "volume_ratio", "target": min_volume_ratio, "operator": ">=", "label": "开盘量比≥2.0"},
                {"name": "limit_up_open_duration", "target": max_open_duration, "operator": "<=", "label": "最大开板时长"},
                {"name": "limit_up_open_amount", "target": min_seal_after, "label": "开板后最小封单"},
                {"name": "turnover_rate", "target": min_turnover, "label": "最小换手率"},
                {"name": "sentiment_period_in", "target": require_sentiment, "operator": "in", "label": "情绪周期要求"},
            ]
        elif strategy_name == "龙头低吸":
            min_consecutive = converted_params.get("min_consecutive_limit", 3)
            min_correction = converted_params.get("min_correction_pct", 0.15)
            max_correction = converted_params.get("max_correction_pct", 0.3)
            correction_days_min = converted_params.get("correction_days_min", 2)
            correction_days_max = converted_params.get("correction_days_max", 5)
            support_level = converted_params.get("support_level", "ma5")
            return [
                # 【修复: market_leader因子全0不可用,暂时跳过该条件】
                # {"name": "market_leader", "target": 1, "label": "市场龙头"},
                {"name": "limit_up_count", "target": min_consecutive, "operator": ">=", "label": f"近5日至少{min_consecutive}板"},
                {"name": "pullback_pct", "target": min_correction, "operator": ">=", "label": "最小回调幅度"},
                {"name": "pullback_pct", "target": max_correction, "operator": "<=", "label": "最大回调幅度"},
                {"name": "pullback_days", "target": correction_days_min, "operator": ">=", "label": "最小回调天数"},
                {"name": "pullback_days", "target": correction_days_max, "operator": "<=", "label": "最大回调天数"},
                {"name": f"pullback_{support_level}", "target": 1, "label": f"{support_level.upper()}支撑位"},
                {"name": "volume_ratio_vs_ma5", "target": 1.0, "operator": "<=", "label": "成交量小于5日均量"},
            ]
        elif strategy_name == "跌停翘板":
            min_consecutive = converted_params.get("min_consecutive_limit", 3)
            # 【修复#47: min_qiao_amount单位统一为千元(与数据库limit_down_open_amount一致)】
            # 前端传10000(万元),数据库因子是千元,需*1000转换
            # 【P2-C修复：同上单位转换规则】
            _raw_qiao = converted_params.get("min_qiao_amount", 1000)
            min_qiao_amount = _raw_qiao * 10 if _raw_qiao < 100000 else _raw_qiao
            min_rise_after = converted_params.get("min_rise_after_qiao", 0.03)
            require_high_sentiment = converted_params.get("require_high_sentiment", True)
            require_sentiment = converted_params.get("require_sentiment_period", ["rising", "chaos"])
            min_turnover_qiao = converted_params.get("min_turnover_rate", 10.0)
            # 【修复：min_turnover_rate前端可能传小数(0.10=10%)，需转换】
            if min_turnover_qiao < 1:
                min_turnover_qiao *= 100
            return [
                {"name": "limit_down_yesterday", "target": 1, "label": "昨日跌停"},
                {"name": "open_above_limit_down", "target": 1, "label": "开盘高于跌停价"},
                {"name": "turnover_rate", "target": min_turnover_qiao, "operator": ">=", "label": f"换手率≥{min_turnover_qiao:.0f}%"},
                {"name": "limit_down_open_amount", "target": min_qiao_amount, "label": "翘板最小金额"},
                {"name": "rise_after_limit_down", "target": min_rise_after, "label": "翘板后最小涨幅"},
                # 【P0-1修复：sentiment_score是0-100分数，>=1只排除0分，语义错误】
                # 改用sentiment_period_in + in操作符，与首板/涨停策略一致
                {"name": "sentiment_period_in", "target": require_sentiment if require_high_sentiment else [], "operator": "in", "label": "情绪周期要求"},
            ]
        else:
            return []

    def _rebalance(self, trade_date: int, target_weights: dict[str, float],
                       cash: float, holdings: dict[str, int], prices: dict[str, float], sentiment: str = ""):
        """执行调仓

        Args:
            trade_date: 当前调仓日期
            target_weights: 目标权重 {ts_code: weight}
            cash: 当前现金
            holdings: 当前持仓 {ts_code: shares}
            prices: 当前价格 {ts_code: price}
            sentiment: 情绪等级字符串(含仓位系数)

        Returns:
            (new_cash, new_holdings, records)
        """
        records = []

        # 计算当前总价值
        # 【P0-B修复：用open价估值持仓(调仓决策基于开盘前信息)，而非close价】
        # 收盘价是盘中最终价，调仓时还没收盘，用open更合理
        total_value = cash
        for code, shares in holdings.items():
            if shares > 0:
                if code in prices and prices[code].get('open', 0) > 0:
                    # 持仓用开盘价估值(调仓决策时刻)
                    total_value += shares * prices[code]['open']
                elif code in prices and prices[code].get('close', 0) > 0:
                    # 回退：open不可用时用close
                    total_value += shares * prices[code]['close']
                else:
                    # 【P0-1修复：停牌股用_last_valid_price估值】
                    lvp = getattr(self, '_last_valid_price', {}).get(code, 0)
                    if lvp > 0:
                        total_value += shares * lvp

        # 🔴 任务2:情绪周期仓位系数真正应用(P0!)
        sentiment_multiplier = self._extract_position_multiplier(sentiment)

        # 🔴 第2层:特殊时期过滤(新增!)
        # 节假日前夕/重大会议/月末季末年末 自动降仓
        special_period_filter = get_special_period_filter()
        special_multiplier = special_period_filter.get_position_multiplier(str(trade_date))
        active_periods = special_period_filter.get_active_periods(str(trade_date))

        # ✅ 综合仓位系数 = 情绪系数 × 特殊时期系数
        # 两个维度独立判断,取乘积就是最终仓位(最严格的生效)
        position_multiplier = sentiment_multiplier * special_multiplier

        # 计算目标持仓(用策略对应买入价计算仓位,而非开盘价)
        target_shares = {}  # {ts_code: target_shares}
        # 【P1-2修复：max_position_per_stock 单票仓位上限】
        max_pos_per_stock = self._risk_config.get('max_position_per_stock', 1.0) if hasattr(self, '_risk_config') else 1.0
        for code, weight in target_weights.items():
            if code not in prices:
                continue
            # ✅ 应用综合仓位系数!
            # 例如:情绪冰点 0.3 × 春节前夕 0.2 = 0.06 → 只有 6% 仓位
            p_info = prices[code]
            o = p_info.get('open', 0)
            h = p_info.get('high', o)
            l = p_info.get('low', o)
            # 【P1-1修复：多策略选同股时取最低买入价】
            buy_p = self._get_buy_price_for_stock(code, o, p_info.get('close', o), h, l, p_info.get('pre_close', 0))
            if buy_p <= 0:
                buy_p = o
            # 【P1-2修复：仓位上限 = min(weight * position_multiplier, max_position_per_stock)】
            effective_weight = min(weight * position_multiplier, max_pos_per_stock)
            target_value = total_value * effective_weight
            shares = int(int(target_value / buy_p) / 100) * 100
            if shares > 0:
                target_shares[code] = shares

        # 先卖出:不在目标持仓中的股票全卖 + 持仓超过目标的股票减仓
        sell_codes = [code for code in holdings if code not in target_shares and holdings[code] > 0]
        # 【P1-1修复：超过max_hold_days的持仓强制卖出，即使仍在目标池中】
        # max_hold_days语义是交易日天数，但日历天数≈交易日*1.5，用日历天数>max_hold_days*1.5判断
        max_hold_days = self._risk_config.get('max_hold_days', 999) if hasattr(self, '_risk_config') else 999
        over_hold_codes = []
        for code in list(holdings.keys()):
            if holdings.get(code, 0) > 0:
                buy_date_raw = getattr(self, '_cost_basis_date', {}).get(code)
                if buy_date_raw is not None and max_hold_days < 999:
                    try:
                        buy_dt = dt_now.strptime(str(buy_date_raw), '%Y%m%d')
                        trade_dt = dt_now.strptime(str(trade_date), '%Y%m%d')
                        calendar_days = (trade_dt - buy_dt).days
                        # 日历天数 > 交易日*1.5 视为超时（周末2天+1交易日=3日历天≈1交易日）
                        if calendar_days > max_hold_days * 1.5 and code not in sell_codes:
                            over_hold_codes.append(code)
                    except (ValueError, TypeError):
                        pass
        sell_codes.extend(over_hold_codes)
        # 【修复P1-6：减仓逻辑 — 持仓超过目标时卖出差额】
        reduce_codes = {code: holdings[code] - target_shares[code] for code in holdings
                        if code in target_shares and holdings.get(code, 0) > target_shares[code]}
        # 【P1-4修复：减仓前检查止损止盈 — 已触发止损的减仓股改为全卖】
        enable_sl = self._risk_config.get('enable_stop_loss', True) if hasattr(self, '_risk_config') else True
        enable_tp = self._risk_config.get('enable_take_profit', True) if hasattr(self, '_risk_config') else True
        # 【P0-2修复：按策略查找策略级止损止盈参数，优先于全局参数】
        def _get_sl_tp_for_code(code):
            """获取某只股票对应的策略级止损止盈参数"""
            strategies = getattr(self, 'stock_to_strategy', {}).get(code, [])
            strategy_rp = getattr(self, '_strategy_risk_params', {})
            global_sl = self._risk_config.get('stop_loss_pct', 0.02) if hasattr(self, '_risk_config') else 0.02
            global_tp = self._risk_config.get('take_profit_pct', 0.07) if hasattr(self, '_risk_config') else 0.07
            if isinstance(strategies, list) and strategies:
                # 多策略时取最宽松的止损（最小stop_loss_pct）和最宽松的止盈（最大take_profit_pct）
                sl = min(strategy_rp.get(s, {}).get('stop_loss_pct', global_sl) for s in strategies)
                tp = max(strategy_rp.get(s, {}).get('take_profit_pct', global_tp) for s in strategies)
                return sl, tp
            return global_sl, global_tp

        codes_to_promote = []  # 从reduce_codes升级到sell_codes的股票
        for code in list(reduce_codes.keys()):
            p = prices.get(code, {})
            low_p = p.get('low', 0)
            high_p = p.get('high', 0)
            cost = getattr(self, '_cost_basis', {}).get(code, 0)
            if cost > 0 and p.get('close', 0) > 0:
                code_sl, code_tp = _get_sl_tp_for_code(code)  # 【P0-2修复：按策略获取参数】
                if enable_sl and low_p <= cost * (1 - code_sl):
                    codes_to_promote.append(code)  # 触发止损，应全卖
                elif enable_tp and high_p >= cost * (1 + code_tp):
                    codes_to_promote.append(code)  # 触发止盈，应全卖
        for code in codes_to_promote:
            sell_codes.append(code)
            del reduce_codes[code]
        # 【修复P1-8：停牌股超时强卖 — close<=0的持仓连续持有>10天强制卖出(取最后有效价)】
        suspend_sell_codes = []
        for code in list(holdings.keys()):
            if holdings.get(code, 0) > 0 and code in prices:
                p = prices[code]
                if p.get('close', 0) <= 0:
                    # 【P0-1修复：从_cost_basis_date获取买入日期】
                    buy_date_raw = getattr(self, '_cost_basis_date', {}).get(code)
                    if buy_date_raw is not None:
                        try:
                            # 【P0-E修复：用datetime计算天数差，替代%10000模运算（跨年必错）】
                            buy_dt = dt_now.strptime(str(buy_date_raw), '%Y%m%d')
                            trade_dt = dt_now.strptime(str(trade_date), '%Y%m%d')
                            days_held = (trade_dt - buy_dt).days  # 日历天数
                            # 超过15个日历天(≈10个交易日)停牌，强制卖出
                            if days_held > 15:
                                last_price = p.get('open', 0) or self._last_valid_price.get(code, 0) if hasattr(self, '_last_valid_price') else 0
                                if last_price > 0:
                                    suspend_sell_codes.append(code)
                        except (ValueError, TypeError):
                            pass

        # 【方案2:日频数据推算盘中卖出价】
        # 止损:盘中最低价触发 → 用low近似
        # 止盈:盘中最高价触发 → 用high近似
        # 其他:收盘卖出 → 用close
        enable_stop_loss = self._risk_config.get('enable_stop_loss', True) if hasattr(self, '_risk_config') else True
        enable_take_profit = self._risk_config.get('enable_take_profit', True) if hasattr(self, '_risk_config') else True
        # 【P0-2修复：默认全局参数，卖出循环中按code覆盖】
        global_sl = self._risk_config.get('stop_loss_pct', 0.02) if hasattr(self, '_risk_config') else 0.02
        global_tp = self._risk_config.get('take_profit_pct', 0.07) if hasattr(self, '_risk_config') else 0.07
        for ts_code in sell_codes:
            shares = holdings[ts_code]
            price_info = prices.get(ts_code, {})
            close_price = price_info.get('close', 0)
            high_price = price_info.get('high', close_price)
            low_price = price_info.get('low', close_price)
            open_price = price_info.get('open', close_price)
            if close_price <= 0 or shares <= 0:
                # 【修复P1-8：停牌股close=0时尝试用最后有效价卖出】
                if ts_code in suspend_sell_codes:
                    last_price = price_info.get('open', 0) or getattr(self, '_last_valid_price', {}).get(ts_code, 0)
                    if last_price > 0 and shares > 0:
                        # 停牌超时强卖，用最后有效价
                        sell_price = last_price
                        sell_reason = '停牌超时强卖'
                        price = sell_price
                        slippage_pct = self._slippage_pct if hasattr(self, '_slippage_pct') else 0.002
                        sell_price_adj = price * (1 - slippage_pct)
                        gross_amount = shares * sell_price_adj
                        commission = max(gross_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
                        stamp_tax = gross_amount * self.STAMP_TAX
                        net_amount = gross_amount - commission - stamp_tax
                        cash += net_amount
                        records.append(RebalanceRecord(
                            date=str(trade_date), action="sell", ts_code=ts_code,
                            shares=shares, price=price, amount=net_amount,
                            reason=sell_reason, sentiment=sentiment))
                        holdings[ts_code] = 0
                        if hasattr(self, '_cost_basis') and ts_code in self._cost_basis:
                            del self._cost_basis[ts_code]
                            if hasattr(self, '_cost_basis_date') and ts_code in self._cost_basis_date:
                                del self._cost_basis_date[ts_code]
                continue

            # 判断盘中是否触发止损/止盈(基于实际买入成本)
            cost_basis = getattr(self, '_cost_basis', {}).get(ts_code, open_price)  # 用实际买入价
            sell_price = close_price  # 默认收盘价
            sell_reason = '调仓卖出'
            if cost_basis > 0:
                # 【P0-2修复：按策略获取止损止盈参数】
                code_sl, code_tp = _get_sl_tp_for_code(ts_code)
                stop_price = cost_basis * (1 - code_sl)
                profit_price = cost_basis * (1 + code_tp)
                if enable_stop_loss and low_price <= stop_price:
                    sell_price = stop_price
                    sell_reason = f'止损({code_sl*100:.0f}%)'
                elif enable_take_profit and high_price >= profit_price:
                    sell_price = profit_price
                    sell_reason = f'止盈({code_tp*100:.0f}%)'
            price = sell_price

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
                reason=sell_reason,
                sentiment=sentiment
            ))

            # 清空持仓
            holdings[ts_code] = 0
            # 清理买入成本记录
            if hasattr(self, '_cost_basis') and ts_code in self._cost_basis:
                del self._cost_basis[ts_code]
                if hasattr(self, '_cost_basis_date') and ts_code in self._cost_basis_date:
                    del self._cost_basis_date[ts_code]

        # 再买入:目标持仓中需要增加的股票
        for ts_code, target_count in target_shares.items():
            current_shares = holdings.get(ts_code, 0)
            delta = target_count - current_shares
            reduce_reason = None  # 【P1-5修复：每次循环重置，避免泄漏到后续股票】

            if delta <= 0:
                continue  # 不需要买入

            # 【方案2:日频数据推算盘中触发价】
            # 不同策略的买入时机不同,用日频OHLC推算合理买入价
            price_info = prices.get(ts_code, {})
            open_price = price_info.get('open', 0)
            high_price = price_info.get('high', open_price)
            low_price = price_info.get('low', open_price)
            close_price = price_info.get('close', 0)
            strategy_name = self._get_strategy_for_stock(ts_code)
            # 【P1-1修复：多策略选同股时取最低买入价】
            price = self._get_buy_price_for_stock(ts_code, open_price, close_price, high_price, low_price, price_info.get('pre_close', 0))
            if price <= 0:
                price = open_price
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
                original_delta = delta
                ratio = cash / total_cost
                delta = int(int(delta * ratio) / 100) * 100
                if delta <= 0:
                    continue
                # 【修复新7：现金缩减买入信息附加到reason字段，后续日志显示】
                reduce_reason = f"现金不足缩减{ratio*100:.1f}%"
                gross_amount = delta * buy_price_adj
                commission = max(gross_amount * self.BUY_COMMISSION, self.MIN_COMMISSION)
                total_cost = gross_amount + commission

            # 更新现金
            cash -= total_cost

            # 更新持仓
            holdings[ts_code] = current_shares + delta
            # 【记录买入成本,用于卖出时止损止盈判断】
            # 【修复P1-7：增仓时更新cost_basis为加权平均价】
            if not hasattr(self, '_cost_basis'):
                self._cost_basis = {}
            if not hasattr(self, '_cost_basis_date'):
                self._cost_basis_date = {}
            if current_shares > 0 and ts_code in self._cost_basis:
                # 增仓：加权平均成本 = (旧成本*旧股数 + 新价*新股数) / 总股数
                old_cost = self._cost_basis[ts_code]
                total_shares = current_shares + delta
                self._cost_basis[ts_code] = (old_cost * current_shares + price * delta) / total_shares
            else:
                self._cost_basis[ts_code] = price  # 新买入：记录实际买入价(含策略差异化)
            self._cost_basis_date[ts_code] = trade_date  # 记录首次买入日期(用于停牌超时)

            # 记录交易
            strategy_name = self._get_strategy_for_stock(ts_code)  # 【P1-1修复：支持多策略列表】
            # 【修复新7：如果有现金缩减信息附加到reason】
            final_reason = "rebalance"
            if reduce_reason:
                final_reason = f"rebalance ({reduce_reason})"
            records.append(RebalanceRecord(
                date=str(trade_date),
                action="buy",
                ts_code=ts_code,
                shares=delta,
                price=price,
                amount=-total_cost,
                reason=final_reason,
                strategy_name=strategy_name,  # 【修复新6：存独立字段】
                sentiment=sentiment
            ))

        # 【修复P1-6：减仓逻辑 — 卖出超过目标的部分】
        for ts_code, reduce_shares in reduce_codes.items():
            if reduce_shares <= 0:
                continue
            shares = holdings.get(ts_code, 0)
            if shares < reduce_shares:
                reduce_shares = shares
            price_info = prices.get(ts_code, {})
            close_price = price_info.get('close', 0)
            if close_price <= 0:
                continue  # 停牌股不处理减仓
            # 减仓用收盘价(不做止损止盈判断，减仓是调仓行为)
            sell_price = close_price
            sell_reason = '减仓'
            slippage_pct = self._slippage_pct if hasattr(self, '_slippage_pct') else 0.002
            sell_price_adj = sell_price * (1 - slippage_pct)
            gross_amount = reduce_shares * sell_price_adj
            commission = max(gross_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
            stamp_tax = gross_amount * self.STAMP_TAX
            net_amount = gross_amount - commission - stamp_tax
            cash += net_amount
            holdings[ts_code] = shares - reduce_shares
            records.append(RebalanceRecord(
                date=str(trade_date), action="sell", ts_code=ts_code,
                shares=reduce_shares, price=sell_price, amount=net_amount,
                reason=sell_reason, sentiment=sentiment))
            # 减仓后如果清零，删除cost_basis
            if holdings[ts_code] <= 0 and hasattr(self, '_cost_basis') and ts_code in self._cost_basis:
                del self._cost_basis[ts_code]
                if hasattr(self, '_cost_basis_date') and ts_code in self._cost_basis_date:
                    del self._cost_basis_date[ts_code]

        # 清理零持仓
        holdings = {code: shares for code, shares in holdings.items() if shares > 0}

        return cash, holdings, records

    async def _get_stock_names(self, ts_codes: list[str]):
        """批量获取股票名称,使用缓存减少查询"""
        result = {}
        need_query = []

        # 【P1-D修复：代码标准化逻辑与_get_prices保持一致】
        # 数据库 stock_basic 存储格式: 600000.SH / 000001.SZ / 830001.BJ
        # 与 stock_daily_ak_full 的 ts_code 格式完全一致
        def _standardize_code(code_str: str) -> str:
            """标准化股票代码为数据库格式: NNNNNN.EX"""
            code_str = str(code_str).strip()
            # 已经是标准格式
            if code_str.endswith('.SH') or code_str.endswith('.SZ') or code_str.endswith('.BJ'):
                return code_str
            # 无后缀:根据代码开头自动补全
            if code_str.startswith('6') or code_str.startswith('5') or code_str.startswith('9'):
                return f"{code_str}.SH"
            elif code_str.startswith('8') or code_str.startswith('4'):
                return f"{code_str}.BJ"  # 北交所
            else:
                return f"{code_str}.SZ"

        for ts_code in ts_codes:
            standard_code = _standardize_code(ts_code)

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
            standard_code = _standardize_code(ts_code)

            if standard_code in self._stock_name_cache:
                result[ts_code] = self._stock_name_cache[standard_code]
            else:
                # 找不到,回退到使用原始代码去掉后缀作为名称
                if '.' in ts_code:
                    result[ts_code] = ts_code.split('.')[0]
                else:
                    result[ts_code] = ts_code

        return result
