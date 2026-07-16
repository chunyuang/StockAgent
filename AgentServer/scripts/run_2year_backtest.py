"""2年全量回测 - 4策略组合"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

async def run_backtest():
    await mongo_manager.initialize()
    
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    task_id = f"backtest_2y_{int(time.time())}"
    logs = []
    
    async def push_log(tid, msg):
        logs.append(msg)
        if any(k in msg for k in ['✅', '❌', '⚠️', '📊', '🎯', '策略', '选股', '候选', '调仓', '回测结果', '收益', 'Alpha', '因子', '数据', '开始', '完成']):
            print(msg)
    
    inner_params = {
        "start_date": "20240506",
        "end_date": "20260511",
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
        # 风控参数放在params子对象里，引擎从req_params.get("params", {})读取
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
    
    print(f"\n🚀 2年全量回测 | {inner_params['start_date']}~{inner_params['end_date']} | ¥{inner_params['initial_cash']:,.0f}")
    print(f"   策略: {', '.join(s['name'] for s in inner_params['selected_strategies'])}\n")
    
    t0 = time.time()
    result = await execute_ultra_short_backtest(
        params=params,
        push_log_fn=push_log,
        node_logger=None,
        task_id=task_id,
    )
    elapsed = time.time() - t0
    
    if result.get("error"):
        print(f"\n❌ 回测失败: {result['error']}")
        # 保存日志
        with open(os.path.join(BASE, 'backtest_error.log'), 'w') as f:
            f.write('\n'.join(logs))
        return
    
    metrics = result.get('metrics', {})
    returns = metrics.get('returns', {})
    risk = metrics.get('risk', {})
    trades = metrics.get('trades', {})
    strategy_results = result.get('strategy_results', {})
    
    tr = returns.get('total_return_pct', 0)
    br = returns.get('benchmark_return_pct', 0)
    alpha = returns.get('alpha_pct', 0)
    
    print(f"\n{'='*65}")
    print(f"📊 2年回测结果 ({elapsed:.1f}s)")
    print(f"{'='*65}")
    print(f"  策略收益率:  {tr:+.2f}%")
    print(f"  基准收益率:  {br:+.2f}%")
    print(f"  Alpha:       {alpha:+.2f}%")
    print(f"  胜率:        {risk.get('win_rate_pct', 0):.1f}%")
    print(f"  盈亏比:      {risk.get('profit_loss_ratio', 0):.2f}")
    print(f"  最大回撤:    {risk.get('max_drawdown_pct', 0):.2f}%")
    print(f"  夏普:        {risk.get('sharpe_ratio', 0):.2f}")
    print(f"  索提诺:      {risk.get('sortino_ratio', 0):.2f}")
    print(f"  卡玛:        {risk.get('calmar_ratio', 0):.2f}")
    print(f"  交易:        {trades.get('total_trades', 0)} (赢{trades.get('winning_trades',0)}/亏{trades.get('losing_trades',0)})")
    
    # 按策略看
    if strategy_results:
        print("\n  策略明细:")
        for sid, sdata in strategy_results.items():
            s_metrics = sdata.get('metrics', {})
            s_returns = s_metrics.get('returns', {})
            s_trades = s_metrics.get('trades', {})
            s_name = sdata.get('strategy_name', sid)
            print(f"    {s_name}: {s_returns.get('total_return_pct',0):+.2f}% | {s_trades.get('total_trades',0)}笔 | 胜率{s_metrics.get('risk',{}).get('win_rate_pct',0):.0f}%")
    
    out = os.path.join(BASE, 'backtest_result_2y.json')
    with open(out, 'w') as f:
        json.dump(result, f, default=str, indent=2, ensure_ascii=False)
    print(f"\n📁 {out}")

if __name__ == "__main__":
    asyncio.run(run_backtest())
