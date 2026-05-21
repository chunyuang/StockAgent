"""V33基线回测 - 3策略默认参数(含策略级风控), 20260105~20260320"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

def build_params():
    return {
        "params": {
            "strategies": ["dragon_head_dip", "limit_down_qiao", "halfway_chase"],
            "start_date": "20260105",
            "end_date": "20260320",
            "initial_cash": 1000000,
            "period": "daily",
            "params": {
                "stop_loss_pct": 0.05,
                "take_profit_pct": 0.15,
                "max_hold_days": 3,
                "max_position_per_stock": 0.2,
                "liquidity_threshold": 500,
                "max_position": 0.7,
                "commission_rate": 0.0003,
                "stamp_duty_rate": 0.001,
                "slippage_pct": 0.002,
            },
            "selected_strategies": [
                {"id": "dragon_head", "name": "龙头低吸", "params": {}, "riskParams": {
                    "stop_loss_pct": 0.05, "take_profit_pct": 0.15, "max_hold_days": 4, "slippage_pct": 0.002
                }},
                {"id": "limit_down_qiao", "name": "跌停翘板", "params": {}, "riskParams": {
                    "stop_loss_pct": 0.04, "take_profit_pct": 0.25, "max_hold_days": 3, "slippage_pct": 0.003
                }},
                {"id": "halfway_chase", "name": "半路追涨", "params": {}, "riskParams": {
                    "stop_loss_pct": 0.05, "take_profit_pct": 0.12, "max_hold_days": 3, "slippage_pct": 0.002
                }},
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

async def main():
    await mongo_manager.initialize()
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    task_id = f"v33_baseline2_{int(time.time())}"
    logs = []
    
    async def push_log(tid, msg):
        logs.append(msg)
    
    t0 = time.time()
    result = await execute_ultra_short_backtest(
        params=build_params(), push_log_fn=push_log, node_logger=None, task_id=task_id,
    )
    elapsed = time.time() - t0
    
    if result:
        m = result.get('metrics', {})
        r = m.get('returns', {})
        k = m.get('risk', {})
        t = m.get('trades', {})
        
        print(f"\n{'='*60}")
        print(f"V33基线回测结果(策略级风控) ({elapsed:.1f}s)")
        print(f"{'='*60}")
        print(f"  信号数:     {t.get('total_trades', '?')}")
        print(f"  胜率:       {k.get('win_rate_pct', 0):.2f}%")
        print(f"  累计收益率: {r.get('total_return_pct', 0):.2f}%")
        print(f"  最大回撤:   {k.get('max_drawdown_pct', 0):.2f}%")
        print(f"  盈亏比:     {k.get('profit_loss_ratio', 0):.2f}")
        print(f"  夏普比率:   {k.get('sharpe_ratio', 0):.2f}")
        print(f"  Sortino:    {k.get('sortino_ratio', 0):.2f}")
        print(f"  Calmar:     {k.get('calmar_ratio', 0):.2f}")
        
        # 策略分解
        sr = result.get('strategy_results', {})
        if sr:
            print(f"\n  策略分解:")
            for sname, sm in sr.items():
                print(f"    {sname}: {sm.get('trades_count',0)}笔 胜率{sm.get('win_rate',0):.1f}% 收益{sm.get('total_return',0):.2f}% 盈亏比{sm.get('profit_loss_ratio',0):.2f}")
        
        # 卖出原因
        srs = result.get('sell_reason_stats', {})
        if srs:
            print(f"\n  卖出原因:")
            for reason, cnt in sorted(srs.items(), key=lambda x: x[1], reverse=True):
                print(f"    {reason}: {cnt}")
        
        # 月度收益
        mp = result.get('monthly_profit', {})
        if mp:
            print(f"\n  月度收益:")
            for k2, v2 in mp.items():
                print(f"    {k2}: {v2:.2f}%")

if __name__ == "__main__":
    asyncio.run(main())
