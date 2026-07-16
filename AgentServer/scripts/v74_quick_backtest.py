"""V74快速验证回测 - 3个月,验证策略分解+收益"""
import asyncio
import sys
import os
import types
import time

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

    task_id = f"v74q_{int(time.time())}"
    logs = []

    async def push_log(tid, msg):
        logs.append(msg)
        if any(k in msg for k in ['📊', '🎯', '收益', 'Alpha', '胜率', '盈亏', '回撤', '夏普', '❌', '中止']):
            print(msg)

    inner_params = {
        "start_date": "20260105",
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

    print(f"🚀 V74快速3月回测 | {inner_params['start_date']}~{inner_params['end_date']}")
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

    # 提取结果
    metrics = result.get('metrics', {})
    returns = metrics.get('returns', {})
    risk_m = metrics.get('risk', {})
    trades = metrics.get('trades', {})

    total_return = returns.get('total_return_pct', 0)
    max_dd = risk_m.get('max_drawdown_pct', 0)
    sharpe = risk_m.get('sharpe_ratio', 0)
    win_rate = risk_m.get('win_rate_pct', 0)

    print(f"\n{'='*65}")
    print(f"📊 V74快速3月结果 ({elapsed:.1f}s)")
    print(f"{'='*65}")
    print(f"  总收益: {total_return:.2f}%")
    print(f"  最大回撤: {max_dd:.2f}%")
    print(f"  夏普: {sharpe:.2f}")
    print(f"  胜率: {win_rate:.1f}%")
    print(f"  交易: {trades.get('total_trades', 0)}")

    # 策略分解（直接从result.strategy_results读取）
    sr = result.get('strategy_results', {})
    print("\n  策略分解:")
    for sname, sdata in sr.items():
        sn = sdata.get('strategy_name', sname)
        wr = sdata.get('win_rate', 0)
        tr = sdata.get('total_return', sdata.get('cumulative_profit_pct', 0))
        tc = sdata.get('trades_count', 0)
        mdd = sdata.get('max_drawdown', 0)
        print(f"    [{sn}] 收益{tr:.2f}% 胜率{wr:.1f}% 笔{tc} 回撤{mdd:.2f}%")

    # 卖出原因
    sell_stats = result.get('sell_reason_stats', {})
    if sell_stats:
        print("\n  卖出原因:")
        for reason, count in sorted(sell_stats.items(), key=lambda x: -x[1]):
            if count > 0:
                print(f"    {reason}: {count}")

asyncio.run(main())
