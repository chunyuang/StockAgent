"""V68优化回测 - 使用V68优化参数(4策略组合Q1)"""
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
    
    task_id = f"v68_opt_{int(time.time())}"
    logs = []
    
    async def push_log(tid, msg):
        logs.append(msg)
        if any(k in msg for k in ['📊', '🎯', '收益', 'Alpha', '胜率', '盈亏', '回撤', '夏普', '索提', '交易笔', '❌']):
            print(msg)
    
    # V68优化参数(4策略组合, Q1 2025) - 使用默认参数(从strategy_defaults读取)
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
    
    print(f"🚀 V68优化回测 | {inner_params['start_date']}~{inner_params['end_date']} | 4策略V68参数")
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
        with open(os.path.join(BASE, 'V68_opt_error.json'), 'w') as f:
            json.dump(result, f, default=str, indent=2, ensure_ascii=False)
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
    vol = risk_m.get('volatility_pct', 0)
    
    print(f"\n{'='*65}")
    print(f"📊 V68优化结果 ({elapsed:.1f}s)")
    print(f"{'='*65}")
    print(f"  总收益:     {tr:.2f}%")
    print(f"  Alpha:      {alpha:.2f}%")
    print(f"  最大回撤:   {md:.2f}%")
    print(f"  夏普:       {sr:.2f}")
    print(f"  索提诺:     {sortino:.2f}")
    print(f"  卡玛:       {calmar:.2f}")
    print(f"  波动率:     {vol:.2f}%")
    print(f"  胜率:       {wr:.1f}%")
    print(f"  盈亏比:     {plr:.2f}")
    print(f"  交易笔数:   {tt}")
    
    # Strategy breakdown
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
        print("\n  卖出原因统计:")
        for k, v in sorted(srs.items(), key=lambda x: -x[1]):
            if v > 0:
                print(f"    {k}: {v}")
    
    # V67 baseline comparison
    print(f"\n{'='*65}")
    print("📊 V67→V68 对比")
    print(f"{'='*65}")
    v67 = {'tr': 315.10, 'md': 3.45, 'sr': 14.10, 'wr': 82.9, 'plr': 3.05, 'tt': 117}
    print(f"  收益:   {v67['tr']:.2f}% → {tr:.2f}% ({tr-v67['tr']:+.2f}%)")
    print(f"  回撤:   {v67['md']:.2f}% → {md:.2f}% ({md-v67['md']:+.2f}%)")
    print(f"  夏普:   {v67['sr']:.2f} → {sr:.2f} ({sr-v67['sr']:+.2f})")
    print(f"  胜率:   {v67['wr']:.1f}% → {wr:.1f}% ({wr-v67['wr']:+.1f}%)")
    print(f"  盈亏比: {v67['plr']:.2f} → {plr:.2f} ({plr-v67['plr']:+.2f})")
    print(f"  交易:   {v67['tt']} → {tt} ({tt-v67['tt']:+d})")
    
    # Save
    with open(os.path.join(BASE, 'V68_opt_result.json'), 'w') as f:
        json.dump(result, f, default=str, indent=2, ensure_ascii=False)
    with open(os.path.join(BASE, 'V68_opt_summary.json'), 'w') as f:
        json.dump({
            'total_return_pct': tr, 'alpha_pct': alpha,
            'max_drawdown_pct': md, 'sharpe_ratio': sr,
            'sortino_ratio': sortino, 'calmar_ratio': calmar,
            'volatility_pct': vol, 'win_rate_pct': wr,
            'profit_loss_ratio': plr, 'total_trades': tt,
            'elapsed': elapsed, 'strategy_results': strategy_results,
            'sell_reason_stats': srs,
        }, f, indent=2)
    print("\n📁 结果已保存")

asyncio.run(main())
