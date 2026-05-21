"""V33 3个月验证回测 - 20251008~20260103"""
import asyncio, sys, os, types, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

def build_params(start, end):
    return {
        "params": {
            "strategies": ["dragon_head_dip", "limit_down_qiao", "halfway_chase"],
            "start_date": start,
            "end_date": end,
            "initial_cash": 1000000,
            "period": "daily",
            "params": {
                "stop_loss_pct": 0.05, "take_profit_pct": 0.15,
                "max_hold_days": 3, "max_position_per_stock": 0.2,
                "liquidity_threshold": 500, "max_position": 0.7,
                "commission_rate": 0.0003, "stamp_duty_rate": 0.001, "slippage_pct": 0.002,
            },
            "selected_strategies": [
                {"id": "dragon_head", "name": "龙头低吸", "params": {}, "riskParams": {"stop_loss_pct": 0.05, "take_profit_pct": 0.15, "max_hold_days": 4, "slippage_pct": 0.002}},
                {"id": "limit_down_qiao", "name": "跌停翘板", "params": {}, "riskParams": {"stop_loss_pct": 0.04, "take_profit_pct": 0.25, "max_hold_days": 3, "slippage_pct": 0.003}},
                {"id": "halfway_chase", "name": "半路追涨", "params": {}, "riskParams": {"stop_loss_pct": 0.05, "take_profit_pct": 0.12, "max_hold_days": 3, "slippage_pct": 0.002}},
            ],
            "enable_force_empty": True, "enable_sentiment_cycle": True,
            "enable_auction_filter": True, "enable_stop_loss": True,
            "enable_take_profit": True, "enable_ma60_filter": True,
            "enable_sector_concentration": True,
        }
    }

async def run_period(start, end, label):
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    task_id = f"v33_verify_{int(time.time())}"
    async def push_log(tid, msg): pass
    
    t0 = time.time()
    result = await execute_ultra_short_backtest(
        params=build_params(start, end), push_log_fn=push_log, node_logger=None, task_id=task_id)
    elapsed = time.time() - t0
    
    if result:
        m = result.get('metrics', {})
        r = m.get('returns', {})
        k = m.get('risk', {})
        t = m.get('trades', {})
        print(f"\n{'='*50}")
        print(f"V33验证: {label} ({elapsed:.1f}s)")
        print(f"{'='*50}")
        print(f"  信号数:     {t.get('total_trades', '?')}")
        print(f"  胜率:       {k.get('win_rate_pct', 0):.2f}%")
        print(f"  累计收益率: {r.get('total_return_pct', 0):.2f}%")
        print(f"  最大回撤:   {k.get('max_drawdown_pct', 0):.2f}%")
        print(f"  盈亏比:     {k.get('profit_loss_ratio', 0):.2f}")
        print(f"  夏普比率:   {k.get('sharpe_ratio', 0):.2f}")
        print(f"  Sortino:    {k.get('sortino_ratio', 0):.2f}")
        return r.get('total_return_pct', 0), k.get('sharpe_ratio', 0), k.get('max_drawdown_pct', 0)
    return 0, 0, 0

async def main():
    await mongo_manager.initialize()
    
    # 3个月验证
    r1, s1, d1 = await run_period("20251008", "20260103", "2025Q4")
    r2, s2, d2 = await run_period("20260105", "20260320", "2026Q1")
    
    print(f"\n{'='*50}")
    print(f"V33验证总结")
    print(f"{'='*50}")
    print(f"  2025Q4: 收益{r1:.2f}%/夏普{s1:.2f}/回撤{d1:.2f}%")
    print(f"  2026Q1: 收益{r2:.2f}%/夏普{s2:.2f}/回撤{d2:.2f}%")

if __name__ == "__main__":
    asyncio.run(main())
