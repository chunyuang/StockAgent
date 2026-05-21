"""V30全新完整回测 - 3策略(半路追涨+龙头低吸+跌停翘板)
配置: 使用strategy_defaults.py策略默认参数
区间: 20260105-20260520(完整5个月)
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
    
    task_id = f"v30_full_{int(time.time())}"
    key_logs = []
    
    async def push_log(tid, msg):
        key_logs.append(msg)
        if any(k in msg for k in ['✅', '❌', '📊', '🎯', '回测结果', '收益', 'Alpha', '夏普', '回撤', '胜率', '耗时', '策略', '调仓']):
            print(msg)
    
    params = {
        "params": {
            "start_date": "20260105",
            "end_date": "20260520",
            "initial_cash": 1000000,
            "period": "daily",
            "strategies": ["halfway_chase", "dragon_head", "limit_down_qiao"],
            "params": {
                "stop_loss_pct": 0.03,
                "take_profit_pct": 0.07,
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
                {
                    "id": "halfway_chase", "name": "半路追涨",
                    "params": {
                        "min_rise_pct": 0.03, "max_rise_pct": 0.07,
                        "min_volume_ratio": 2.0, "max_volume_ratio": 3.0,
                        "min_close_rise_pct": 0.05, "max_open_rise_pct": 0.03,
                        "allow_after_10am": False,
                        "next_day_open_sell_pct": 0.03,
                    },
                    "riskParams": {
                        "stop_loss_pct": 0.05, "take_profit_pct": 0.12,
                        "max_hold_days": 3, "slippage_pct": 0.002,
                    }
                },
                {
                    "id": "dragon_head", "name": "龙头低吸",
                    "params": {
                        "min_consecutive_limit": 1,
                        "min_circulation_market_cap": 30,
                        "min_correction_pct": 0.05, "max_correction_pct": 0.35,
                        "correction_days_min": 1, "correction_days_max": 7,
                        "support_level": "ma5",
                        "min_volume_ratio": 0.5, "max_volume_ratio": 2.0,
                        "next_day_open_sell_pct": 0.03,
                    },
                    "riskParams": {
                        "stop_loss_pct": 0.05, "take_profit_pct": 0.15,
                        "max_hold_days": 4, "slippage_pct": 0.002,
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
                        "stop_loss_pct": 0.04, "take_profit_pct": 0.25,
                        "max_hold_days": 3, "slippage_pct": 0.003,
                    }
                },
            ],
        }
    }
    
    print(f"\n🚀 V30全新完整回测: 半路追涨+龙头低吸+跌停翘板 | 20260105-20260520")
    print(f"   半路: SL5%/TP12%/3天 | 龙头: SL5%/TP15%/4天 | 翘板: SL4%/TP25%/3天\n")
    
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
    sortino = k.get('sortino_ratio', 0)
    plr = k.get('profit_loss_ratio', 0)
    trades = t.get('total_trades', 0)
    avg_hold = t.get('avg_hold_days', 0)
    
    print(f"\n{'='*60}")
    print(f"📊 V30完整回测结果 ({elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  收益率:    {ret:+.2f}%")
    print(f"  Alpha:     {alpha:+.2f}%")
    print(f"  夏普:      {sharpe:.2f}")
    print(f"  索提诺:    {sortino:.2f}" if sortino else "")
    print(f"  胜率:      {wr:.1f}%")
    print(f"  盈亏比:    {plr:.2f}")
    print(f"  最大回撤:  {dd:.2f}%")
    print(f"  交易:      {trades}")
    print(f"  平均持仓:  {avg_hold:.1f}天" if avg_hold else "")
    
    # V29基线对比
    print(f"\n  V29基线:   658.83%/7.80夏普/6.69%回撤/71.54%胜率/1.75盈亏比")
    
    # 保存完整结果
    out = os.path.join(BASE, 'backtest_v30_full.json')
    with open(out, 'w') as f:
        json.dump(result, f, default=str, indent=2, ensure_ascii=False)
    print(f"\n📁 {out}")
    
    # 输出交易明细摘要
    positions = m.get('positions', {})
    if positions:
        daily_profit = positions.get('daily_profit', [])
        if daily_profit:
            print(f"\n📈 净值曲线点数: {len(daily_profit)}")
    
    # 卖出原因统计
    sell_reasons = t.get('sell_reason_stats', {})
    if sell_reasons:
        print(f"\n📋 卖出原因分布:")
        for reason, count in sorted(sell_reasons.items(), key=lambda x: -x[1]) if isinstance(sell_reasons, dict) else []:
            print(f"  {reason}: {count}")
    
    return result

if __name__ == "__main__":
    asyncio.run(run())
