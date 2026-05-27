"""V74全量2年回测 - P0修复验证 + 优化基线"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

async def main():
    await mongo_manager.initialize()
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    from nodes.backtest_engine.strategy_defaults import ALL_STRATEGIES, GLOBAL_RISK

    task_id = f"v74_full_{int(time.time())}"
    logs = []

    async def push_log(tid, msg):
        logs.append(msg)
        # 只打印关键信息
        if any(k in msg for k in ['📊', '🎯', '收益', 'Alpha', '胜率', '盈亏', '回撤', '夏普', '索提', '交易笔', '策略收益', '❌', '总净值', '中止']):
            print(msg)

    inner_params = {
        "start_date": "20240506",
        "end_date": "20260511",
        "initial_cash": 1000000,
        "period": "daily",
        "enable_stop_loss": True,
        "enable_take_profit": True,
        "enable_ma60_filter": True,
        "enable_sector_concentration": True,
        "enable_force_empty": False,
        "enable_sentiment_cycle": True,
        "enable_auction_filter": False,
        "strategies": ["halfway_chase", "first_limit_up", "dragon_head", "limit_down_qiao"],
        "selected_strategies": ALL_STRATEGIES,
        "params": {
            "stop_loss_pct": GLOBAL_RISK["stop_loss_pct"],
            "take_profit_pct": GLOBAL_RISK["take_profit_pct"],
            "max_hold_days": GLOBAL_RISK["max_hold_days"],
            "max_position_per_stock": GLOBAL_RISK["max_position_per_stock"],
            "liquidity_threshold": GLOBAL_RISK["liquidity_threshold"],
            "max_total_position": GLOBAL_RISK["max_total_position"],
            "commission_rate": GLOBAL_RISK["commission_rate"],
            "stamp_duty_rate": GLOBAL_RISK["stamp_duty_rate"],
            "slippage_pct": GLOBAL_RISK["slippage_pct"],
        },
    }

    params = {"params": inner_params}

    print(f"🚀 V74全量2年回测 | {inner_params['start_date']}~{inner_params['end_date']}")
    t0 = time.time()
    result = await execute_ultra_short_backtest(
        params=params,
        push_log_fn=push_log,
        node_logger=None,
        task_id=task_id,
    )
    elapsed = time.time() - t0

    if result.get("error"):
        print(f"❌ 回测失败: {result['error']}")
        return

    # 提取结果（兼容多种格式）
    metrics = result.get('metrics', {})
    returns = metrics.get('returns', {})
    risk_m = metrics.get('risk', {})
    trades = metrics.get('trades', {})

    total_return = returns.get('total_return_pct', 0)
    alpha = returns.get('alpha_pct', 0)
    max_dd = risk_m.get('max_drawdown_pct', 0)
    sharpe = risk_m.get('sharpe_ratio', 0)
    win_rate = risk_m.get('win_rate_pct', 0)
    pl_ratio = risk_m.get('profit_loss_ratio', 0)
    total_trades = trades.get('total_trades', 0)

    print(f"\n{'='*65}")
    print(f"📊 V74全量2年结果 ({elapsed:.1f}s)")
    print(f"{'='*65}")
    print(f"  总收益:   {total_return:.2f}%")
    print(f"  Alpha:    {alpha:.2f}%")
    print(f"  最大回撤: {max_dd:.2f}%")
    print(f"  夏普:     {sharpe:.2f}")
    print(f"  胜率:     {win_rate:.1f}%")
    print(f"  盈亏比:   {pl_ratio:.2f}")
    print(f"  交易笔数: {total_trades}")

    # 策略级结果
    sr = result.get('strategy_results', {})
    for sname, sdata in sr.items():
        sname_display = sdata.get('strategy_name', sname)
        s_wr = sdata.get('win_rate', 0)
        s_tr = sdata.get('total_return', sdata.get('cumulative_profit_pct', 0))
        s_tc = sdata.get('trades_count', 0)
        s_mdd = sdata.get('max_drawdown', 0)
        print(f"  [{sname_display}] 收益{s_tr:.2f}% 胜率{s_wr:.1f}% 笔{s_tc} 回撤{s_mdd:.2f}%")

    # 卖出原因统计
    sell_stats = result.get('sell_reason_stats', {})
    if sell_stats:
        print(f"\n  卖出原因统计:")
        for reason, count in sorted(sell_stats.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}")

    # 保存完整结果
    summary = {
        "total_return_pct": total_return,
        "alpha_pct": alpha,
        "max_drawdown_pct": max_dd,
        "sharpe_ratio": sharpe,
        "sortino_ratio": risk_m.get('sortino_ratio', 0),
        "win_rate_pct": win_rate,
        "profit_loss_ratio": pl_ratio,
        "total_trades": total_trades,
        "elapsed": elapsed,
        "strategy_results": {},
        "sell_reason_stats": sell_stats,
    }
    for sname, sdata in sr.items():
        summary["strategy_results"][sname] = {
            "strategy_name": sdata.get('strategy_name', sname),
            "win_rate": sdata.get('win_rate', 0),
            "total_return": sdata.get('total_return', sdata.get('cumulative_profit_pct', 0)),
            "trades_count": sdata.get('trades_count', 0),
            "max_drawdown": sdata.get('max_drawdown', 0),
            "profit_loss_ratio": sdata.get('profit_loss_ratio', 0),
        }

    out_path = os.path.join(BASE, 'V74_baseline_summary.json')
    with open(out_path, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n📁 {out_path}")

asyncio.run(main())
