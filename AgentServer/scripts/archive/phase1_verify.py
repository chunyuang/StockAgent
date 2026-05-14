#!/usr/bin/env python3
"""Phase1验证: 半路追涨 1/5-3/20 对比修复前后"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager


def build_halfway_only():
    return {
        "params": {
            "strategies": ["halfway_chase"],
            "start_date": "20260105",
            "end_date": "20260320",
            "initial_cash": 1000000,
            "period": "daily",
            "params": {
                "stop_loss_pct": 0.03,
                "take_profit_pct": 0.07,
                "max_hold_days": 3,
                "max_position_per_stock": 0.15,
                "liquidity_threshold": 500,
                "max_position": 0.7,
                "commission_rate": 0.0002,
                "stamp_duty_rate": 0.001,
                "slippage_pct": 0.001,
            },
            "selected_strategies": [
                {"id": "halfway_chase", "name": "半路追涨", "params": {
                    "min_volume_ratio": 2.0,
                    "min_rise_pct": 0.02,
                    "max_rise_pct": 0.07,
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


def build_all_strategies():
    return {
        "params": {
            "strategies": ["halfway_chase", "first_limit_up", "leader_buy_dip", "limit_down_qiao"],
            "start_date": "20260105",
            "end_date": "20260320",
            "initial_cash": 1000000,
            "period": "daily",
            "params": {
                "stop_loss_pct": 0.03,
                "take_profit_pct": 0.07,
                "max_hold_days": 3,
                "max_position_per_stock": 0.15,
                "liquidity_threshold": 500,
                "max_position": 0.7,
                "commission_rate": 0.0002,
                "stamp_duty_rate": 0.001,
                "slippage_pct": 0.001,
            },
            "selected_strategies": [
                {"id": "halfway_chase", "name": "半路追涨", "params": {
                    "min_volume_ratio": 2.0,
                    "min_rise_pct": 0.02,
                    "max_rise_pct": 0.07,
                }},
                {"id": "first_limit_up", "name": "首板打板", "params": {}},
                {"id": "leader_buy_dip", "name": "龙头低吸", "params": {}},
                {"id": "limit_down_qiao", "name": "跌停翘板", "params": {}},
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


async def run_one(name, params):
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    task_id = f"phase1_{name}_{int(time.time())}"
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
    
    return {
        "name": name,
        "total_return": r.get('total_return_pct', 0),
        "alpha": r.get('alpha_pct', 0),
        "win_rate": k.get('win_rate_pct', 0),
        "max_drawdown": k.get('max_drawdown_pct', 0),
        "sharpe": k.get('sharpe_ratio', 0),
        "total_trades": t.get('total_trades', 0),
        "elapsed": elapsed,
    }


async def main():
    await mongo_manager.initialize()
    
    print("=" * 80)
    print("Phase1 验证回测: 20260105~20260320")
    print("修复: T+1约束 + 半路追涨买入价 + 跳空止损 + 止损卖出价")
    print("=" * 80)
    
    # Run 1: 半路追涨 alone
    print("\n📊 Test 1: 半路追涨(单独)")
    r1 = await run_one("halfway_only", build_halfway_only())
    print(f"  收益: {r1['total_return']:+.2f}% | Alpha: {r1['alpha']:+.2f}% | 胜率: {r1['win_rate']:.0f}%")
    print(f"  回撤: {r1['max_drawdown']:.2f}% | 夏普: {r1['sharpe']:.2f} | 交易: {r1['total_trades']}笔")
    print(f"  耗时: {r1['elapsed']:.0f}s")
    
    # Run 2: All 4 strategies
    print("\n📊 Test 2: 4策略组合")
    r2 = await run_one("all_strategies", build_all_strategies())
    print(f"  收益: {r2['total_return']:+.2f}% | Alpha: {r2['alpha']:+.2f}% | 胜率: {r2['win_rate']:.0f}%")
    print(f"  回撤: {r2['max_drawdown']:.2f}% | 夏普: {r2['sharpe']:.2f} | 交易: {r2['total_trades']}笔")
    print(f"  耗时: {r2['elapsed']:.0f}s")
    
    # Comparison
    print("\n" + "=" * 80)
    print("📊 对比参考(修复前历史结果, 同区间半路追涨):")
    print("  修复前: 收益+436.8% | 胜率83% | 111笔 | 回撤~1.5%")
    print()
    print(f"  修复后: 收益{r1['total_return']:+.2f}% | 胜率{r1['win_rate']:.0f}% | {r1['total_trades']}笔 | 回撤{r1['max_drawdown']:.2f}%")
    print("=" * 80)
    
    # Save
    out = os.path.join(BASE, 'phase1_verify_results.json')
    with open(out, 'w') as f:
        json.dump({"halfway_only": r1, "all_strategies": r2}, f, default=str, indent=2, ensure_ascii=False)
    print(f"\n📁 {out}")


if __name__ == "__main__":
    asyncio.run(main())
