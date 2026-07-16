"""V73 基线回测 - 审查前基准数据"""
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
    
    task_id = f"v73_baseline_{int(time.time())}"
    logs = []
    
    async def push_log(tid, msg):
        logs.append(msg)
        if any(k in msg for k in ['📊', '🎯', '收益', 'Alpha', '胜率', '盈亏', '回撤', '夏普', '索提', '交易笔', '❌', '卖出原因']):
            print(msg)
    
    inner_params = {
        "start_date": "20250105",
        "end_date": "20250331",
        "initial_cash": 1000000,
        "period": "daily",
        "enable_stop_loss": True,
        "enable_take_profit": True,
        "enable_ma60_filter": True,
        "enable_sector_concentration": True,
        "enable_force_empty": True,
        "enable_sentiment_cycle": True,
        "enable_auction_filter": True,
        "strategies": ["halfway_chase", "first_limit_up", "dragon_head", "limit_down_qiao"],
        "selected_strategies": [
            {"id": "halfway_chase", "name": "半路追涨"},
            {"id": "first_limit_up", "name": "首板打板"},
            {"id": "dragon_head", "name": "龙头低吸"},
            {"id": "limit_down_qiao", "name": "跌停翘板"},
        ],
        "params": {
            "stop_loss_pct": 0.03,
            "take_profit_pct": 0.07,
            "max_hold_days": 10,
            "max_position_per_stock": 0.35,
            "max_total_position": 0.75,
            "commission_rate": 0.0003,
            "stamp_duty_rate": 0.001,
            "slippage_pct": 0.002,
        },
    }
    
    params = {"params": inner_params}
    
    print(f"🚀 V73 基线回测 | {inner_params['start_date']}~{inner_params['end_date']}")
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
    
    # Extract results
    perf_list = result.get('performance', [])
    perf = perf_list[0] if perf_list else {}
    
    tr = perf.get('total_return', 0)
    md = perf.get('max_drawdown', 0)
    sr = perf.get('sharpe_ratio', 0)
    wr = perf.get('win_rate', 0)
    plr = perf.get('profit_loss_ratio', 0)
    tt = perf.get('total_trades', 0)
    wt = perf.get('winning_trades', 0)
    lt = perf.get('losing_trades', 0)
    alpha = perf.get('alpha', 0)
    sortino = perf.get('sortino_ratio', 0)
    calmar = perf.get('calmar_ratio', 0)
    avg_hold = perf.get('average_hold_days', 0)
    iv = perf.get('initial_cash', 1000000)
    fv = perf.get('final_value', 0)
    
    print(f"\n{'='*65}")
    print(f"📊 V73 基线结果 ({elapsed:.1f}s)")
    print(f"{'='*65}")
    print(f"  总收益:     {tr:.2f}%")
    print(f"  Alpha:      {alpha:.2f}%")
    print(f"  最大回撤:   {md:.2f}%")
    print(f"  夏普:       {sr:.2f}")
    print(f"  索提诺:     {sortino:.2f}")
    print(f"  卡玛:       {calmar:.2f}")
    print(f"  胜率:       {wr:.1f}%")
    print(f"  盈亏比:     {plr:.2f}")
    print(f"  交易笔数:   {tt} (胜{wt}/负{lt})")
    print(f"  平均持仓:   {avg_hold:.1f}天")
    print(f"  初始资金:   {iv:,.0f} → 期末: {fv:,.0f}")
    
    # Strategy results
    strategy_results = result.get('strategy_results', {})
    for sname, sdata in strategy_results.items():
        s_wr = sdata.get('win_rate', 0)
        s_tr = sdata.get('total_return', 0)
        s_tc = sdata.get('trades_count', 0)
        s_dd = sdata.get('max_drawdown', 0)
        s_plr = sdata.get('profit_loss_ratio', 0)
        print(f"  [{sname}] 收益{s_tr:.2f}% 胜率{s_wr:.1f}% 笔{s_tc} 回撤{s_dd:.2f}% 盈亏比{s_plr:.2f}")
    
    # Sell reason stats
    srs = result.get('sell_reason_stats', {})
    if srs:
        total_sells = sum(srs.values())
        print(f"\n  卖出原因统计 (共{total_sells}笔):")
        for k, v in sorted(srs.items(), key=lambda x: -x[1]):
            if v > 0:
                pct = v/total_sells*100 if total_sells > 0 else 0
                print(f"    {k}: {v} ({pct:.1f}%)")
    
    # Monthly profit
    mp = perf.get('monthly_profit', {})
    if mp:
        print("\n  月度盈亏:")
        for k, v in sorted(mp.items()):
            print(f"    {k}: {v:.2f}%")
    
    # Save result
    out_path = os.path.join(BASE, 'V73_baseline_result.json')
    with open(out_path, 'w') as f:
        json.dump(result, f, default=str, indent=2, ensure_ascii=False)
    print(f"\n📁 结果已保存到 {out_path}")

asyncio.run(main())
