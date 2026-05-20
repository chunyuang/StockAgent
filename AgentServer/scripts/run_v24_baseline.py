"""V24基线回测 - 2策略(半路追涨+跌停翘板), 与V23结果对比
配置: SL5%/TP12%(半路)+SL7%/TP20%(翘板), 20260105-20260506
"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

async def run():
    await mongo_manager.initialize()
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    task_id = f"v24_baseline_{int(time.time())}"
    key_logs = []
    
    async def push_log(tid, msg):
        key_logs.append(msg)
        # 只打印关键行
        if any(k in msg for k in ['✅', '❌', '📊', '🎯', '回测结果', '收益', 'Alpha', '夏普', '回撤', '胜率']):
            print(msg)
    
    params = {
        "params": {
            "start_date": "20260105",
            "end_date": "20260506",
            "initial_cash": 1000000,
            "period": "daily",
            "strategies": ["halfway_chase", "limit_down_qiao"],
            "params": {
                "stop_loss_pct": 0.05,
                "take_profit_pct": 0.10,
                "max_hold_days": 3,
                "max_position_per_stock": 0.2,
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
            "enable_force_empty": True,
            "enable_sentiment_cycle": True,
            "enable_auction_filter": False,
            "selected_strategies": [
                {"id": "halfway_chase", "name": "半路追涨", "params": {
                    "min_volume_ratio": 2.0, "min_rise_pct": 0.03, "max_rise_pct": 0.07,
                    "min_close_rise_pct": 0.05, "max_open_rise_pct": 0.03,
                }, "riskParams": {
                    "stop_loss_pct": 0.05, "take_profit_pct": 0.12, "max_hold_days": 3, "slippage_pct": 0.002,
                }},
                {"id": "limit_down_qiao", "name": "跌停翘板", "params": {
                    "min_consecutive_limit": 2, "min_qiao_amount": 1000,
                    "min_rise_after_qiao": 0.03, "min_circulation_market_cap": 20,
                }, "riskParams": {
                    "stop_loss_pct": 0.07, "take_profit_pct": 0.20, "max_hold_days": 3, "slippage_pct": 0.003,
                }},
            ],
        }
    }
    
    print(f"\n🚀 V24基线回测: 半路追涨+跌停翘板 | 20260105-20260506")
    print(f"   半路: SL5%/TP12%/3天 | 翘板: SL7%/TP20%/3天\n")
    
    t0 = time.time()
    result = await execute_ultra_short_backtest(
        params=params, push_log_fn=push_log, node_logger=None, task_id=task_id,
    )
    elapsed = time.time() - t0
    
    if result.get("error"):
        print(f"\n❌ 回测失败: {result['error']}")
        return None
    
    m = result.get('metrics', {})
    r = m.get('returns', {})
    k = m.get('risk', {})
    t = m.get('trades', {})
    
    ret = r.get('total_return_pct', 0)
    alpha = r.get('alpha_pct', 0)
    wr = k.get('win_rate_pct', 0)
    dd = k.get('max_drawdown_pct', 0)
    sharpe = k.get('sharpe_ratio', 0)
    plr = k.get('profit_loss_ratio', 0)
    trades = t.get('total_trades', 0)
    
    print(f"\n{'='*60}")
    print(f"📊 V24基线结果 ({elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  收益率:    {ret:+.2f}%")
    print(f"  Alpha:     {alpha:+.2f}%")
    print(f"  胜率:      {wr:.1f}%")
    print(f"  盈亏比:    {plr:.2f}")
    print(f"  最大回撤:  {dd:.2f}%")
    print(f"  夏普:      {sharpe:.2f}")
    print(f"  交易:      {trades}")
    print(f"  V23对比:   113.92%/11.38夏普/2.26%回撤/75.63%胜率/2.38盈亏比/119笔")
    
    # 保存完整结果
    out = os.path.join(BASE, 'backtest_v24_baseline.json')
    with open(out, 'w') as f:
        json.dump(result, f, default=str, indent=2, ensure_ascii=False)
    print(f"\n📁 {out}")
    
    return result

if __name__ == "__main__":
    asyncio.run(run())
