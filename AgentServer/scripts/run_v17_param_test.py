"""V17参数测试 - 紧凑输出"""
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
    task_id = f"v17_{int(time.time()*1000)}"
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
    plr = k.get('profit_loss_ratio', 0)
    trades = t.get('total_trades', 0)
    
    print(f"  {label:32s} | {ret:+8.2f}% | {wr:5.1f}% | {dd:6.2f}% | {sharpe:6.2f} | {plr:5.2f} | {trades:4d} | SL={srs.get('stop_loss',0)} TP={srs.get('take_profit',0)} RB={srs.get('rebalance',0)} FE={srs.get('force_empty',0)} | {elapsed:.0f}s")
    return ret, sharpe, dd, wr

def make_params(close_pct=None, open_max_pct=None, sl=None, tp=None, strategies=None, strat_params=None):
    p = {
        "params": {
            "start_date": "20260105", "end_date": "20260320",
            "initial_cash": 1000000, "period": "daily",
            "strategies": strategies or ["halfway_chase", "limit_down_qiao"],
            "params": {
                "stop_loss_pct": sl or 0.05, "take_profit_pct": tp or 0.10,
                "max_hold_days": 3, "max_position_per_stock": 0.2,
                "liquidity_threshold": 500, "commission_rate": 0.0003,
                "stamp_duty_rate": 0.001, "slippage_pct": 0.002,
            },
            "enable_force_empty": True, "enable_sentiment_cycle": True,
            "enable_auction_filter": True, "enable_stop_loss": True,
            "enable_take_profit": True, "enable_ma60_filter": True,
            "enable_sector_concentration": True,
            "selected_strategies": strat_params or [
                {"id": "halfway_chase", "name": "半路追涨", "params": {}, "riskParams": {}},
                {"id": "limit_down_qiao", "name": "跌停翘板", "params": {}, "riskParams": {}},
            ],
        }
    }
    # Apply close_pct to halfway_chase
    if close_pct is not None:
        for s in p["params"]["selected_strategies"]:
            if s["id"] == "halfway_chase":
                s["params"]["min_close_rise_pct"] = close_pct
    if open_max_pct is not None:
        for s in p["params"]["selected_strategies"]:
            if s["id"] == "halfway_chase":
                s["params"]["max_open_rise_pct"] = open_max_pct
    return p

async def main():
    await mongo_manager.initialize()
    
    print(f"\n📊 V17参数测试 | 2策略 | 20260105-20260320")
    print(f"{'='*130}")
    print(f"  {'测试项':32s} | {'收益':>8s} | {'胜率':>5s} | {'回撤':>6s} | {'夏普':>6s} | {'盈亏比':>5s} | {'笔数':>4s} | {'卖出原因':40s} | {'耗时':>4s}")
    print(f"{'-'*130}")
    
    # 1. 基线
    await run_test("基线V16(close5%/>3天SL5%TP10%)", make_params(), mongo_manager)
    
    # 2. close_rise_pct variations
    await run_test("半路追涨收盘确认3%", make_params(close_pct=0.03), mongo_manager)
    await run_test("半路追涨收盘确认4%", make_params(close_pct=0.04), mongo_manager)
    await run_test("半路追涨收盘确认6%", make_params(close_pct=0.06), mongo_manager)
    
    # 3. max_open_rise_pct
    await run_test("开盘涨幅上限5%", make_params(open_max_pct=0.05), mongo_manager)
    await run_test("收盘3%+开盘上限5%", make_params(close_pct=0.03, open_max_pct=0.05), mongo_manager)
    
    # 4. SL/TP variations
    await run_test("SL3%/TP7%(全局默认)", make_params(sl=0.03, tp=0.07), mongo_manager)
    await run_test("SL3%/TP10%", make_params(sl=0.03, tp=0.10), mongo_manager)
    await run_test("SL5%/TP7%", make_params(sl=0.05, tp=0.07), mongo_manager)
    await run_test("SL5%/TP15%", make_params(sl=0.05, tp=0.15), mongo_manager)
    
    # 5. max_hold_days
    await run_test("持仓2天", make_params(sl=0.05, tp=0.10), mongo_manager)  # base is 3 days
    p2 = make_params()
    p2["params"]["params"]["max_hold_days"] = 2
    await run_test("max_hold=2天", p2, mongo_manager)
    p5 = make_params()
    p5["params"]["params"]["max_hold_days"] = 5
    await run_test("max_hold=5天", p5, mongo_manager)
    
    # 6. 4策略
    await run_test("4策略组合", make_params(
        strategies=["halfway_chase", "limit_down_qiao", "dragon_head", "first_limit_up"],
        strat_params=[
            {"id": "halfway_chase", "name": "半路追涨", "params": {}, "riskParams": {}},
            {"id": "limit_down_qiao", "name": "跌停翘板", "params": {}, "riskParams": {}},
            {"id": "dragon_head", "name": "龙头低吸", "params": {}, "riskParams": {}},
            {"id": "first_limit_up", "name": "首板打板", "params": {}, "riskParams": {}},
        ]
    ), mongo_manager)
    
    print(f"\n{'='*130}")

if __name__ == "__main__":
    asyncio.run(main())
