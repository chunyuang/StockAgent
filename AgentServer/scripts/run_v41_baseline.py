"""V41基准回测 - 获取当前配置的回测结果作为优化基线"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager


def build_baseline_params():
    """当前默认3策略配置"""
    return {
        "params": {
            "strategies": ["halfway_chase", "dragon_head", "limit_down_qiao"],
            "start_date": "20260105",
            "end_date": "20260320",
            "initial_cash": 1000000,
            "period": "daily",
            "params": {
                "stop_loss_pct": 0.03,
                "take_profit_pct": 0.07,
                "max_hold_days": 3,
                "max_position_per_stock": 0.2,
                "liquidity_threshold": 500,
                "max_total_position": 0.7,
                "commission_rate": 0.0003,
                "stamp_duty_rate": 0.001,
                "slippage_pct": 0.002,
            },
            "selected_strategies": [
                {
                    "id": "halfway_chase", "name": "半路追涨",
                    "params": {
                        "min_volume_ratio": 2.0,
                        "min_rise_pct": 0.03,
                        "max_rise_pct": 0.07,
                        "min_close_rise_pct": 0.05,
                        "max_open_rise_pct": 0.03,
                        "next_day_open_sell_pct": 0.03,
                    },
                    "riskParams": {
                        "stop_loss_pct": 0.04,
                        "take_profit_pct": 0.12,
                        "max_hold_days": 3,
                        "slippage_pct": 0.002,
                    }
                },
                {
                    "id": "dragon_head", "name": "龙头低吸",
                    "params": {
                        "min_consecutive_limit": 1,
                        "min_circulation_market_cap": 30,
                        "min_correction_pct": 0.05,
                        "max_correction_pct": 0.20,
                        "correction_days_min": 1,
                        "correction_days_max": 7,
                        "min_volume_ratio": 0.5,
                        "max_volume_ratio": 2.0,
                        "next_day_open_sell_pct": 0.03,
                    },
                    "riskParams": {
                        "stop_loss_pct": 0.03,
                        "take_profit_pct": 0.30,
                        "max_hold_days": 5,
                        "slippage_pct": 0.002,
                    }
                },
                {
                    "id": "limit_down_qiao", "name": "跌停翘板",
                    "params": {
                        "min_consecutive_limit": 2,
                        "min_turnover_rate": 10,
                        "min_qiao_amount": 1000,
                        "min_rise_after_qiao": 0.03,
                        "min_circulation_market_cap": 20,
                        "require_high_sentiment": False,
                        "next_day_open_sell_pct": 0.03,
                    },
                    "riskParams": {
                        "stop_loss_pct": 0.05,
                        "take_profit_pct": 0.20,
                        "max_hold_days": 3,
                        "slippage_pct": 0.003,
                    }
                },
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


async def main():
    await mongo_manager.initialize()
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest

    p = build_baseline_params()
    task_id = f"v41_baseline_{int(time.time())}"
    logs = []

    async def push_log(tid, msg):
        logs.append(msg)

    t0 = time.time()
    print("🚀 V41基准回测: 3策略组合 20260105~20260320 ¥1M")
    print("=" * 70)

    result = await execute_ultra_short_backtest(
        params=p, push_log_fn=push_log, node_logger=None, task_id=task_id,
    )

    elapsed = time.time() - t0
    m = result.get('metrics', {})
    r = m.get('returns', {})
    k = m.get('risk', {})
    t = m.get('trades', {})
    perf_list = result.get('performance', [])
    perf = perf_list[0] if perf_list else {}

    ret = r.get('total_return_pct', result.get('total_return', perf.get('total_return', 0)))
    alpha_val = r.get('alpha_pct', result.get('alpha_pct', perf.get('alpha', 0)))
    wr = k.get('win_rate_pct', result.get('win_rate', perf.get('win_rate', 0)))
    dd = k.get('max_drawdown_pct', result.get('max_drawdown', perf.get('max_drawdown', 0)))
    trades = t.get('total_trades', result.get('total_trades', perf.get('total_trades', 0)))
    sharpe = k.get('sharpe_ratio', result.get('sharpe_ratio', perf.get('sharpe_ratio', 0)))
    calmar = k.get('calmar_ratio', result.get('calmar_ratio', perf.get('calmar_ratio', 0)))
    sortino = k.get('sortino_ratio', result.get('sortino_ratio', perf.get('sortino_ratio', 0)))
    plr = k.get('profit_loss_ratio', result.get('profit_loss_ratio', perf.get('profit_loss_ratio', 0)))
    avg_hold = t.get('average_hold_days', perf.get('average_hold_days', 0))
    sell_stats = perf.get('sell_reason_stats', {})
    perf.get('execution_time_ms', int(elapsed * 1000))

    print(f"\n📊 V41基准结果 (耗时{elapsed:.1f}s):")
    print(f"  累计收益率: {ret:+.2f}%")
    print(f"  超额收益(Alpha): {alpha_val:+.2f}%")
    print(f"  胜率: {wr:.1f}%")
    print(f"  最大回撤: {dd:.2f}%")
    print(f"  夏普比率: {sharpe:.2f}")
    print(f"  卡玛比率: {calmar:.2f}")
    print(f"  索提诺比率: {sortino:.2f}")
    print(f"  盈亏比: {plr:.2f}")
    print(f"  总交易: {trades}笔")
    print(f"  平均持仓: {avg_hold:.1f}天")
    print(f"  卖出原因: {sell_stats}")

    # 保存完整结果
    out_path = os.path.join(BASE, 'v41_baseline_result.json')
    with open(out_path, 'w') as f:
        # 去掉大的时间序列数据
        save_result = {k: v for k, v in result.items()
                       if k not in ('net_value_series', 'drawdown_series', 'daily_profit')}
        json.dump(save_result, f, default=str, indent=2, ensure_ascii=False)
    print(f"\n📁 完整结果: {out_path}")

    # 打印关键基线值，供后续对比
    print("\n📊 基线数值(供V41优化对比):")
    print(f"  ret={ret:.2f} alpha={alpha_val:.2f} wr={wr:.1f} dd={dd:.2f} sharpe={sharpe:.2f} calmar={calmar:.2f} trades={trades}")


if __name__ == "__main__":
    asyncio.run(main())
