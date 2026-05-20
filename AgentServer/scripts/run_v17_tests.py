"""V17参数测试 - 超时阈值>= + close_rise_pct变化"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

async def run_test(label, params, mongo_mgr):
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    task_id = f"v17t_{int(time.time()*1000)}"
    logs = []
    async def push_log(tid, msg):
        logs.append(msg)
    
    t0 = time.time()
    result = await execute_ultra_short_backtest(
        params=params, push_log_fn=push_log, node_logger=None, task_id=task_id,
    )
    elapsed = time.time() - t0
    
    m = result.get('metrics', {})
    r = m.get('returns', {})
    k = m.get('risk', {})
    t = m.get('trades', {})
    p = m.get('performance', {})
    
    ret = r.get('total_return_pct', 0)
    wr = k.get('win_rate_pct', 0)
    dd = k.get('max_drawdown_pct', 0)
    sharpe = k.get('sharpe_ratio', 0)
    plr = k.get('profit_loss_ratio', 0)
    trades = t.get('total_trades', 0)
    srs = result.get('sell_reason_stats', {})
    
    print(f"  {label:30s} | {ret:+7.2f}% | {wr:5.1f}% | {dd:5.2f}% | {sharpe:5.2f} | {plr:4.2f} | {trades:3d} | {srs} | {elapsed:.0f}s")
    return result

async def main():
    await mongo_manager.initialize()
    
    # 基线: 2策略, SL5%/TP10%/3天
    base_params = {
        "params": {
            "start_date": "20260105",
            "end_date": "20260320",
            "initial_cash": 1000000,
            "period": "daily",
            "strategies": ["halfway_chase", "limit_down_qiao"],
            "params": {
                "stop_loss_pct": 0.05,
                "take_profit_pct": 0.10,
                "max_hold_days": 3,
                "max_position_per_stock": 0.2,
                "liquidity_threshold": 500,
                "commission_rate": 0.0003,
                "stamp_duty_rate": 0.001,
                "slippage_pct": 0.002,
            },
            "enable_force_empty": True,
            "enable_sentiment_cycle": True,
            "enable_auction_filter": True,
            "enable_stop_loss": True,
            "enable_take_profit": True,
            "enable_ma60_filter": True,
            "enable_sector_concentration": True,
            "selected_strategies": [
                {"id": "halfway_chase", "name": "半路追涨", "params": {}, "riskParams": {}},
                {"id": "limit_down_qiao", "name": "跌停翘板", "params": {}, "riskParams": {}},
            ],
        }
    }
    
    print(f"\n📊 V17参数测试 | 2策略(半路追涨+跌停翘板) | 20260105-20260320")
    print(f"{'='*130}")
    print(f"  {'测试项':30s} | {'收益':>7s} | {'胜率':>5s} | {'回撤':>5s} | {'夏普':>5s} | {'盈亏':>4s} | {'笔数':>3s} | {'卖出原因':50s} | {'耗时':>4s}")
    print(f"{'-'*130}")
    
    # 基线
    await run_test("基线(V16: close5%/>3天)", base_params, mongo_manager)
    
    # 测试1: 半路追涨close_rise_pct 5%→3%
    params_3pct = json.loads(json.dumps(base_params))
    for s in params_3pct["params"]["selected_strategies"]:
        if s["id"] == "halfway_chase":
            s["params"]["min_close_rise_pct"] = 0.03
    await run_test("半路追涨收盘确认3%", params_3pct, mongo_manager)
    
    # 测试2: 半路追涨close_rise_pct 5%→4%
    params_4pct = json.loads(json.dumps(base_params))
    for s in params_4pct["params"]["selected_strategies"]:
        if s["id"] == "halfway_chase":
            s["params"]["min_close_rise_pct"] = 0.04
    await run_test("半路追涨收盘确认4%", params_4pct, mongo_manager)
    
    # 测试3: 跌停翘板买入价系数 1.01→1.02
    # (需要修改代码，通过参数无法控制，先跳过)
    
    # 测试4: 超时阈值 >= 替代 >
    # (需要修改代码，先跳过)
    
    # 测试5: 半路追涨max_open_rise_pct 3%→5%
    params_open5 = json.loads(json.dumps(base_params))
    for s in params_open5["params"]["selected_strategies"]:
        if s["id"] == "halfway_chase":
            s["params"]["max_open_rise_pct"] = 0.05
    await run_test("半路追涨开盘涨幅上限5%", params_open5, mongo_manager)
    
    # 测试6: 半路追涨SL5%/TP10% → SL3%/TP7%(全局默认)
    params_sl3 = json.loads(json.dumps(base_params))
    params_sl3["params"]["params"]["stop_loss_pct"] = 0.03
    params_sl3["params"]["params"]["take_profit_pct"] = 0.07
    await run_test("全局SL3%/TP7%", params_sl3, mongo_manager)
    
    # 测试7: 4策略组合(增加龙头低吸+首板打板)
    params_4strat = json.loads(json.dumps(base_params))
    params_4strat["params"]["strategies"] = ["halfway_chase", "limit_down_qiao", "dragon_head", "first_limit_up"]
    params_4strat["params"]["selected_strategies"] = [
        {"id": "halfway_chase", "name": "半路追涨", "params": {}, "riskParams": {}},
        {"id": "limit_down_qiao", "name": "跌停翘板", "params": {}, "riskParams": {}},
        {"id": "dragon_head", "name": "龙头低吸", "params": {}, "riskParams": {}},
        {"id": "first_limit_up", "name": "首板打板", "params": {}, "riskParams": {}},
    ]
    await run_test("4策略组合", params_4strat, mongo_manager)
    
    # 测试8: 半路追涨收盘确认3% + 开盘涨幅上限5%
    params_3pct_open5 = json.loads(json.dumps(base_params))
    for s in params_3pct_open5["params"]["selected_strategies"]:
        if s["id"] == "halfway_chase":
            s["params"]["min_close_rise_pct"] = 0.03
            s["params"]["max_open_rise_pct"] = 0.05
    await run_test("收盘3%+开盘上限5%", params_3pct_open5, mongo_manager)

if __name__ == "__main__":
    asyncio.run(main())
