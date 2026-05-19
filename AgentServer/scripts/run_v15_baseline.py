"""V15基线回测 - 2策略(半路追涨+跌停翘板)标准参数"""
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
    
    params = {
        "params": {
            "strategies": ["halfway_chase", "limit_down_qiao"],
            "start_date": "20260105",
            "end_date": "20260320",
            "initial_cash": 1000000,
            "period": "daily",
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
            "selected_strategies": [
                {"id": "halfway_chase", "name": "半路追涨", "params": {
                    "min_rise_pct": 0.03, "max_rise_pct": 0.07,
                    "min_volume_ratio": 2.0, "max_volume_ratio": 3.0,
                    "min_close_rise_pct": 0.05, "max_open_rise_pct": 0.03,
                }, "riskParams": {
                    "stop_loss_pct": 0.05, "take_profit_pct": 0.10,
                    "max_hold_days": 3, "slippage_pct": 0.002,
                }},
                {"id": "limit_down_qiao", "name": "跌停翘板", "params": {
                    "min_consecutive_limit": 2,
                    "min_qiao_amount": 1000,
                    "min_rise_after_qiao": 0.03,
                    "min_circulation_market_cap": 20,
                    "require_high_sentiment": False,
                }, "riskParams": {
                    "stop_loss_pct": 0.07, "take_profit_pct": 0.10,
                    "max_hold_days": 3, "slippage_pct": 0.003,
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
    
    task_id = f"v15_baseline_{int(time.time())}"
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
    
    print("\n" + "="*60)
    print("V15 基线回测结果 (2策略: 半路追涨+跌停翘板)")
    print("="*60)
    print(f"  累计收益率: {r.get('total_return_pct', 0):.2f}%")
    print(f"  年化收益率: {r.get('annual_return_pct', 0):.2f}%")
    print(f"  最大回撤:   {k.get('max_drawdown_pct', 0):.2f}%")
    print(f"  胜率:       {k.get('win_rate_pct', 0):.2f}%")
    print(f"  夏普比率:   {k.get('sharpe_ratio', 0):.2f}")
    print(f"  盈亏比:     {k.get('profit_loss_ratio', 0):.2f}")
    print(f"  总交易:     {t.get('total_trades', 0)}")
    print(f"  信号数:     {p.get('total_signals', 0)}")
    print(f"  耗时:       {elapsed:.1f}s")
    print(f"  执行耗时:   {result.get('execution_time_ms', 0)}ms")
    
    # 策略分解
    sr = result.get('strategy_results', {})
    for sname, sdata in sr.items():
        print(f"\n  [{sname}]:")
        print(f"    胜率: {sdata.get('win_rate', 0):.1f}%")
        print(f"    累计盈利: {sdata.get('total_return', 0):.2f}%")
        print(f"    交易数: {sdata.get('trades_count', 0)}")
        print(f"    盈亏比: {sdata.get('profit_loss_ratio', 0):.2f}")
        if sdata.get('warning'):
            print(f"    ⚠️ {sdata['warning']}")
    
    # 卖出原因
    srs = result.get('sell_reason_stats', {})
    total_sell = sum(srs.values()) if srs else 0
    if total_sell > 0:
        print(f"\n  卖出原因分布:")
        for reason, cnt in sorted(srs.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {cnt}笔 ({cnt/total_sell*100:.0f}%)")
    
    # 保存详细结果
    out = os.path.join(BASE, 'v15_baseline_result.json')
    with open(out, 'w') as f:
        # 只保存关键指标，不含大数组
        save = {
            "total_return_pct": r.get('total_return_pct', 0),
            "annual_return_pct": r.get('annual_return_pct', 0),
            "max_drawdown_pct": k.get('max_drawdown_pct', 0),
            "win_rate_pct": k.get('win_rate_pct', 0),
            "sharpe_ratio": k.get('sharpe_ratio', 0),
            "profit_loss_ratio": k.get('profit_loss_ratio', 0),
            "total_trades": t.get('total_trades', 0),
            "total_signals": p.get('total_signals', 0),
            "strategy_results": sr,
            "sell_reason_stats": srs,
            "execution_time_ms": result.get('execution_time_ms', 0),
            "elapsed_s": elapsed,
        }
        json.dump(save, f, indent=2, ensure_ascii=False)
    print(f"\n📁 保存到 {out}")

if __name__ == "__main__":
    asyncio.run(main())
