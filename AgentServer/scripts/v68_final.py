"""V68最终回测 - 仅保留正向优化(龙头低吸SL 3%+利润锁定回撤2.5%)"""
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
    
    task_id = f"v68_final_{int(time.time())}"
    logs = []
    
    async def push_log(tid, msg):
        logs.append(msg)
        if any(k in msg for k in ['📊', '🎯', '收益', 'Alpha', '胜率', '盈亏', '回撤', '夏普', '索提', '交易笔', '❌']):
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
    
    print(f"🚀 V68最终回测 | {inner_params['start_date']}~{inner_params['end_date']}")
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
    trades_m = metrics.get('trades', {})
    
    tr = returns.get('total_return_pct', 0)
    md = risk_m.get('max_drawdown_pct', 0)
    sr = risk_m.get('sharpe_ratio', 0)
    wr = risk_m.get('win_rate_pct', 0)
    plr = risk_m.get('profit_loss_ratio', 0)
    tt = trades_m.get('total_trades', 0)
    alpha = returns.get('alpha_pct', 0)
    sortino = risk_m.get('sortino_ratio', 0)
    calmar = risk_m.get('calmar_ratio', 0)
    
    print(f"\n{'='*65}")
    print(f"📊 V68最终结果 ({elapsed:.1f}s)")
    print(f"{'='*65}")
    print(f"  总收益:     {tr:.2f}%")
    print(f"  Alpha:      {alpha:.2f}%")
    print(f"  最大回撤:   {md:.2f}%")
    print(f"  夏普:       {sr:.2f}")
    print(f"  索提诺:     {sortino:.2f}")
    print(f"  卡玛:       {calmar:.2f}")
    print(f"  胜率:       {wr:.1f}%")
    print(f"  盈亏比:     {plr:.2f}")
    print(f"  交易笔数:   {tt}")
    
    strategy_results = result.get('strategy_results', {})
    for sname, sdata in strategy_results.items():
        s_wr = sdata.get('win_rate', 0)
        s_tr = sdata.get('total_return', 0)
        s_tc = sdata.get('trades_count', 0)
        s_dd = sdata.get('max_drawdown', 0)
        s_plr = sdata.get('profit_loss_ratio', 0)
        print(f"  [{sname}] 收益{s_tr:.2f}% 胜率{s_wr:.1f}% 笔{s_tc} 回撤{s_dd:.2f}% 盈亏比{s_plr:.2f}")
    
    srs = result.get('sell_reason_stats', {})
    if srs:
        print(f"\n  卖出原因统计:")
        for k, v in sorted(srs.items(), key=lambda x: -x[1]):
            if v > 0:
                print(f"    {k}: {v}")
    
    # V67 baseline comparison
    print(f"\n{'='*65}")
    print(f"📊 V67→V68 最终对比")
    print(f"{'='*65}")
    v67 = {'tr': 315.10, 'md': 3.45, 'sr': 14.10, 'wr': 82.9, 'plr': 3.05, 'tt': 117}
    v67_sr = {'跌停翘板': (317.80, 10.30, 3.42), '龙头低吸': (306.89, 3.65, 2.96), '半路追涨': (162.80, 3.67, 2.59), '首板打板': (66.97, 5.58, 2.28)}
    print(f"  收益:   {v67['tr']:.2f}% → {tr:.2f}% ({tr-v67['tr']:+.2f}%)")
    print(f"  回撤:   {v67['md']:.2f}% → {md:.2f}% ({md-v67['md']:+.2f}%)")
    print(f"  夏普:   {v67['sr']:.2f} → {sr:.2f} ({sr-v67['sr']:+.2f})")
    print(f"  胜率:   {v67['wr']:.1f}% → {wr:.1f}% ({wr-v67['wr']:+.1f}%)")
    print(f"  盈亏比: {v67['plr']:.2f} → {plr:.2f} ({plr-v67['plr']:+.2f})")
    print(f"  交易:   {v67['tt']} → {tt} ({tt-v67['tt']:+d})")
    
    for sname, (v67_tr, v67_dd, v67_plr) in v67_sr.items():
        sdata = strategy_results.get(sname, {})
        s_tr = sdata.get('total_return', 0)
        s_dd = sdata.get('max_drawdown', 0)
        s_plr = sdata.get('profit_loss_ratio', 0)
        print(f"  [{sname}] 收益{v67_tr:.2f}→{s_tr:.2f}({s_tr-v67_tr:+.2f}) 回撤{v67_dd:.2f}→{s_dd:.2f}({s_dd-v67_dd:+.2f})")
    
    with open(os.path.join(BASE, 'V68_final_result.json'), 'w') as f:
        json.dump(result, f, default=str, indent=2, ensure_ascii=False)
    print(f"\n📁 结果已保存")

asyncio.run(main())
