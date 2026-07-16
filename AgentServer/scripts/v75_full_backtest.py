"""V75全量2年回测 - 验证所有P0修复"""
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

    task_id = f"v75f_{int(time.time())}"
    logs = []

    async def push_log(tid, msg):
        logs.append(msg)
        if any(k in msg for k in ['📊', '🎯', '收益', 'Alpha', '胜率', '盈亏', '回撤', '夏普', '❌', '中止']):
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
        "enable_force_empty": True,
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

    print(f"🚀 V75全量2年回测 | {inner_params['start_date']}~{inner_params['end_date']}")
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
    sortino = risk_m.get('sortino_ratio', 0)
    calmar = risk_m.get('calmar_ratio', 0)
    volatility = risk_m.get('volatility_pct', 0)

    print(f"\n{'='*65}")
    print(f"📊 V75全量2年结果 ({elapsed:.1f}s)")
    print(f"{'='*65}")
    print(f"  总收益: {total_return:.2f}%")
    print(f"  最大回撤: {max_dd:.2f}%")
    print(f"  夏普: {sharpe:.2f}")
    print(f"  索提诺: {sortino:.2f}")
    print(f"  卡玛: {calmar:.2f}")
    print(f"  波动率: {volatility:.2f}%")
    print(f"  胜率: {win_rate:.1f}%")
    print(f"  交易: {trades.get('total_trades', 0)}")

    # V75新增指标
    max_consec_loss = result.get('max_consecutive_losses', 'N/A')
    max_day_loss = result.get('max_single_day_loss_pct', 'N/A')
    max_trade_loss_pct = result.get('max_single_trade_loss_pct', 'N/A')
    print(f"  最大连续亏损笔数: {max_consec_loss}")
    print(f"  最大单日亏损%: {max_day_loss:.2f}%" if isinstance(max_day_loss, float) else f"  最大单日亏损%: {max_day_loss}")
    print(f"  单笔最大亏损%: {max_trade_loss_pct:.2f}%" if isinstance(max_trade_loss_pct, float) else f"  单笔最大亏损%: {max_trade_loss_pct}")

    # 策略分解
    sr = result.get('strategy_results', {})
    print("\n  策略分解:")
    for sname, sdata in sr.items():
        sn = sdata.get('strategy_name', sname)
        wr = sdata.get('win_rate', 0)
        tr = sdata.get('total_return', 0)
        cpl = sdata.get('cumulative_profit_pct', 0)
        tc = sdata.get('trades_count', 0)
        mdd = sdata.get('max_drawdown', 0)
        print(f"    [{sn}] 加权收益{tr:.2f}% 累计盈亏{cpl:.2f}% 胜率{wr:.1f}% 笔{tc} 回撤{mdd:.2f}%")

    # 卖出原因
    sell_stats = result.get('sell_reason_stats', {})
    if sell_stats:
        total_sells = sum(sell_stats.values())
        print(f"\n  卖出原因(共{total_sells}笔):")
        for reason, count in sorted(sell_stats.items(), key=lambda x: -x[1]):
            if count > 0:
                pct = count / total_sells * 100 if total_sells > 0 else 0
                print(f"    {reason}: {count}({pct:.1f}%)")

asyncio.run(main())
