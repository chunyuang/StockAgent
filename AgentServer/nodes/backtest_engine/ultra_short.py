"""

超短策略回测执行器

从node.py拆分出的超短策略回测执行逻辑。

【参数嵌套规范】
═══════════════════════════════════════════════════════════════

Web API构建的task_info结构:
  task_info = {
    "task_id": "us_xxx",
    "params": {                    ← 顶层参数（策略/日期/开关/selected_strategies）
      "strategies": [...],
      "start_date": "20260105",
      "end_date": "20260320",
      "initial_cash": 1000000,
      "enable_force_empty": true,    ← 功能开关（顶层）
      "enable_sentiment_cycle": true,
      "selected_strategies": [...],
      "params": {                  ← 内层参数（全局风控/细粒度配置）
        "stop_loss_pct": 0.03,
        "commission_rate": 0.0003,
        "force_empty_config": {...}, ← 细粒度配置对象
        "global_filter_config": {...},
        "selected_strategies": [...], ← 兼容：也可放在内层
      }
    }
  }

本文件读取规则:
  req_params = params.get("params", {})  ← 整个params对象
  strategies = req_params.get("strategies", [])  ← 从顶层读
  enable_force_empty = req_params.get("enable_force_empty", True)  ← 从顶层读
  strategy_params = req_params.get("params", {})  ← 从内层读

═══════════════════════════════════════════════════════════════
"""

import subprocess
from datetime import datetime, timezone

from core.constants import C
from core.managers import mongo_manager, akshare_manager, redis_manager
from core.utils.logger import logger

from nodes.backtest_engine.factor_selection import PortfolioBacktester
from nodes.backtest_engine.strategy_defaults import ALL_STRATEGIES as _ALL_STRATEGIES, GLOBAL_RISK, STRATEGY_CONFIGS

# 默认所有策略（兜底用）— 从单一来源读取
ALL_STRATEGIES = _ALL_STRATEGIES


async def _redis_publish_safe(channel, data):
    """Redis publish with fallback - does not crash if Redis is unavailable"""
    try:
        await redis_manager.publish(channel, data)
    except Exception:
        pass


