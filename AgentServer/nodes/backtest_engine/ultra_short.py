"""
超短策略回测执行器

从node.py拆分出的超短策略回测执行逻辑。
"""

import subprocess
from datetime import datetime
from typing import Dict, Any, List

from core.managers import mongo_manager, akshare_manager, redis_manager
from core.utils.logger import logger

from nodes.backtest_engine.factor_selection import PortfolioBacktester


# 默认所有策略（兜底用）
ALL_STRATEGIES = [
    {"id": "halfway_chase", "name": "半路追涨", "params": {}},
    {"id": "first_limit_up", "name": "首板打板", "params": {}},
    {"id": "limit_up_open", "name": "涨停开板", "params": {}},
    {"id": "leader_buy_dip", "name": "龙头低吸", "params": {}},
    {"id": "limit_down_qiao", "name": "跌停翘板", "params": {}},
]


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

    # 参数在params子对象中，因为web层调用时封装在params里
    req_params = params.get("params", {})
    strategies = req_params.get("strategies", [])
    start_date = req_params.get("start_date", "20260105")
    end_date = req_params.get("end_date", "20260320")
    initial_cash = req_params.get("initial_cash", 1000000)
    strategy_params = req_params.get("params", {})
    period = req_params.get("period", "daily")

    # 打印初始化阶段头部
    logger.success("INIT", "============== 回测任务启动 ==============")
    logger.info("INIT", f"回测时间：{start_date} → {end_date}")
    logger.info("INIT", f"初始资金：{initial_cash:,.0f} 元")

    # 解析选中策略名称
    strategy_name_map = {
        "halfway_chase": "半路追涨",
        "first_limit_up": "首板打板",
        "limit_up_open": "涨停开板",
        "leader_buy_dip": "龙头低吸",
        "limit_down_qiao": "跌停翘板"
    }
    selected_strategy_names = [strategy_name_map.get(s, s) for s in strategies]
    logger.info("INIT", f"选中策略：【{'、'.join(selected_strategy_names)}】")

    # 打印全局参数
    logger.info("INIT", f"全局参数：流动性门槛{strategy_params.get('liquidity_threshold', 500)}万/止损{strategy_params.get('stop_loss_pct', 0.02)*100}%/止盈{strategy_params.get('take_profit_pct', 0.07)*100}%/最大持仓{strategy_params.get('max_hold_days', 3)}天/单票仓位{strategy_params.get('max_position_per_stock', 0.2)*100}%/总仓位{strategy_params.get('max_position', 0.7)*100}%")

    # 打印功能开关
    enable_force_empty = req_params.get("enable_force_empty", True)
    enable_sentiment_cycle = req_params.get("enable_sentiment_cycle", True)
    enable_auction_filter = req_params.get("enable_auction_filter", True)
    logger.info("INIT", f"功能开关：强制空仓{'✅' if enable_force_empty else '❌'} / 情绪周期{'✅' if enable_sentiment_cycle else '❌'} / 竞价过滤{'✅' if enable_auction_filter else '❌'}")

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
        {"$set": {"status": "running", "started_at": datetime.utcnow(), "progress": 10, "logs": []}},
    )
    # 【修复#4：进度推送Redis频道，前端实时接收】
    await redis_manager.publish(f"backtest:progress:{task_id}", {
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
    await push_log_fn(task_id, "├─ 流动性门槛: %s 万元" % strategy_params.get('liquidity_threshold', 500))
    await push_log_fn(task_id, "├─ 单票最大仓位: %.1f %%" % (strategy_params.get('max_position_per_stock', 0.2)*100))
    await push_log_fn(task_id, "├─ 总仓位上限: %.1f %%" % (strategy_params.get('max_position', 0.7)*100))
    await push_log_fn(task_id, "├─ 止损比例: %.1f %%" % (strategy_params.get('stop_loss_pct', 0.02)*100))
    await push_log_fn(task_id, "├─ 止盈比例: %.1f %%" % (strategy_params.get('take_profit_pct', 0.07)*100))
    await push_log_fn(task_id, "├─ 最大持仓天数: %d 天" % strategy_params.get('max_hold_days', 3))
    await push_log_fn(task_id, "├─ 强制空仓规则: %s" % ("已启用" if req_params.get('enable_force_empty', True) else "已关闭"))
    await push_log_fn(task_id, "├─ 情绪周期算法: %s" % ("已启用" if req_params.get('enable_sentiment_cycle', True) else "已关闭"))
    await push_log_fn(task_id, "└─ 竞价过滤规则: %s" % ("已启用" if req_params.get('enable_auction_filter', True) else "已关闭"))

    for s in selected_strategies:
        strategy_name = s.get('name', s.get('id', '未知策略'))
        await push_log_fn(task_id, "")
        await push_log_fn(task_id, "🎯 【%s】" % strategy_name)
        strategy_params_local = s.get('params', {})
        if "params" not in s:
            s["params"] = {}
        s["params"].update(strategy_params_local)
        if strategy_name == '半路追涨':
            min_rise = strategy_params_local.get('min_rise_pct', 0.03) * 100
            max_rise = strategy_params_local.get('max_rise_pct', 0.07) * 100
            volume_val = strategy_params_local.get('volume_threshold', strategy_params_local.get('min_volume_ratio', 1.5))
            allow_after_10am = strategy_params_local.get('allow_after_10am', False)
            await push_log_fn(task_id, "  ├─ 最小涨幅: %.1f %%" % min_rise)
            await push_log_fn(task_id, "  ├─ 最大涨幅: %.1f %%" % max_rise)
            await push_log_fn(task_id, "  ├─ 量比阈值: %.1f 倍 (应用到筛选逻辑)" % volume_val)
            await push_log_fn(task_id, "  └─ 允许10点后买入: %s" % ("是" if allow_after_10am else "否"))
            s["params"]["volume_threshold"] = volume_val
            s["params"]["min_volume_ratio"] = volume_val
        elif strategy_name == '首板打板':
            min_seal = strategy_params_local.get('min_seal_amount', 5000)
            max_limit_time = strategy_params_local.get('max_limit_up_time', '10:00')
            max_cap = strategy_params_local.get('max_circulation_market_cap', 100)
            max_blast = strategy_params_local.get('max_blast_count', 1)
            require_hot = strategy_params_local.get('require_hot_sector', True)
            await push_log_fn(task_id, "  ├─ 最小封单金额: %d 万元" % min_seal)
            await push_log_fn(task_id, "  ├─ 最晚涨停时间: %s" % max_limit_time)
            await push_log_fn(task_id, "  ├─ 最大流通市值: %d 亿" % max_cap)
            await push_log_fn(task_id, "  ├─ 最大开板次数: %d 次" % max_blast)
            await push_log_fn(task_id, "  └─ 要求热门板块: %s" % ("是" if require_hot else "否"))
        elif strategy_name == '涨停开板':
            min_consecutive = strategy_params_local.get('min_consecutive_limit', 2)
            max_open_duration = strategy_params_local.get('max_open_duration', 5)
            min_seal_after = strategy_params_local.get('min_seal_after_open', 3000)
            min_turnover = strategy_params_local.get('min_turnover_rate', 0.15) * 100
            await push_log_fn(task_id, "  ├─ 最小连续涨停天数: %d 天" % min_consecutive)
            await push_log_fn(task_id, "  ├─ 最大开板时长: %d 分钟" % max_open_duration)
            await push_log_fn(task_id, "  ├─ 开板后最小封单: %d 万元" % min_seal_after)
            await push_log_fn(task_id, "  └─ 最小换手率: %.1f %%" % min_turnover)
        elif strategy_name == '龙头低吸':
            min_consecutive = strategy_params_local.get('min_consecutive_limit', 3)
            min_correction = strategy_params_local.get('min_correction_pct', 0.15) * 100
            max_correction = strategy_params_local.get('max_correction_pct', 0.3) * 100
            correction_days_min = strategy_params_local.get('correction_days_min', 2)
            correction_days_max = strategy_params_local.get('correction_days_max', 5)
            support_level = strategy_params_local.get('support_level', 'ma5')
            await push_log_fn(task_id, "  ├─ 最小连续涨停天数: %d 天" % min_consecutive)
            await push_log_fn(task_id, "  ├─ 最小回调幅度: %.1f %%" % min_correction)
            await push_log_fn(task_id, "  ├─ 最大回调幅度: %.1f %%" % max_correction)
            await push_log_fn(task_id, "  ├─ 最小回调天数: %d 天" % correction_days_min)
            await push_log_fn(task_id, "  ├─ 最大回调天数: %d 天" % correction_days_max)
            await push_log_fn(task_id, "  └─ 支撑位: %s" % support_level)
        elif strategy_name == '跌停翘板':
            min_consecutive = strategy_params_local.get('min_consecutive_limit', 3)
            min_qiao_amount = strategy_params_local.get('min_qiao_amount', 10000)
            min_rise_after = strategy_params_local.get('min_rise_after_qiao', 0.03) * 100
            require_high_sentiment = strategy_params_local.get('require_high_sentiment', True)
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
    universe_mgr.min_liquidity = strategy_params.get('liquidity_threshold', 500)
    factor_engine = FactorEngine()

    await push_log_fn(task_id, "✅ 管理器初始化完成")
    await mongo_manager.update_one(
        "backtest_tasks",
        {"task_id": task_id},
        {"$set": {"progress": 20}},
    )
    # 【修复#4：进度推送Redis频道，前端实时接收】
    await redis_manager.publish(f"backtest:progress:{task_id}", {
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
    await redis_manager.publish(f"backtest:progress:{task_id}", {
        "task_id": task_id,
        "progress": 30,
        "status": "running"
    })

    # 合并所有选中策略的因子和过滤条件
    all_factors = []
    strategy_weights = {}
    weight_per_strategy = 1.0 / len(selected_strategies)

    for strategy in selected_strategies:
        strategy_name = strategy.get('name', strategy.get('id', '未知策略'))
        strategy_id = strategy.get('id', strategy.get('name', 'unknown'))
        strategy_weights[strategy_name] = weight_per_strategy
        sp = strategy.get("params", {})
        if strategy_id == "halfway_chase":
            min_volume = sp.get("min_volume_ratio", 1.5)  # 【修复风险9：默认值统一为1.5】
            all_factors.append({"name": "volume_increase", "weight": weight_per_strategy, "target": min_volume})
        elif strategy_id == "first_limit_up":
            min_seal = sp.get("min_seal_amount", 5000)
            all_factors.append({"name": "limit_up_amount", "weight": weight_per_strategy, "target": min_seal})
        elif strategy_id == "limit_up_open":
            min_consecutive = sp.get("min_consecutive_limit", 2)
            min_seal_after = sp.get("min_seal_after_open", 3000)
            all_factors.append({"name": "limit_up_count", "weight": weight_per_strategy, "target": min_consecutive})
            all_factors.append({"name": "limit_up_open_amount", "weight": weight_per_strategy, "target": min_seal_after})
        elif strategy_id == "leader_buy_dip":
            all_factors.append({"name": "market_leader", "weight": weight_per_strategy, "target": 1})
        elif strategy_id == "limit_down_qiao":
            min_consecutive = sp.get("min_consecutive_limit", 3)
            all_factors.append({"name": "limit_down_count", "weight": weight_per_strategy, "target": min_consecutive})

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
        "data_collection": "stock_daily_ak_full" if period == "daily" else "stock_1min",
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
        "volume_threshold": next((s.get("params", {}).get("min_volume_ratio", 1.5) for s in selected_strategies if s.get("name") == "半路追涨"), 1.5),
        "weight_method": "equal",
        # 🔧 传递前端配置的佣金/滑点参数到回测引擎
        "commission_rate": strategy_params.get("commission_rate", 0.0003),  # 万3
        "stamp_duty_rate": strategy_params.get("stamp_duty_rate", 0.001),   # 千1
        "slippage_pct": strategy_params.get("slippage_pct", 0.002),         # 0.2%
        # 【修复#7：传递功能开关配置】
        "enable_auction_filter": enable_auction_filter,
        "enable_sentiment_cycle": enable_sentiment_cycle,
        "enable_force_empty": enable_force_empty,
    }
    backtester = PortfolioBacktester()

    # 运行组合回测
    try:
        result = await backtester.run(config)

        if result is None or "error" in result:
            error_msg = result.get('error', 'unknown error') if result else 'unknown error'
            await push_log_fn(task_id, f"❌ 组合回测失败: {error_msg}")
            await mongo_manager.update_one(
                "backtest_tasks",
                {"task_id": task_id},
                {"$set": {"status": "failed", "error": error_msg, "completed_at": datetime.utcnow()}},
            )
            # 【修复#4：推送进度到Redis通知前端失败】
            await redis_manager.publish(f"backtest:progress:{task_id}", {
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
        total_signals = performance_data.get('total_signals', result.get('total_signals', 0))
        total_trades = trades_data.get('total_trades', result.get('total_trades', 0))
        winning_trades = trades_data.get('winning_trades', result.get('winning_trades', 0))
        losing_trades = trades_data.get('losing_trades', result.get('losing_trades', 0))
        average_hold_days = trades_data.get('average_hold_days', result.get('average_hold_days', 0.0))
        initial_cash = result.get('initial_cash', 1000000.0)
        final_cash = result.get('final_cash', 0.0)
        final_value = result.get('final_value', result.get('final_equity', 0.0))

        raw_trades = performance_data.get('all_trades', result.get('all_trades', []))
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
            "return_drawdown_ratio": return_drawdown_ratio,
            "total_signals": total_signals,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "average_hold_days": average_hold_days,
            "initial_cash": initial_cash,
            "final_cash": final_cash,
            "final_value": final_value,
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
        perf["trades"] = formatted_trades
        perf["net_value_series"] = net_value_series
        perf["drawdown_series"] = drawdown_series
        perf["daily_profit"] = daily_profit

        # 更新result顶层字段，确保前端多路径都能读取到正确值
        result['performance'] = [perf]
        result['win_rate'] = win_rate
        result['total_return'] = total_return
        result['max_drawdown'] = max_drawdown
        result['sharpe_ratio'] = sharpe_ratio

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
        await redis_manager.publish(f"backtest:progress:{task_id}", {
            "task_id": task_id,
            "progress": 100,
            "status": "completed"
        })

    except Exception as e:
        node_logger.error(f"[{task_id}] Portfolio backtest failed: {e}")
        import traceback
        tb_str = traceback.format_exc()
        node_logger.error(f"[{task_id}] Traceback:\n{tb_str}")
        await push_log_fn(task_id, f"❌ 组合回测运行异常: {str(e)}")
        await push_log_fn(task_id, "📋 完整错误堆栈:")
        for line in tb_str.split('\n'):
            if line.strip():
                await push_log_fn(task_id, f'``` {line} ```')
        await akshare_manager.shutdown()
        logger.clear_task_id()
        return {"error": str(e)}

    await akshare_manager.shutdown()
    logger.clear_task_id()

    return result
