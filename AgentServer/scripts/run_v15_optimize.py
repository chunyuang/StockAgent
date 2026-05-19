"""V15参数优化测试"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager


async def run_test(label, params_mods, strategy_mods=None):
    """运行单次回测"""
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    base_params = {
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.10,
        "max_hold_days": 3,
        "max_position_per_stock": 0.2,
        "liquidity_threshold": 500,
        "commission_rate": 0.0003,
        "stamp_duty_rate": 0.001,
        "slippage_pct": 0.002,
    }
    base_params.update(params_mods)
    
    hw_params = {
        "min_rise_pct": 0.03, "max_rise_pct": 0.07,
        "min_volume_ratio": 2.0, "max_volume_ratio": 3.0,
        "min_close_rise_pct": 0.05, "max_open_rise_pct": 0.03,
    }
    ldq_params = {
        "min_consecutive_limit": 2,
        "min_qiao_amount": 1000,
        "min_rise_after_qiao": 0.03,
        "min_circulation_market_cap": 20,
        "require_high_sentiment": False,
    }
    hw_risk = {"stop_loss_pct": 0.05, "take_profit_pct": 0.10, "max_hold_days": 3, "slippage_pct": 0.002}
    ldq_risk = {"stop_loss_pct": 0.07, "take_profit_pct": 0.10, "max_hold_days": 3, "slippage_pct": 0.003}
    
    if strategy_mods:
        if 'halfway' in strategy_mods: hw_params.update(strategy_mods['halfway'])
        if 'ldq' in strategy_mods: ldq_params.update(strategy_mods['ldq'])
        if 'halfway_risk' in strategy_mods: hw_risk.update(strategy_mods['halfway_risk'])
        if 'ldq_risk' in strategy_mods: ldq_risk.update(strategy_mods['ldq_risk'])
    
    params = {
        "params": {
            "strategies": ["halfway_chase", "limit_down_qiao"],
            "start_date": "20260105",
            "end_date": "20260320",
            "initial_cash": 1000000,
            "period": "daily",
            "params": base_params,
            "selected_strategies": [
                {"id": "halfway_chase", "name": "半路追涨", "params": hw_params, "riskParams": hw_risk},
                {"id": "limit_down_qiao", "name": "跌停翘板", "params": ldq_params, "riskParams": ldq_risk},
            ],
            "enable_force_empty": True,
            "enable_sentiment_cycle": True,
            "enable_auction_filter": True,
            "enable_stop_loss": True,
            "enable_take_profit": True,
            "enable_ma60_filter": True,
            "enable_sector_concentration": True,
        }
    }
    
    async def push_noop(tid, msg):
        pass
    
    task_id = f"v15opt_{int(time.time())}"
    t0 = time.time()
    result = await execute_ultra_short_backtest(
        params=params, push_log_fn=push_noop, node_logger=None, task_id=task_id,
    )
    elapsed = time.time() - t0
    
    m = result.get('metrics', {})
    r = m.get('returns', {})
    k = m.get('risk', {})
    t = m.get('trades', {})
    
    return {
        "label": label,
        "ret": r.get('total_return_pct', 0),
        "dd": k.get('max_drawdown_pct', 0),
        "wr": k.get('win_rate_pct', 0),
        "sharpe": k.get('sharpe_ratio', 0),
        "plr": k.get('profit_loss_ratio', 0),
        "trades": t.get('total_trades', 0),
        "elapsed": elapsed,
    }


async def main():
    await mongo_manager.initialize()
    
    tests = [
        ("基线(V14参数)", {}, {}),
        # 强制空仓阈值优化
        ("空仓涨停限10→20", {}, {}),  # 需要修改GLOBAL_RISK
        # 买入价测试 - 需要修改代码后测
        # 收盘确认3%→5%对比
        ("收盘确认3%", {}, {"halfway": {"min_close_rise_pct": 0.03}}),
    ]
    
    print(f"{'测试':>20} | {'收益':>8} {'回撤':>7} {'胜率':>6} {'夏普':>6} {'盈亏比':>6} {'交易':>5} | {'耗时':>5}")
    print("-" * 90)
    
    for label, params_mods, strategy_mods in tests:
        r = await run_test(label, params_mods, strategy_mods)
        print(f"{r['label']:>20} | {r['ret']:+7.2f}% {r['dd']:5.2f}% {r['wr']:5.1f}% {r['sharpe']:5.2f} {r['plr']:5.2f} {r['trades']:5d} | {r['elapsed']:4.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