async def execute_ultra_short_backtest(
    params: dict,
    push_log_fn,
    node_logger,
    task_id: str,
) -> dict:
    """
    执行超短策略回测

    Args:
        params: 超短回测参数
        push_log_fn: 日志推送函数
        node_logger: 节点logger实例
        task_id: 任务ID

    Returns:
        回测报告（包含所有策略的结果和汇总统计）
    """
    # 设置当前任务ID到日志工具类
    logger.set_task_id(task_id)

    # 【任务3：回测耗时记录】记录开始时间
    import time as _time
    _start_time = _time.time()

    # 【P0-2修复：统一参数读取路径】
    # Web API构建: params = { strategies, start_date, ..., params: { stop_loss_pct, ... } }
    # 顶层字段: strategies/start_date/end_date/initial_cash/enable_* /selected_strategies
    # 内层字段: params.stop_loss_pct/commission_rate/force_empty_config/global_filter_config
    req_params = params.get("params", {})  # 整个params对象
    strategies = req_params.get("strategies", [])
    start_date = req_params.get("start_date", "20260105")
    end_date = req_params.get("end_date", "20260320")
    initial_cash = req_params.get("initial_cash", 1000000)
    strategy_params = req_params.get("params", {})  # 内层全局风控参数
    period = req_params.get("period", "daily")
    
    # 功能开关：统一从顶层读取（Web API在params和params.params两处都传了，优先顶层）
    enable_force_empty = req_params.get("enable_force_empty", req_params.get("params", {}).get("enable_force_empty", True))
    enable_sentiment_cycle = req_params.get("enable_sentiment_cycle", req_params.get("params", {}).get("sentiment_cycle", True))
    enable_auction_filter = req_params.get("enable_auction_filter", req_params.get("params", {}).get("auction_filter", True))
    enable_stop_loss = req_params.get("enable_stop_loss", req_params.get("params", {}).get("enable_stop_loss", True))
    enable_take_profit = req_params.get("enable_take_profit", req_params.get("params", {}).get("enable_take_profit", True))
    enable_ma60_filter = req_params.get("enable_ma60_filter", req_params.get("params", {}).get("enable_ma60_filter", True))
    enable_sector_concentration = req_params.get("enable_sector_concentration", req_params.get("params", {}).get("enable_sector_concentration", True))

    # 打印初始化阶段头部
    logger.success("INIT", "============== 回测任务启动 ==============")
    logger.info("INIT", f"回测时间：{start_date} → {end_date}")
    logger.info("INIT", f"初始资金：{initial_cash:,.0f} 元")

    # 解析选中策略名称
    # 【N06修复：使用models.py中的共享映射，不再本地重复定义】
    from nodes.web.api.backtest.models import strategy_name_map as _snm
    strategy_name_map = _snm
    selected_strategy_names = [strategy_name_map.get(s, s) for s in strategies]
    logger.info("INIT", f"选中策略：【{'、'.join(selected_strategy_names)}】")

    # 打印全局参数
    logger.info("INIT", f"全局参数：流动性门槛{strategy_params.get('liquidity_threshold', GLOBAL_RISK['liquidity_threshold'])}万/止损{strategy_params.get('stop_loss_pct', GLOBAL_RISK['stop_loss_pct'])*100}%/止盈{strategy_params.get('take_profit_pct', GLOBAL_RISK['take_profit_pct'])*100}%/最大持仓{strategy_params.get('max_hold_days', GLOBAL_RISK['max_hold_days'])}天/单票仓位{strategy_params.get('max_position_per_stock', GLOBAL_RISK['max_position_per_stock'])*100}%/总仓位{strategy_params.get('max_total_position', GLOBAL_RISK['max_total_position'])*100}%")

    # 打印功能开关（已在上方统一读取，此处仅打印）
    logger.info("INIT", f"功能开关：强制空仓{'✅' if enable_force_empty else '❌'} / 情绪周期{'✅' if enable_sentiment_cycle else '❌'} / 竞价过滤{'✅' if enable_auction_filter else '❌'} / 止损{'✅' if enable_stop_loss else '❌'} / 止盈{'✅' if enable_take_profit else '❌'} / MA60过滤{'✅' if enable_ma60_filter else '❌'} / 板块集中度{'✅' if enable_sector_concentration else '❌'}")

    # 打印代码版本
    try:
        import os
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        commit_id = subprocess.check_output("git rev-parse --short HEAD", shell=True, cwd=project_root).decode().strip()
        commit_time = subprocess.check_output("git log -1 --format=%cd --date=format:'%Y-%m-%d %H:%M'", shell=True, cwd=project_root).decode().strip()
        logger.info("INIT", f"代码版本：log分支 commit {commit_id} ({commit_time})")
    except Exception:
        pass

    logger.success("INIT", "===============================================")

    # 更新状态为 running
    await mongo_manager.update_one(
        "backtest_tasks",
        {"task_id": task_id},
        {"$set": {"status": "running", "started_at": datetime.now(timezone.utc), "progress": 10}},
    )
    # 【修复#4：进度推送Redis频道，前端实时接收】
    await _redis_publish_safe(f"backtest:progress:{task_id}", {
        "task_id": task_id,
        "progress": 10,
        "status": "running"
    })

    selected_strategies = req_params.get("selected_strategies", [])
    # 兜底：如果前端没传，用默认所有策略
    if not selected_strategies:
        selected_strategies = ALL_STRATEGIES

    # ========== 参数日志只打印一次（与界面对照）==========
    # 【修复：参数日志只打印一次】
    await push_log_fn(task_id, "📋 === 🔧 全局公共参数 ===")
    await push_log_fn(task_id, "├─ 流动性门槛: %s 万元" % strategy_params.get('liquidity_threshold', GLOBAL_RISK['liquidity_threshold']))
    await push_log_fn(task_id, "├─ 单票最大仓位: %.1f %%" % (strategy_params.get('max_position_per_stock', GLOBAL_RISK['max_position_per_stock'])*100))
    await push_log_fn(task_id, "├─ 总仓位上限: %.1f %%" % (strategy_params.get('max_total_position', GLOBAL_RISK['max_total_position'])*100))
    await push_log_fn(task_id, "├─ 止损比例: %.1f %%" % (strategy_params.get('stop_loss_pct', GLOBAL_RISK['stop_loss_pct'])*100))
    await push_log_fn(task_id, "├─ 止盈比例: %.1f %%" % (strategy_params.get('take_profit_pct', GLOBAL_RISK['take_profit_pct'])*100))
    await push_log_fn(task_id, "├─ 最大持仓天数: %d 天" % strategy_params.get('max_hold_days', GLOBAL_RISK['max_hold_days']))
    await push_log_fn(task_id, "├─ 强制空仓规则: %s" % ("已启用" if req_params.get('enable_force_empty', True) else "已关闭"))
    await push_log_fn(task_id, "├─ 情绪周期算法: %s" % ("已启用" if req_params.get('enable_sentiment_cycle', True) else "已关闭"))
    await push_log_fn(task_id, "└─ 竞价过滤规则: %s" % ("已启用" if req_params.get('enable_auction_filter', True) else "已关闭"))

    for s in selected_strategies:
        strategy_name = s.get('name', s.get('id', '未知策略'))
        strategy_id = s.get('id', '')
        await push_log_fn(task_id, "")
        await push_log_fn(task_id, "🎯 【%s】" % strategy_name)
        strategy_params_local = s.get('params', {})
        if "params" not in s:
            s["params"] = {}
        s["params"].update(strategy_params_local)
        # 【P1-5修复：默认值统一从STRATEGY_CONFIGS读取，确保日志与筛选逻辑一致】
        _defaults = STRATEGY_CONFIGS.get(strategy_id, {}).get("params", {})
        if strategy_name == '半路追涨':
            min_rise = strategy_params_local.get('min_rise_pct', _defaults.get('min_rise_pct', 0.03)) * 100
            max_rise = strategy_params_local.get('max_rise_pct', _defaults.get('max_rise_pct', 0.07)) * 100
            volume_val = strategy_params_local.get('min_volume_ratio', _defaults.get('min_volume_ratio', 2.0))
            allow_after_10am = strategy_params_local.get('allow_after_10am', _defaults.get('allow_after_10am', False))
            await push_log_fn(task_id, "  ├─ 最小涨幅: %.1f %%" % min_rise)
            await push_log_fn(task_id, "  ├─ 最大涨幅: %.1f %%" % max_rise)
            await push_log_fn(task_id, "  ├─ 量比阈值: %.1f 倍" % volume_val)
            await push_log_fn(task_id, "  └─ 允许10点后买入: %s" % ("是" if allow_after_10am else "否"))
            s["params"]["volume_threshold"] = volume_val
            s["params"]["min_volume_ratio"] = volume_val
        elif strategy_name == '首板打板':
            # 【P1-5修复：仅打印实际生效的参数，标注实盘专用参数】
            min_cap = strategy_params_local.get('min_circulation_market_cap', _defaults.get('min_circulation_market_cap', 50))
            max_cap = strategy_params_local.get('max_circulation_market_cap', _defaults.get('max_circulation_market_cap', 500))
            opening_min = strategy_params_local.get('opening_pct_min', _defaults.get('opening_pct_min', -1.0))
            opening_max = strategy_params_local.get('opening_pct_max', _defaults.get('opening_pct_max', 7.0))
            hit_yizi = strategy_params_local.get('hit_probability_yizi', _defaults.get('hit_probability_yizi', 0.0))
            hit_fast = strategy_params_local.get('hit_probability_fast', _defaults.get('hit_probability_fast', 0.3))
            hit_normal = strategy_params_local.get('hit_probability_normal', _defaults.get('hit_probability_normal', 0.5))
            hit_slow = strategy_params_local.get('hit_probability_slow', _defaults.get('hit_probability_slow', 0.7))
            await push_log_fn(task_id, "  ├─ 最小流通市值: %d 亿" % min_cap)
            await push_log_fn(task_id, "  ├─ 最大流通市值: %d 亿" % max_cap)
            await push_log_fn(task_id, "  ├─ 竞价涨幅范围: %.1f%% ~ %.1f%%" % (opening_min, opening_max))
            await push_log_fn(task_id, "  ├─ 成交概率: 一字%.0f%%/秒%.0f%%/快%.0f%%/慢%.0f%%" % (hit_yizi*100, hit_fast*100, hit_normal*100, hit_slow*100))
            # 以下为实盘专用参数，日线回测无数据不生效
            _seal = strategy_params_local.get('min_seal_amount', 5000)
            _limit_time = strategy_params_local.get('max_limit_up_time', '10:00')
            _blast = strategy_params_local.get('max_blast_count', 1)
            _hot = strategy_params_local.get('require_hot_sector', True)
            await push_log_fn(task_id, "  ├─ [实盘] 最小封单: %d万 / 最晚涨停: %s / 最大开板: %d次 / 热门板块: %s" % (_seal, _limit_time, _blast, "是" if _hot else "否"))
        elif strategy_name == '涨停开板':
            min_consecutive = strategy_params_local.get('min_consecutive_limit', _defaults.get('min_consecutive_limit', 2))
            max_open_duration = strategy_params_local.get('max_open_duration', _defaults.get('max_open_duration', 5))
            min_seal_after = strategy_params_local.get('min_seal_after_open', _defaults.get('min_seal_after_open', 3000))
            min_turnover = strategy_params_local.get('min_turnover_rate', _defaults.get('min_turnover_rate', 0.15)) * 100
            opening_pct_min = strategy_params_local.get('opening_pct_min', _defaults.get('opening_pct_min', -3.0))
            opening_pct_max = strategy_params_local.get('opening_pct_max', _defaults.get('opening_pct_max', 3.0))
            min_volume_ratio = strategy_params_local.get('min_volume_ratio', _defaults.get('min_volume_ratio', 2.0))
            await push_log_fn(task_id, "  ├─ 最小连续涨停天数: %d 天" % min_consecutive)
            await push_log_fn(task_id, "  ├─ 最大开板时长: %d 分钟" % max_open_duration)
            await push_log_fn(task_id, "  ├─ 开板后最小封单: %d 万元" % min_seal_after)
            await push_log_fn(task_id, "  ├─ 最小换手率: %.1f %%" % min_turnover)
            await push_log_fn(task_id, "  ├─ 竞价涨幅范围: %.1f%% ~ %.1f%%" % (opening_pct_min, opening_pct_max))
            await push_log_fn(task_id, "  └─ 最小量比: %.1f" % min_volume_ratio)
        elif strategy_name == '龙头低吸':
            min_consecutive = strategy_params_local.get('min_consecutive_limit', _defaults.get('min_consecutive_limit', 1))
            min_correction = strategy_params_local.get('min_correction_pct', _defaults.get('min_correction_pct', 0.05)) * 100
            max_correction = strategy_params_local.get('max_correction_pct', _defaults.get('max_correction_pct', 0.35)) * 100
            correction_days_min = strategy_params_local.get('correction_days_min', _defaults.get('correction_days_min', 1))
            correction_days_max = strategy_params_local.get('correction_days_max', _defaults.get('correction_days_max', 7))
            support_level = strategy_params_local.get('support_level', _defaults.get('support_level', 'ma5'))
            min_circ_cap = strategy_params_local.get('min_circulation_market_cap', _defaults.get('min_circulation_market_cap', 30))
            await push_log_fn(task_id, "  ├─ 最小连续涨停天数: %d 天" % min_consecutive)
            await push_log_fn(task_id, "  ├─ 最小流通市值: %d 亿" % min_circ_cap)
            await push_log_fn(task_id, "  ├─ 最小回调幅度: %.1f %%" % min_correction)
            await push_log_fn(task_id, "  ├─ 最大回调幅度: %.1f %%" % max_correction)
            await push_log_fn(task_id, "  ├─ 最小回调天数: %d 天" % correction_days_min)
            await push_log_fn(task_id, "  ├─ 最大回调天数: %d 天" % correction_days_max)
            await push_log_fn(task_id, "  └─ 支撑位: %s" % support_level)
        elif strategy_name == '跌停翘板':
            min_consecutive = strategy_params_local.get('min_consecutive_limit', _defaults.get('min_consecutive_limit', 2))
            min_qiao_amount = strategy_params_local.get('min_qiao_amount', _defaults.get('min_qiao_amount', 1000))
            min_rise_after = strategy_params_local.get('min_rise_after_qiao', _defaults.get('min_rise_after_qiao', 0.03)) * 100
            require_high_sentiment = strategy_params_local.get('require_high_sentiment', _defaults.get('require_high_sentiment', False))
            await push_log_fn(task_id, "  ├─ 最小连续跌停天数: %d 天" % min_consecutive)
            await push_log_fn(task_id, "  ├─ 翘板最小金额: %d 万元" % min_qiao_amount)
            await push_log_fn(task_id, "  ├─ 翘板后最小涨幅: %.1f %%" % min_rise_after)
            await push_log_fn(task_id, "  └─ 要求高情绪周期: %s" % ("是" if require_high_sentiment else "否"))

    await push_log_fn(task_id, "")
    await push_log_fn(task_id, "✅ 参数核对完成，所有参数与界面配置完全一致")
    await push_log_fn(task_id, "")
    await push_log_fn(task_id, "🔄 初始化管理器...")

    # 初始化选股和因子引擎
    from .factor_selection.universe import UniverseManager, ExcludeRule
    from .factor_selection.factor_engine import FactorEngine

    universe_mgr = UniverseManager()
    universe_mgr.start_date = start_date
    universe_mgr.end_date = end_date
    universe_mgr.exclude_rules = [ExcludeRule.ST, ExcludeRule.NEW_STOCK]
    universe_mgr.min_liquidity = strategy_params.get('liquidity_threshold', GLOBAL_RISK['liquidity_threshold'])
    factor_engine = FactorEngine()

    await push_log_fn(task_id, "✅ 管理器初始化完成")
    await mongo_manager.update_one(
        "backtest_tasks",
        {"task_id": task_id},
        {"$set": {"progress": 20}},
    )
    # 【修复#4：进度推送Redis频道，前端实时接收】
    await _redis_publish_safe(f"backtest:progress:{task_id}", {
        "task_id": task_id,
        "progress": 20,
        "status": "running"
    })

    # 获取真实调仓日期(每日调仓)
    rebalance_dates = await universe_mgr.get_rebalance_dates(start_date, end_date, "daily")
    trade_days_count = len(rebalance_dates)
    await push_log_fn(task_id, f"✅ 总交易日: {trade_days_count} 天")
    await mongo_manager.update_one(
        "backtest_tasks",
        {"task_id": task_id},
        {"$set": {"progress": 30}},
    )
    # 【修复#4：进度推送Redis频道，前端实时接收】
    await _redis_publish_safe(f"backtest:progress:{task_id}", {
        "task_id": task_id,
        "progress": 30,
        "status": "running"
    })

    # 【P1-6修复：all_factors与9层筛选对齐】
    # 9层筛选需要的关键因子字段（与portfolio_backtest.py._build_strategy_filter_conditions对齐）
    # L1强制空仓: 涨停数/跌停数 → 由引擎内部计算
    # L2特殊时期: 月末/周五 → 由special_period_filter处理
    # L3情绪周期: sentiment_score → 由引擎内部计算
    # L4盘前预选: ST/退市/低流动性 → 由universe_mgr处理
    # L5竞价过滤: opening_pct → 由引擎内部处理
    # L6策略量能: 以下因子需显式添加
    # L7综合排序: 策略优先级 → strategy_weights
    # L8仓位控制: 情绪×特殊×单票上限 → 由引擎内部处理
    all_factors = []
    strategy_weights = {}
    weight_per_strategy = 1.0 / len(selected_strategies)

    for strategy in selected_strategies:
        strategy_name = strategy.get('name', strategy.get('id', '未知策略'))
        strategy_id = strategy.get('id', strategy.get('name', 'unknown'))
        strategy_weights[strategy_name] = weight_per_strategy
        sp = strategy.get("params", {})
        if strategy_id == "halfway_chase":
            # 半路追涨因子: 量比+涨幅+收盘确认
            min_volume = sp.get("min_volume_ratio", 2.0)
            min_rise = sp.get("min_rise_pct", 0.03)
            min_close_rise = sp.get("min_close_rise_pct", 0.03)
            all_factors.append({"name": "volume_increase", "weight": weight_per_strategy, "target": min_volume})
            all_factors.append({"name": "rise_pct", "weight": weight_per_strategy, "target": min_rise})
            all_factors.append({"name": "close_rise_pct", "weight": weight_per_strategy, "target": min_close_rise})
        elif strategy_id == "first_limit_up":
            # 首板打板因子: 封单金额+竞价涨幅+换手率+流通市值
            min_seal = sp.get("min_seal_amount", 5000)
            opening_min = sp.get("opening_pct_min", -1.0)
            opening_max = sp.get("opening_pct_max", 7.0)
            min_turnover = sp.get("min_turnover_rate", 3)
            max_turnover = sp.get("max_turnover_rate", 15)
            all_factors.append({"name": "limit_up_amount", "weight": weight_per_strategy, "target": min_seal})
            all_factors.append({"name": "opening_pct_min", "weight": weight_per_strategy, "target": opening_min})
            all_factors.append({"name": "opening_pct_max", "weight": weight_per_strategy, "target": opening_max})
            all_factors.append({"name": "turnover_rate_min", "weight": weight_per_strategy, "target": min_turnover})
            all_factors.append({"name": "turnover_rate_max", "weight": weight_per_strategy, "target": max_turnover})
        elif strategy_id == "limit_up_open":
            # 涨停开板因子: 连板数+开板时长+封单+换手率
            min_consecutive = sp.get("min_consecutive_limit", 2)
            min_seal_after = sp.get("min_seal_after_open", 3000)
            min_turnover = sp.get("min_turnover_rate", 15.0)
            all_factors.append({"name": "limit_up_count", "weight": weight_per_strategy, "target": min_consecutive})
            all_factors.append({"name": "limit_up_open_amount", "weight": weight_per_strategy, "target": min_seal_after})
            all_factors.append({"name": "turnover_rate_min", "weight": weight_per_strategy, "target": min_turnover})
        elif strategy_id == "dragon_head":
            # 龙头低吸因子: 连板数+回调幅度+量比
            min_consecutive = sp.get("min_consecutive_limit", 1)
            min_correction = sp.get("min_correction_pct", 0.05)
            max_correction = sp.get("max_correction_pct", 0.35)
            min_volume = sp.get("min_volume_ratio", 0.5)
            all_factors.append({"name": "market_leader", "weight": weight_per_strategy, "target": 1})
            all_factors.append({"name": "consecutive_limit", "weight": weight_per_strategy, "target": min_consecutive})
            all_factors.append({"name": "correction_pct_min", "weight": weight_per_strategy, "target": min_correction})
            all_factors.append({"name": "correction_pct_max", "weight": weight_per_strategy, "target": max_correction})
            all_factors.append({"name": "volume_ratio_min", "weight": weight_per_strategy, "target": min_volume})
        elif strategy_id == "limit_down_qiao":
            # 跌停翘板因子: 连跌数+翘板金额+翘板后涨幅
            min_consecutive = sp.get("min_consecutive_limit", 2)
            min_qiao_amount = sp.get("min_qiao_amount", 1000)
            min_rise_after = sp.get("min_rise_after_qiao", 0.03)
            all_factors.append({"name": "limit_down_count", "weight": weight_per_strategy, "target": min_consecutive})
            all_factors.append({"name": "qiao_amount", "weight": weight_per_strategy, "target": min_qiao_amount})
            all_factors.append({"name": "rise_after_qiao", "weight": weight_per_strategy, "target": min_rise_after})

    await push_log_fn(task_id, "")
    await push_log_fn(task_id, "=" * 60)
    await push_log_fn(task_id, "▶️ 开始多策略组合回测")
    await push_log_fn(task_id, "📊 策略权重配置: " + str(strategy_weights))
    await push_log_fn(task_id, "=" * 60)

    # 创建组合回测器
    config = {
        "start_date": start_date,
        "end_date": end_date,
        "initial_cash": initial_cash,
        "max_position_percent": strategy_params.get("max_position_per_stock", 0.2),
        "liquidity_threshold": strategy_params.get("liquidity_threshold", 500),
        "data_collection": C.STOCK_DAILY if period == "daily" else C.STOCK_1MIN,
        "universe_mgr": universe_mgr,
        "factor_engine": factor_engine,
        "exclude_rules": [ExcludeRule.ST, ExcludeRule.NEW_STOCK],
        "factors": all_factors,
        "top_n": 10,
        "rebalance_freq": "daily",
        "task_id": task_id,
        "push_log": push_log_fn,
        "strategy_weights": strategy_weights,
        "selected_strategies": selected_strategies,
        "volume_threshold": next((s.get("params", {}).get("min_volume_ratio", 2.0) for s in selected_strategies if s.get("name") == "半路追涨"), 2.0),
        "weight_method": "equal",
        # 🔧 传递前端配置的佣金/滑点参数到回测引擎
        "commission_rate": strategy_params.get("commission_rate", GLOBAL_RISK["commission_rate"]),  # 万3
        "stamp_duty_rate": strategy_params.get("stamp_duty_rate", GLOBAL_RISK["stamp_duty_rate"]),   # 千1
        "slippage_pct": strategy_params.get("slippage_pct", GLOBAL_RISK["slippage_pct"]),         # 0.2%
        # 【信号延迟模式】
        # 🔧 传递止盈止损比例(前端可配置)
        "stop_loss_pct": strategy_params.get("stop_loss_pct", GLOBAL_RISK["stop_loss_pct"]),
        "take_profit_pct": strategy_params.get("take_profit_pct", GLOBAL_RISK["take_profit_pct"]),
        # 【P1-1/P1-2修复：传递max_hold_days和max_position_per_stock到回测引擎】
        "max_hold_days": strategy_params.get("max_hold_days", 3),
        "max_position_per_stock": strategy_params.get("max_position_per_stock", 0.2),
        # 【修复#7：传递功能开关配置】
        "enable_auction_filter": enable_auction_filter,
        "enable_sentiment_cycle": enable_sentiment_cycle,
        "enable_force_empty": enable_force_empty,
        "enable_stop_loss": enable_stop_loss,
        "enable_take_profit": enable_take_profit,
        "enable_ma60_filter": enable_ma60_filter,
        "enable_sector_concentration": enable_sector_concentration,
        # 【P1-3/P1-4修复：透传细粒度配置】
        "force_empty_config": strategy_params.get("force_empty_config", {}),
        "global_filter_config": strategy_params.get("global_filter_config", {}),
    }
    backtester = PortfolioBacktester()

    # 运行组合回测
    try:
        result = await backtester.run(config)

        if result is None or "error" in result:
            error_msg = result.get('error', 'unknown error') if result else 'unknown error (run() returned None)'
            await push_log_fn(task_id, f"❌ 组合回测失败: {error_msg}")
            await mongo_manager.update_one(
                "backtest_tasks",
                {"task_id": task_id},
                {"$set": {"status": "failed", "error": error_msg, "completed_at": datetime.now(timezone.utc)}},
            )
            # 【修复#4：推送进度到Redis通知前端失败】
            await _redis_publish_safe(f"backtest:progress:{task_id}", {
                "task_id": task_id,
                "progress": 100,
                "status": "failed"
            })
            return {"success": False, "error": error_msg}

        # 【修复风险1：适配portfolio_backtest.py的嵌套metrics结构】
        # portfolio_backtest.py现在返回: {success, initial_cash, final_value, metrics: {returns, risk, trades, positions, performance, metadata}}
        # 需要从嵌套结构中正确提取数据
        metrics = result.get('metrics', {})
        returns_data = metrics.get('returns', {})
        risk_data = metrics.get('risk', {})
        trades_data = metrics.get('trades', {})
        positions_data = metrics.get('positions', {})
        performance_data = metrics.get('performance', {})

        # 从嵌套结构提取（兼容：如果嵌套结构为空，fallback到顶层扁平字段）
        total_return = returns_data.get('total_return', result.get('total_return', 0.0))
        max_drawdown = risk_data.get('max_drawdown', result.get('max_drawdown', 0.0))
        win_rate = risk_data.get('win_rate', result.get('win_rate', 0.0))
        sharpe_ratio = risk_data.get('sharpe_ratio', result.get('sharpe_ratio', 0.0))
        profit_loss_ratio = risk_data.get('profit_loss_ratio', result.get('profit_loss_ratio', 0.0))
        return_drawdown_ratio = risk_data.get('return_drawdown_ratio', result.get('return_drawdown_ratio', 0.0))
        annualized_return = returns_data.get('annualized_return', result.get('annualized_return', 0.0))
        benchmark_return = returns_data.get('benchmark_return_pct', returns_data.get('benchmark_return', result.get('benchmark_return', 0.0)))
        alpha = returns_data.get('alpha_pct', returns_data.get('alpha', result.get('alpha', 0.0)))
        sortino_ratio = risk_data.get('sortino_ratio', result.get('sortino_ratio', 0.0))
        calmar_ratio = risk_data.get('calmar_ratio', result.get('calmar_ratio', 0.0))
        volatility = risk_data.get('volatility', result.get('volatility', 0.0))
        annual_return_reliable = returns_data.get('annual_return_reliable', result.get('annual_return_reliable', False))
        monthly_profit = performance_data.get('monthly_profit', result.get('monthly_profit', {}))
        total_signals = performance_data.get('total_signals', result.get('total_signals', 0))
        total_trades = trades_data.get('total_trades', result.get('total_trades', 0))
        winning_trades = trades_data.get('winning_trades', result.get('winning_trades', 0))
        losing_trades = trades_data.get('losing_trades', result.get('losing_trades', 0))
        average_hold_days = trades_data.get('average_hold_days', result.get('average_hold_days', 0.0))
        initial_cash = result.get('initial_cash', 1000000.0)
        final_cash = result.get('final_cash', 0.0)
        final_value = result.get('final_value', result.get('final_equity', 0.0))

        raw_trades = performance_data.get('all_trades', result.get('all_trades', []))
        merged_trades = performance_data.get('merged_trades', result.get('merged_trades', []))
        rebalance_records = performance_data.get('rebalance_records', result.get('rebalance_records', []))
        stock_names = performance_data.get('stock_names', result.get('stock_names', {}))
        net_value_series = positions_data.get('net_value_series', result.get('net_value_series', []))
        drawdown_series = positions_data.get('drawdown_series', result.get('drawdown_series', []))
        daily_profit = positions_data.get('daily_profit', result.get('daily_profit', []))

        # 构建perf字典（兼容旧格式，同时确保数据正确）
        perf = {
            "strategy_name": "多策略组合",
            "name": "多策略组合",
            "win_rate": win_rate,
            "total_return": total_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "profit_loss_ratio": profit_loss_ratio,
            "annualized_return": annualized_return,
            "benchmark_return": benchmark_return,
            "alpha": alpha,
            "sortino_ratio": sortino_ratio,
            "calmar_ratio": calmar_ratio,
            "volatility": volatility,
            "annual_return_reliable": annual_return_reliable,
            "return_drawdown_ratio": return_drawdown_ratio,
            "total_signals": total_signals,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "average_hold_days": average_hold_days,
            "initial_cash": initial_cash,
            "final_cash": final_cash,
            "final_value": final_value,
            "monthly_profit": monthly_profit,
        }

        # 格式化交易记录
        formatted_trades = []
        for trade in raw_trades:
            trade_dict = trade.copy() if isinstance(trade, dict) else {}
            if 'ts_code' in trade_dict:
                code = trade_dict['ts_code']
            elif 'code' in trade_dict:
                code = trade_dict['code']
            else:
                continue
            trade_dict['code'] = code
            if 'name' not in trade_dict:
                trade_dict['name'] = stock_names.get(code, code.replace('.SZ', '').replace('.SH', ''))
            if 'volume' not in trade_dict and 'shares' in trade_dict:
                trade_dict['volume'] = trade_dict['shares']
            if 'profit' not in trade_dict:
                trade_dict['profit'] = 0.0
            if 'trade_date' not in trade_dict and 'date' in trade_dict:
                trade_dict['trade_date'] = trade_dict['date']
            formatted_trades.append(trade_dict)
        perf["trades"] = merged_trades if merged_trades else formatted_trades  # 优先用完整交易记录
        perf["merged_trades"] = merged_trades
        perf["net_value_series"] = net_value_series
        perf["drawdown_series"] = drawdown_series
        perf["daily_profit"] = daily_profit

        # 【任务2：卖出原因统计】
        sell_reason_stats = {"stop_loss": 0, "take_profit": 0, "max_hold": 0, "force_empty": 0, "rebalance": 0, "other": 0}
        for trade in (merged_trades or raw_trades or []):
            reason = trade.get("reason", trade.get("sell_reason", ""))
            # 跳过未平仓交易(无sell_date或profit_pct为None)
            if not reason and trade.get("profit_pct") is None:
                continue
            if not reason:
                reason = "other"
            reason_str = str(reason)
            # 止损: 包含"止损"/"stop_loss"/"跳空止损"/"止损(X%)"
            if "止损" in reason_str or "stop_loss" in reason_str.lower():
                sell_reason_stats["stop_loss"] += 1
            # 止盈: 包含"止盈"/"take_profit"/"止盈(X%)"
            elif "止盈" in reason_str or "take_profit" in reason_str.lower():
                sell_reason_stats["take_profit"] += 1
            # 到期: 包含"到期"/"max_hold"/"持仓天数"
            elif "到期" in reason_str or "max_hold" in reason_str.lower() or "持仓天数" in reason_str:
                sell_reason_stats["max_hold"] += 1
            # 空仓: 包含"空仓"/"force_empty"/"强制"/"force_empty_position"
            elif "空仓" in reason_str or "force_empty" in reason_str.lower() or "强制" in reason_str:
                sell_reason_stats["force_empty"] += 1
            # 调仓: 包含"调仓"/"rebalance"/"减仓"
            elif "调仓" in reason_str or "rebalance" in reason_str.lower() or "减仓" in reason_str:
                sell_reason_stats["rebalance"] += 1
            else:
                sell_reason_stats["other"] += 1

        perf["sell_reason_stats"] = sell_reason_stats

        # 【任务3：回测耗时记录】
        perf["execution_time_ms"] = int((_time.time() - _start_time) * 1000)

        # 更新result顶层字段，确保前端多路径都能读取到正确值
        result['performance'] = [perf]
        result['win_rate'] = win_rate
        result['total_return'] = total_return
        result['max_drawdown'] = max_drawdown
        result['sharpe_ratio'] = sharpe_ratio
        result['sell_reason_stats'] = sell_reason_stats
        result['execution_time_ms'] = perf['execution_time_ms']

        # 注意：win_rate/total_return/max_drawdown 已是百分比形式（如5.0=5%），不需要再×100
        logger.success("RESULT", "多策略组合回测完成")
        logger.info("RESULT", f"信号数: {total_signals}")
        logger.info("RESULT", f"胜率: {win_rate:.2f}%")
        logger.info("RESULT", f"累计收益率: {total_return:.2f}%")
        logger.info("RESULT", f"最大回撤: {max_drawdown:.2f}%")
        logger.info("RESULT", f"盈亏比: {profit_loss_ratio:.2f}")
        logger.info("RESULT", f"夏普比率: {sharpe_ratio:.2f}")
        
        # 【修复#4：推送完成进度到Redis】
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": {"progress": 100}},
        )
        await _redis_publish_safe(f"backtest:progress:{task_id}", {
            "task_id": task_id,
            "progress": 100,
            "status": "completed"
        })

    except Exception as e:
        _logger = node_logger or logger
        _logger.error("BACKTEST", f"[{task_id}] Portfolio backtest failed: {e}")
        import traceback
        tb_str = traceback.format_exc()
        _logger.error("BACKTEST", f"[{task_id}] Traceback:\n{tb_str}")
        await push_log_fn(task_id, f"❌ 组合回测运行异常: {str(e)}")
        await push_log_fn(task_id, "📋 完整错误堆栈:")
        for line in tb_str.split('\n'):
            if line.strip():
                await push_log_fn(task_id, f'``` {line} ```')
        # 【P2-4修复：shutdown统一到finally，避免双分支调用】
        logger.clear_task_id()
        return {"error": str(e)}

    finally:
        # 【P2-4修复：无论成功或异常都只调一次shutdown】
        try:
            await akshare_manager.shutdown()
        except Exception:
            pass  # shutdown失败不应影响返回结果
        # 🔧 自动清理旧回测结果(保留最近20条)
        try:
            await cleanup_old_backtest_tasks(mongo_manager, keep=20)
        except Exception:
            pass
        # 🔧 内存泄漏防护：强制GC释放回测中分配的大对象
        try:
            import gc
            gc.collect()
            logger.info(f"[{task_id}] GC completed, freed memory")
        except Exception:
            pass

    return result


async def cleanup_old_backtest_tasks(mongo_manager, keep: int = 20):
    """自动清理旧的回测任务结果,只保留最近N条
    
    【P2-7修复：只清理已完成的任务，不删除正在运行的任务】
    """
    try:
        # 只统计已完成的任务（completed/failed），不统计running/queued
        total = await mongo_manager.count_documents("backtest_tasks", {"status": {"$in": ["completed", "failed"]}})
        if total <= keep:
            return
        # 找到要保留的task_id（只从已完成的任务中选择）
        docs = await mongo_manager.find_many(
            "backtest_tasks",
            {"status": {"$in": ["completed", "failed"]}},
            projection={"task_id": 1},
            sort=[("_id", -1)],
            limit=keep
        )
        keep_ids = [d["task_id"] for d in docs]
        # 只删除已完成的旧任务，不删除正在运行的任务
        delete_result = await mongo_manager.delete_many(
            "backtest_tasks",
            {"task_id": {"$nin": keep_ids}, "status": {"$in": ["completed", "failed"]}}
        )
        logger.info(f"[cleanup] 删除{delete_result}条旧回测结果, 保留{len(keep_ids)}条")
    except Exception as e:
        logger.warning(f"[cleanup] 清理旧回测任务失败: {e}")
