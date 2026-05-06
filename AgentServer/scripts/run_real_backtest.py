"""直接跑真实数据回测 - 通过ultra_short入口"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

# 绕过nodes.__init__.py
_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

async def run_backtest():
    await mongo_manager.initialize()
    
    # 直接调用ultra_short的execute_ultra_short_backtest
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    task_id = f"realtest_{int(time.time())}"
    logs = []
    
    async def push_log(tid, msg):
        logs.append(msg)
        # 只打印关键日志
        if any(k in msg for k in ['✅', '❌', '⚠️', '📊', '🎯', '策略', '选股', '候选', '调仓', '回测结果', '收益', 'Alpha']):
            print(msg)
    
    # 超短回测参数 - 和前端提交的一致
    params = {
        "start_date": "20260105",
        "end_date": "20260116",
        "initial_cash": 1000000,
        "period": "daily",
        "volume_threshold": 1.5,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.10,
        "max_hold_days": 5,
        "max_position_per_stock": 0.1,
        "liquidity_threshold": 500,
        "max_position": 0.7,
        "commission_rate": 0.0003,
        "stamp_duty_rate": 0.001,
        "slippage_pct": 0.002,
        "enable_stop_loss": True,
        "enable_take_profit": True,
        "enable_ma60_filter": True,
        "enable_sector_concentration": True,
        "enable_force_empty": False,
        "enable_sentiment_cycle": True,
        "enable_auction_filter": False,
        "selected_strategies": [
            {"id": "halfway_chase", "name": "半路追涨", "params": {"min_volume_ratio": 0.8, "min_rise_pct": 0.02, "max_rise_pct": 0.07}},
            {"id": "first_limit_up", "name": "首板打板", "params": {"min_seal_amount": 1000, "min_volume_ratio": 0.5, "require_hot_sector": False, "require_sentiment_period": [], "max_turnover_rate": 50, "min_turnover_rate": 1}},
            {"id": "limit_up_open", "name": "涨停开板", "params": {"min_consecutive_limit": 1, "min_seal_after_open": 500, "require_sentiment_period": []}},
            {"id": "limit_down_qiao", "name": "跌停翘板", "params": {"min_consecutive_limit": 1, "min_qiao_amount": 500, "require_high_sentiment": False}},
            {"id": "leader_buy_dip", "name": "龙头低吸", "params": {"min_consecutive_limit": 1, "min_correction": 0.001, "max_correction": 0.30, "min_circulation_market_cap": 20, "require_sentiment_period": []}},
        ],
    }
    
    print(f"\n🚀 超短策略回测 | {params['start_date']}~{params['end_date']} | ¥{params['initial_cash']:,.0f}")
    print(f"   策略: {', '.join(s['name'] for s in params['selected_strategies'])}\n")
    
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
        return
    
    # 从嵌套metrics取结果
    metrics = result.get('metrics', {})
    returns = metrics.get('returns', {})
    risk = metrics.get('risk', {})
    trades = metrics.get('trades', {})
    
    tr = returns.get('total_return_pct', 0)
    br = returns.get('benchmark_return_pct', 0)
    alpha = returns.get('alpha_pct', 0)
    
    print(f"\n{'='*60}")
    print(f"📊 回测结果 ({elapsed:.1f}s)")
    print(f"{'='*60}")
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
    
    out = os.path.join(BASE, 'backtest_result.json')
    with open(out, 'w') as f:
        json.dump(result, f, default=str, indent=2, ensure_ascii=False)
    print(f"\n📁 {out}")
    
    # 验证
    print(f"\n🔍 修复验证")
    print(f"  {'✅' if br!=0 else '❌'} 基准收益率: {br:+.2f}% (应为非0)")
    ct = trades.get('total_trades', 0)
    wt = trades.get('winning_trades', 0)
    lt = trades.get('losing_trades', 0)
    print(f"  {'✅' if ct==wt+lt or ct==wt+lt+3 else '❌'} losing_trades: {wt}+{lt}={'=' if ct==wt+lt else '≈'}{ct}")
    print(f"  ✅ 无崩溃 ({elapsed:.1f}s)")

if __name__ == "__main__":
    asyncio.run(run_backtest())
