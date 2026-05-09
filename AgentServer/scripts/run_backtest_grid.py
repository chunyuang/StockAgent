"""批量调参回测 - 正确参数嵌套 + 网格搜索"""
import asyncio, sys, os, types, json, time, itertools

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

# ======== 参数网格 ========
GRID = {
    "start_date": ["20251008"],  # 114天满覆盖区间
    "end_date": ["20260320"],
    "initial_cash": [1000000],
    # 半路追涨核心参数
    "min_volume_ratio": [0.8, 1.0, 1.5, 2.0],
    "min_rise_pct": [0.01, 0.02, 0.03],
    "max_rise_pct": [0.04, 0.05, 0.07],
    # 全局风控
    "stop_loss_pct": [0.02, 0.03],
    "take_profit_pct": [0.05, 0.07],
    "max_hold_days": [3, 5],
}

# 生成组合（只变核心3个参数，风控用2组）
def gen_combos():
    combos = []
    for vr, min_r, max_r in itertools.product(
        GRID["min_volume_ratio"],
        GRID["min_rise_pct"],
        GRID["max_rise_pct"],
    ):
        if max_r <= min_r:
            continue
        for sl, tp, mhd in itertools.product(
            GRID["stop_loss_pct"],
            GRID["take_profit_pct"],
            GRID["max_hold_days"],
        ):
            combos.append({
                "min_volume_ratio": vr,
                "min_rise_pct": min_r,
                "max_rise_pct": max_r,
                "stop_loss_pct": sl,
                "take_profit_pct": tp,
                "max_hold_days": mhd,
            })
    return combos

def build_params(combo):
    """构建三层嵌套参数"""
    return {
        "params": {  # req_params层
            "strategies": ["halfway_chase"],
            "start_date": GRID["start_date"][0],
            "end_date": GRID["end_date"][0],
            "initial_cash": GRID["initial_cash"][0],
            "period": "daily",
            "params": {  # strategy_params层(全局风控)
                "stop_loss_pct": combo["stop_loss_pct"],
                "take_profit_pct": combo["take_profit_pct"],
                "max_hold_days": combo["max_hold_days"],
                "max_position_per_stock": 0.15,
                "liquidity_threshold": 500,
                "max_position": 0.7,
                "commission_rate": 0.0002,
                "stamp_duty_rate": 0.001,
                "slippage_pct": 0.001,
            },
            "selected_strategies": [
                {
                    "id": "halfway_chase",
                    "name": "半路追涨",
                    "params": {
                        "min_volume_ratio": combo["min_volume_ratio"],
                        "min_rise_pct": combo["min_rise_pct"],
                        "max_rise_pct": combo["max_rise_pct"],
                    },
                },
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

async def run_one(params, combo_id, total):
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    task_id = f"grid_{combo_id}_{int(time.time())}"
    logs = []
    
    async def push_log(tid, msg):
        logs.append(msg)
    
    t0 = time.time()
    try:
        result = await execute_ultra_short_backtest(
            params=params,
            push_log_fn=push_log,
            node_logger=None,
            task_id=task_id,
        )
    except Exception as e:
        return {"combo_id": combo_id, "error": str(e), "elapsed": time.time()-t0}
    
    elapsed = time.time() - t0
    m = result.get('metrics', {})
    r = m.get('returns', {})
    k = m.get('risk', {})
    t = m.get('trades', {})
    
    return {
        "combo_id": combo_id,
        "elapsed": elapsed,
        "return_pct": r.get('total_return_pct', 0),
        "benchmark_pct": r.get('benchmark_return_pct', 0),
        "alpha_pct": r.get('alpha_pct', 0),
        "win_rate": k.get('win_rate_pct', 0),
        "max_drawdown": k.get('max_drawdown_pct', 0),
        "sharpe": k.get('sharpe_ratio', 0),
        "total_trades": t.get('total_trades', 0),
        "winning": t.get('winning_trades', 0),
        "losing": t.get('losing_trades', 0),
    }

async def main():
    await mongo_manager.initialize()
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    combos = gen_combos()
    print(f"📊 网格搜索: {len(combos)} 组合")
    print(f"区间: {GRID['start_date'][0]}~{GRID['end_date'][0]}")
    print(f"参数: VR={GRID['min_volume_ratio']}, Rise=[{GRID['min_rise_pct']},{GRID['max_rise_pct']}]")
    print(f"风控: SL={GRID['stop_loss_pct']}, TP={GRID['take_profit_pct']}, MHD={GRID['max_hold_days']}")
    print("="*70)
    
    results = []
    for i, combo in enumerate(combos):
        p = build_params(combo)
        desc = f"VR={combo['min_volume_ratio']:.1f} Rise={combo['min_rise_pct']*100:.0f}~{combo['max_rise_pct']*100:.0f}% SL={combo['stop_loss_pct']*100:.0f}% TP={combo['take_profit_pct']*100:.0f}% MHD={combo['max_hold_days']}"
        print(f"[{i+1}/{len(combos)}] {desc} ...", end=" ", flush=True)
        
        r = await run_one(p, i, len(combos))
        r["params"] = combo
        r["desc"] = desc
        results.append(r)
        
        if r.get("error"):
            print(f"❌ {r['error'][:50]}")
        else:
            print(f"Ret={r['return_pct']:+.2f}% α={r['alpha_pct']:+.2f}% WR={r['win_rate']:.0f}% DD={r['max_drawdown']:.1f}% T={r['total_trades']} Sharpe={r['sharpe']:.2f} ({r['elapsed']:.0f}s)")
    
    # 排序输出
    print("\n" + "="*70)
    print("📊 按Alpha排序 TOP 10:")
    print("="*70)
    valid = [r for r in results if not r.get("error")]
    valid.sort(key=lambda x: x.get("alpha_pct", -999), reverse=True)
    for r in valid[:10]:
        print(f"  {r['desc']}")
        print(f"    → Ret={r['return_pct']:+.2f}% α={r['alpha_pct']:+.2f}% WR={r['win_rate']:.0f}% DD={r['max_drawdown']:.1f}% T={r['total_trades']} Sharpe={r['sharpe']:.2f}")
    
    # 保存完整结果
    out = os.path.join(BASE, 'backtest_grid_results.json')
    with open(out, 'w') as f:
        json.dump(results, f, default=str, indent=2, ensure_ascii=False)
    print(f"\n📁 完整结果: {out}")

if __name__ == "__main__":
    asyncio.run(main())
