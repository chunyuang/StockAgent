"""V33回测+详细亏损分析"""
import asyncio
import sys
import os
import types
import time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

def build_params():
    return {
        "params": {
            "strategies": ["dragon_head_dip", "limit_down_qiao", "halfway_chase"],
            "start_date": "20260105",
            "end_date": "20260320",
            "initial_cash": 1000000,
            "period": "daily",
            "params": {
                "stop_loss_pct": 0.05,
                "take_profit_pct": 0.15,
                "max_hold_days": 3,
                "max_position_per_stock": 0.2,
                "liquidity_threshold": 500,
                "max_position": 0.7,
                "commission_rate": 0.0003,
                "stamp_duty_rate": 0.001,
                "slippage_pct": 0.002,
            },
            "selected_strategies": [
                {"id": "dragon_head", "name": "龙头低吸", "params": {}, "riskParams": {
                    "stop_loss_pct": 0.05, "take_profit_pct": 0.15, "max_hold_days": 4, "slippage_pct": 0.002
                }},
                {"id": "limit_down_qiao", "name": "跌停翘板", "params": {}, "riskParams": {
                    "stop_loss_pct": 0.04, "take_profit_pct": 0.25, "max_hold_days": 3, "slippage_pct": 0.003
                }},
                {"id": "halfway_chase", "name": "半路追涨", "params": {}, "riskParams": {
                    "stop_loss_pct": 0.05, "take_profit_pct": 0.12, "max_hold_days": 3, "slippage_pct": 0.002
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

async def main():
    await mongo_manager.initialize()
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    task_id = f"v33_verify_{int(time.time())}"
    logs = []
    
    async def push_log(tid, msg):
        logs.append(msg)
    
    t0 = time.time()
    result = await execute_ultra_short_backtest(
        params=build_params(), push_log_fn=push_log, node_logger=None, task_id=task_id,
    )
    elapsed = time.time() - t0
    
    if not result:
        print("回测失败")
        return
    
    m = result.get('metrics', {})
    r = m.get('returns', {})
    k = m.get('risk', {})
    t = m.get('trades', {})
    
    print(f"\n{'='*60}")
    print(f"V33验证回测 ({elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  信号数:     {t.get('total_trades', '?')}")
    print(f"  胜率:       {k.get('win_rate_pct', 0):.2f}%")
    print(f"  累计收益率: {r.get('total_return_pct', 0):.2f}%")
    print(f"  最大回撤:   {k.get('max_drawdown_pct', 0):.2f}%")
    print(f"  盈亏比:     {k.get('profit_loss_ratio', 0):.2f}")
    print(f"  夏普比率:   {k.get('sharpe_ratio', 0):.2f}")
    
    # 详细交易分析
    trades = result.get('trades', [])
    
    # 1. 亏损交易
    losses = [t2 for t2 in trades if t2.get('profit_pct') is not None and t2['profit_pct'] < 0]
    print(f"\n=== 亏损交易: {len(losses)}笔 ===")
    for t2 in sorted(losses, key=lambda x: x['profit_pct']):
        print(f"  {t2['sell_date']} {t2['ts_code']} {t2.get('stock_name',''):8s} 策略:{t2.get('strategy_name',''):6s} 利润:{t2['profit_pct']:7.2f}% 原因:{t2.get('sell_reason',''):12s} 买入:{t2['buy_price']:8.2f} 卖出:{t2['sell_price']:8.2f} 持仓:{t2.get('hold_days','')}")
    
    # 2. 冲高回落/利润保护交易
    pullback = [t2 for t2 in trades if '冲高回落' in str(t2.get('sell_reason','')) or '利润保护' in str(t2.get('sell_reason',''))]
    print(f"\n=== 冲高回落/利润保护: {len(pullback)}笔 ===")
    avg_profit = sum(t2.get('profit_pct',0) for t2 in pullback) / len(pullback) if pullback else 0
    print(f"  平均利润: {avg_profit:.2f}%")
    
    # 3. 调仓卖出中的亏损
    rebal_losses = [t2 for t2 in trades if '调仓' in str(t2.get('sell_reason','')) and t2.get('profit_pct') is not None and t2['profit_pct'] < -3]
    print(f"\n=== 调仓卖出亏损>3%: {len(rebal_losses)}笔 ===")
    for t2 in sorted(rebal_losses, key=lambda x: x['profit_pct']):
        print(f"  {t2['sell_date']} {t2['ts_code']} {t2.get('stock_name',''):8s} 策略:{t2.get('strategy_name',''):6s} 利润:{t2['profit_pct']:7.2f}% 买入:{t2['buy_price']:8.2f} 卖出:{t2['sell_price']:8.2f} 持仓:{t2.get('hold_days','')}")

if __name__ == "__main__":
    asyncio.run(main())
