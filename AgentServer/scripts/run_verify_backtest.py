"""跑半路追涨55日回测验证 - 数据补充后"""
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
    
    task_id = f"verify_{int(time.time())}"
    key_logs = []
    
    async def push_log(tid, msg):
        key_logs.append(msg)
        if any(k in msg for k in ['✅', '❌', '⚠️', '📊', '🎯', '候选', '调仓', '回测结果', '收益', 'Alpha', '半路追涨']):
            print(msg)
    
    # 半路追涨参数 - 优化后: 量比2.0/涨幅2-5%/2日持仓/SL-2%/TP7%
    # 注意: ultra_short读取params.params子对象
    params = {
        "params": {
            "start_date": "20260301",
            "end_date": "20260506",
            "initial_cash": 1000000,
            "period": "daily",
            "strategies": ["halfway_chase"],
            "params": {
                "volume_threshold": 2.0,
                "stop_loss_pct": 0.02,
                "take_profit_pct": 0.07,
                "max_hold_days": 2,
                "max_position_per_stock": 0.1,
                "liquidity_threshold": 500,
                "max_position": 0.7,
                "commission_rate": 0.0003,
                "stamp_duty_rate": 0.001,
                "slippage_pct": 0.002,
            },
            "enable_stop_loss": True,
            "enable_take_profit": True,
            "enable_ma60_filter": True,
            "enable_sector_concentration": True,
            "enable_force_empty": False,  # 关闭强制空仓!
            "enable_sentiment_cycle": True,
            "enable_auction_filter": False,
            "selected_strategies": [
                {"id": "halfway_chase", "name": "半路追涨", "params": {"min_volume_ratio": 2.0, "min_rise_pct": 0.02, "max_rise_pct": 0.05}},
            ],
        }
    }
    
    p = params['params']
    print(f"\n🚀 半路追涨回测 | {p['start_date']}~{p['end_date']} | 55个交易日")
    print(f"   量比≥2.0 | 涨幅2-5% | 2日持仓 | SL-2% | TP7%\n")
    
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
        with open(os.path.join(BASE, 'backtest_verify_error.json'), 'w') as f:
            json.dump(result, f, default=str, indent=2, ensure_ascii=False)
        return
    
    metrics = result.get('metrics', {})
    returns = metrics.get('returns', {})
    risk = metrics.get('risk', {})
    trades = metrics.get('trades', {})
    
    tr = returns.get('total_return_pct', 0)
    br = returns.get('benchmark_return_pct', 0)
    alpha = returns.get('alpha_pct', 0)
    
    print(f"\n{'='*60}")
    print(f"📊 半路追涨回测结果 ({elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  策略收益率:  {tr:+.2f}%")
    print(f"  基准收益率:  {br:+.2f}%")
    print(f"  Alpha:       {alpha:+.2f}%")
    print(f"  胜率:        {risk.get('win_rate_pct', 0):.1f}%")
    print(f"  盈亏比:      {risk.get('profit_loss_ratio', 0):.2f}")
    print(f"  最大回撤:    {risk.get('max_drawdown_pct', 0):.2f}%")
    print(f"  夏普:        {risk.get('sharpe_ratio', 0):.2f}")
    print(f"  交易:        {trades.get('total_trades', 0)} (赢{trades.get('winning_trades',0)}/亏{trades.get('losing_trades',0)})")
    
    # 验证
    print(f"\n🔍 数据补充后验证")
    print(f"  {'✅' if br!=0 else '❌'} 基准收益率: {br:+.2f}% (应为非0)")
    print(f"  {'✅' if tr > 50 else '⚠️'} 策略收益: {tr:+.2f}% (之前55日+79.7%)")
    
    out = os.path.join(BASE, 'backtest_verify_result.json')
    with open(out, 'w') as f:
        json.dump(result, f, default=str, indent=2, ensure_ascii=False)
    print(f"\n📁 {out}")

if __name__ == "__main__":
    asyncio.run(run_backtest())
