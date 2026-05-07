"""快速调参 - 2026年1-3月区间，少量关键参数"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

COMBOS = [
    # 量比/涨幅下/涨幅上/止损/止盈/最大持仓天
    (1.0, 0.02, 0.05, 0.02, 0.07, 3),
    (1.0, 0.01, 0.04, 0.02, 0.07, 3),
    (1.5, 0.02, 0.05, 0.02, 0.07, 3),
    (1.5, 0.02, 0.05, 0.02, 0.07, 5),
    (1.5, 0.01, 0.04, 0.02, 0.07, 3),
    (2.0, 0.02, 0.05, 0.02, 0.07, 3),
    (2.0, 0.02, 0.05, 0.02, 0.07, 5),
    (2.0, 0.01, 0.04, 0.02, 0.07, 3),
    # 止损放宽
    (1.5, 0.02, 0.05, 0.03, 0.07, 3),
    (1.5, 0.02, 0.05, 0.05, 0.07, 5),
    (1.0, 0.02, 0.05, 0.03, 0.07, 3),
    (1.0, 0.02, 0.05, 0.05, 0.10, 5),
    # 宽止损+大止盈
    (1.0, 0.02, 0.05, 0.05, 0.15, 5),
    (1.5, 0.02, 0.05, 0.05, 0.15, 5),
    # 极宽松
    (0.8, 0.01, 0.07, 0.05, 0.15, 5),
    (0.8, 0.02, 0.05, 0.05, 0.15, 5),
]

def build_params(vr, min_r, max_r, sl, tp, mhd):
    return {
        "params": {
            "strategies": ["halfway_chase"],
            "start_date": "20260105",
            "end_date": "20260320",
            "initial_cash": 1000000,
            "period": "daily",
            "params": {
                "stop_loss_pct": sl,
                "take_profit_pct": tp,
                "max_hold_days": mhd,
                "max_position_per_stock": 0.15,
                "liquidity_threshold": 500,
                "max_position": 0.7,
                "commission_rate": 0.0002,
                "stamp_duty_rate": 0.001,
                "slippage_pct": 0.001,
            },
            "selected_strategies": [
                {"id": "halfway_chase", "name": "半路追涨", "params": {
                    "min_volume_ratio": vr,
                    "min_rise_pct": min_r,
                    "max_rise_pct": max_r,
                }},
            ],
            "enable_force_empty": False,
            "enable_sentiment_cycle": True,
            "enable_auction_filter": False,
            "enable_stop_loss": True,
            "enable_take_profit": True,
            "enable_ma60_filter": True,
            "enable_sector_concentration": True,
        }
    }

async def main():
    await mongo_manager.initialize()
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    print(f"📊 快速调参: {len(COMBOS)}组合, 20260105~20260320")
    print("="*90)
    print(f"{'#':>3} {'VR':>4} {'Rise':>8} {'SL':>4} {'TP':>4} {'MHD':>4} | {'Ret':>8} {'α':>8} {'WR':>5} {'DD':>7} {'Trades':>7} {'Sharpe':>7}")
    print("-"*90)
    
    results = []
    for i, (vr, min_r, max_r, sl, tp, mhd) in enumerate(COMBOS):
        p = build_params(vr, min_r, max_r, sl, tp, mhd)
        task_id = f"qk_{i}_{int(time.time())}"
        logs = []
        
        async def push_log(tid, msg):
            logs.append(msg)
        
        t0 = time.time()
        try:
            result = await execute_ultra_short_backtest(
                params=p, push_log_fn=push_log, node_logger=None, task_id=task_id,
            )
        except Exception as e:
            print(f"{i+1:3d} {vr:4.1f} {min_r*100:.0f}~{max_r*100:.0f}% {sl*100:.0f}% {tp*100:.0f}% {mhd:4d} | ERROR: {e}")
            continue
        
        m = result.get('metrics', {})
        r = m.get('returns', {})
        k = m.get('risk', {})
        t = m.get('trades', {})
        
        ret = r.get('total_return_pct', 0)
        alpha = r.get('alpha_pct', 0)
        wr = k.get('win_rate_pct', 0)
        dd = k.get('max_drawdown_pct', 0)
        trades = t.get('total_trades', 0)
        sharpe = k.get('sharpe_ratio', 0)
        
        results.append({
            "vr": vr, "min_r": min_r, "max_r": max_r, "sl": sl, "tp": tp, "mhd": mhd,
            "ret": ret, "alpha": alpha, "wr": wr, "dd": dd, "trades": trades, "sharpe": sharpe,
        })
        
        print(f"{i+1:3d} {vr:4.1f} {min_r*100:.0f}~{max_r*100:.0f}% {sl*100:.0f}% {tp*100:.0f}% {mhd:4d} | {ret:+7.2f}% {alpha:+7.2f}% {wr:4.0f}% {dd:6.1f}% {trades:7d} {sharpe:7.2f} ({time.time()-t0:.0f}s)")
    
    # 排序
    results.sort(key=lambda x: x.get("alpha", -999), reverse=True)
    print("\n" + "="*90)
    print("TOP 5 by Alpha:")
    for r in results[:5]:
        print(f"  VR={r['vr']:.1f} Rise={r['min_r']*100:.0f}~{r['max_r']*100:.0f}% SL={r['sl']*100:.0f}% TP={r['tp']*100:.0f}% MHD={r['mhd']} → α={r['alpha']:+.2f}% Ret={r['ret']:+.2f}% WR={r['wr']:.0f}% DD={r['dd']:.1f}% T={r['trades']} Sharpe={r['sharpe']:.2f}")
    
    out = os.path.join(BASE, 'backtest_quick_results.json')
    with open(out, 'w') as f:
        json.dump(results, f, default=str, indent=2, ensure_ascii=False)
    print(f"\n📁 {out}")

if __name__ == "__main__":
    asyncio.run(main())
