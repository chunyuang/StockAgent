"""V17 SL/TP穿透测试"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

async def run_test(label, params, mm):
    import logging
    logging.getLogger('ultrashort').setLevel(logging.ERROR)
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    task_id = f"v17sl_{int(time.time()*1000)}"
    async def push_log(tid, msg): pass
    
    t0 = time.time()
    result = await execute_ultra_short_backtest(
        params=params, push_log_fn=push_log, node_logger=None, task_id=task_id,
    )
    elapsed = time.time() - t0
    
    m = result.get('metrics', {})
    r = m.get('returns', {})
    k = m.get('risk', {})
    t = m.get('trades', {})
    srs = result.get('sell_reason_stats', {})
    
    ret = r.get('total_return_pct', 0)
    wr = k.get('win_rate_pct', 0)
    dd = k.get('max_drawdown_pct', 0)
    sharpe = k.get('sharpe_ratio', 0)
    trades = t.get('total_trades', 0)
    
    print(f"  {label:35s} | {ret:+8.2f}% | {wr:5.1f}% | {dd:6.2f}% | {sharpe:6.2f} | {trades:4d} | SL={srs.get('stop_loss',0)} TP={srs.get('take_profit',0)} | {elapsed:.0f}s")

def make_params(sl=0.05, tp=0.10, mhd=3, risk_params=None):
    """Make params with explicit riskParams override"""
    p = {
        "params": {
            "start_date": "20260105", "end_date": "20260320",
            "initial_cash": 1000000, "period": "daily",
            "strategies": ["halfway_chase", "limit_down_qiao"],
            "params": {
                "stop_loss_pct": sl, "take_profit_pct": tp,
                "max_hold_days": mhd, "max_position_per_stock": 0.2,
                "liquidity_threshold": 500, "commission_rate": 0.0003,
                "stamp_duty_rate": 0.001, "slippage_pct": 0.002,
            },
            "enable_force_empty": True, "enable_sentiment_cycle": True,
            "enable_auction_filter": True, "enable_stop_loss": True,
            "enable_take_profit": True, "enable_ma60_filter": True,
            "enable_sector_concentration": True,
            "selected_strategies": [
                {"id": "halfway_chase", "name": "半路追涨", "params": {}, "riskParams": risk_params or {}},
                {"id": "limit_down_qiao", "name": "跌停翘板", "params": {}, "riskParams": risk_params or {}},
            ],
        }
    }
    return p

async def main():
    await mongo_manager.initialize()
    
    print(f"\n📊 V17 SL/TP穿透测试 | 2策略 | 20260105-20260320")
    print(f"{'='*110}")
    print(f"  {'测试项':35s} | {'收益':>8s} | {'胜率':>5s} | {'回撤':>6s} | {'夏普':>6s} | {'笔数':>4s} | {'卖出':25s} | {'耗时':>4s}")
    print(f"{'-'*110}")
    
    # 1. 基线 (策略默认: halfway SL5% TP10%, limit_down SL7% TP10%)
    await run_test("基线(策略默认SL5%/TP10%)", make_params(), mongo_manager)
    
    # 2. 全局SL=2%(非GLOBAL_RISK默认0.03→应覆盖策略默认)
    await run_test("全局SL2%(非默认→应穿透)", make_params(sl=0.02, tp=0.10), mongo_manager)
    
    # 3. 全局SL=8%(非默认)
    await run_test("全局SL8%(非默认→应穿透)", make_params(sl=0.08, tp=0.10), mongo_manager)
    
    # 4. 全局TP=5%(非默认0.07)
    await run_test("全局TP5%(非默认→应穿透)", make_params(sl=0.05, tp=0.05), mongo_manager)
    
    # 5. 全局TP=20%(非默认)
    await run_test("全局TP20%(非默认→应穿透)", make_params(sl=0.05, tp=0.20), mongo_manager)
    
    # 6. max_hold=2(非默认3)
    await run_test("全局max_hold=2天(非默认)", make_params(sl=0.05, tp=0.10, mhd=2), mongo_manager)
    
    # 7. riskParams显式设置(最高优先级)
    await run_test("riskParams显式SL3%/TP7%", make_params(risk_params={"stop_loss_pct": 0.03, "take_profit_pct": 0.07}), mongo_manager)
    
    print(f"\n{'='*110}")

if __name__ == "__main__":
    asyncio.run(main())
