"""V67基线Q1回测 - 使用与V66相同的参数配置(无修改)"""
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
    
    task_id = f"v67_q1_{int(time.time())}"
    logs = []
    
    async def push_log(tid, msg):
        logs.append(msg)
        if any(k in msg for k in ['📊', '🎯', '收益', 'Alpha', '胜率', '盈亏', '回撤', '夏普', '索提', '交易笔', '策略收益', '回测完成', '❌']):
            print(msg)
    
    # Use same params as 2year backtest (which produced V66 results)
    inner_params = {
        "start_date": "20250105",
        "end_date": "20250331",
        "initial_cash": 1000000,
        "period": "daily",
        "enable_stop_loss": True,
        "enable_take_profit": True,
        "enable_ma60_filter": True,
        "enable_sector_concentration": True,
        "enable_force_empty": False,
        "enable_sentiment_cycle": True,
        "enable_auction_filter": False,
        "strategies": ["halfway_chase", "first_limit_up", "leader_buy_dip", "limit_down_qiao"],
        "selected_strategies": [
            {"id": "halfway_chase", "name": "半路追涨", "params": {"min_volume_ratio": 1.0, "min_rise_pct": 0.02, "max_rise_pct": 0.05}, "riskParams": {"stop_loss_pct": 0.02}},
            {"id": "first_limit_up", "name": "首板打板", "params": {"min_volume_ratio": 0.8}, "riskParams": {"stop_loss_pct": 0.05}},
            {"id": "leader_buy_dip", "name": "龙头低吸", "params": {"min_consecutive_limit": 2, "max_callback_pct": 0.35, "min_callback_pct": 0.08}, "riskParams": {"stop_loss_pct": 0.05}},
            {"id": "limit_down_qiao", "name": "跌停翘板", "params": {"min_consecutive_limit": 2, "require_high_sentiment": False}, "riskParams": {"stop_loss_pct": 0.07}},
        ],
        "params": {
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.07,
            "max_hold_days": 10,
            "max_position_per_stock": 0.15,
            "liquidity_threshold": 500,
            "max_total_position": 0.7,
            "commission_rate": 0.0002,
            "stamp_duty_rate": 0.001,
            "slippage_pct": 0.001,
            "volume_threshold": 1.0,
        },
    }
    
    params = {"params": inner_params}
    
    print(f"🚀 V67基线Q1回测 | {inner_params['start_date']}~{inner_params['end_date']}")
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
    
    metrics = result.get('metrics', {})
    returns = metrics.get('returns', {})
    risk_m = metrics.get('risk', {})
    trades = metrics.get('trades', {})
    
    print(f"\n{'='*65}")
    print(f"📊 V67基线Q1结果 ({elapsed:.1f}s)")
    print(f"{'='*65}")
    print(f"  总收益:   {returns.get('total_return_pct', 0):.2f}%")
    print(f"  Alpha:    {returns.get('alpha_pct', 0):.2f}%")
    print(f"  最大回撤: {risk_m.get('max_drawdown_pct', 0):.2f}%")
    print(f"  夏普:     {risk_m.get('sharpe_ratio', 0):.2f}")
    print(f"  胜率:     {risk_m.get('win_rate_pct', 0):.1f}%")
    print(f"  盈亏比:   {risk_m.get('profit_loss_ratio', 0):.2f}")
    print(f"  交易笔数: {trades.get('total_trades', 0)}")
    
    # Strategy breakdown
    sr = result.get('strategy_results', {})
    for sname, sdata in sr.items():
        sm = sdata.get('metrics', {})
        s_returns = sm.get('returns', {})
        s_risk = sm.get('risk', {})
        s_trades = sm.get('trades', {})
        sname_display = sdata.get('strategy_name', sname)
        print(f"  [{sname_display}] 收益{s_returns.get('total_return_pct',0):.2f}% 胜率{s_risk.get('win_rate_pct',0):.1f}% 笔{s_trades.get('total_trades',0)}")
    
    # Save
    with open(os.path.join(BASE, 'V67_baseline_q1.json'), 'w') as f:
        json.dump({
            'total_return': returns.get('total_return_pct', 0),
            'alpha': returns.get('alpha_pct', 0),
            'max_drawdown': risk_m.get('max_drawdown_pct', 0),
            'sharpe': risk_m.get('sharpe_ratio', 0),
            'win_rate': risk_m.get('win_rate_pct', 0),
            'profit_loss_ratio': risk_m.get('profit_loss_ratio', 0),
            'total_trades': trades.get('total_trades', 0),
            'elapsed': elapsed,
        }, f, indent=2)

asyncio.run(main())
