"""V17基线回测 - 2策略(半路追涨+跌停翘板) 20260105-20260320"""
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
    
    task_id = f"v17baseline_{int(time.time())}"
    logs = []
    
    async def push_log(tid, msg):
        logs.append(msg)
    
    # V16基线参数: 2策略(半路追涨+跌停翘板), SL5%/TP10%/3天
    params = {
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
    
    print("🚀 V17基线回测 | 2策略(半路追涨+跌停翘板) | 20260105-20260320 | SL5%/TP10%/3天")
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
    alpha = r.get('alpha_pct', 0)
    wr = k.get('win_rate_pct', 0)
    dd = k.get('max_drawdown_pct', 0)
    sharpe = k.get('sharpe_ratio', 0)
    plr = k.get('profit_loss_ratio', 0)
    trades = t.get('total_trades', 0)
    calmar = k.get('calmar_ratio', 0)
    sortino = k.get('sortino_ratio', 0)
    vol = k.get('volatility_pct', 0)
    
    # 卖出原因统计
    srs = result.get('sell_reason_stats', {})
    
    print(f"\n{'='*70}")
    print(f"📊 V17基线回测结果 ({elapsed:.1f}s)")
    print(f"{'='*70}")
    print(f"  累计收益率: {ret:+.2f}%")
    print(f"  Alpha:      {alpha:+.2f}%")
    print(f"  胜率:       {wr:.1f}%")
    print(f"  最大回撤:   {dd:.2f}%")
    print(f"  夏普比率:   {sharpe:.2f}")
    print(f"  盈亏比:     {plr:.2f}")
    print(f"  卡玛比率:   {calmar:.2f}")
    print(f"  索提诺:     {sortino:.2f}")
    print(f"  年化波动:   {vol:.2f}%")
    print(f"  交易数:     {trades} (赢{t.get('winning_trades',0)}/亏{t.get('losing_trades',0)})")
    print(f"  信号数:     {p.get('total_signals', 0)}")
    print(f"  卖出原因:   {srs}")
    
    # 策略级结果
    sr = result.get('strategy_results', {})
    for sname, sdata in sr.items():
        print(f"\n  策略[{sname}]: 胜率{sdata.get('win_rate',0):.0f}% 收益{sdata.get('total_return',0):+.1f}% 交易{sdata.get('trades_count',0)}笔 盈亏比{sdata.get('profit_loss_ratio',0):.2f}")
    
    out = os.path.join(BASE, 'backtest_v17_baseline.json')
    with open(out, 'w') as f:
        json.dump(result, f, default=str, indent=2, ensure_ascii=False)
    print(f"\n📁 {out}")
    
    await mongo_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
