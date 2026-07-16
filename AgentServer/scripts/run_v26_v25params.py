"""V26基线回测 - V25同参数(全局SL3%/TP7%)"""
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
from core.constants import C

async def main():
    await mongo_manager.initialize()
    
    from nodes.backtest_engine.strategy_defaults import ALL_STRATEGIES, STRATEGY_CONFIGS
    from nodes.backtest_engine.factor_selection import PortfolioBacktester
    from nodes.backtest_engine.factor_selection.universe import UniverseManager, ExcludeRule
    from nodes.backtest_engine.factor_selection.factor_engine import FactorEngine
    
    universe_mgr = UniverseManager()
    universe_mgr.start_date = '20260105'
    universe_mgr.end_date = '20260320'
    universe_mgr.exclude_rules = [ExcludeRule.ST, ExcludeRule.NEW_STOCK]
    universe_mgr.min_liquidity = 500
    
    # V25同参数：用策略默认参数(SL5%/TP12%+SL5%/TP20%)
    selected = []
    for s in ALL_STRATEGIES:
        sid = s.get('id', '')
        cfg = STRATEGY_CONFIGS.get(sid, {})
        rp = dict(cfg.get("riskParams", {}))
        # V25: 全局SL3%/TP7%覆盖策略级参数
        # 但V25实际用的是策略级SL5%/TP12%等(在V24中验证过)
        selected.append({
            "id": sid,
            "name": s.get("name", cfg.get("name", sid)),
            "params": dict(cfg.get("params", {})),
            "riskParams": rp,  # 策略默认参数
        })
    
    config = {
        'start_date': '20260105', 'end_date': '20260320',
        'initial_cash': 1000000, 'max_position_percent': 0.2,
        'liquidity_threshold': 500, 'data_collection': C.STOCK_DAILY,
        'universe_mgr': universe_mgr, 'factor_engine': FactorEngine(),
        'exclude_rules': [ExcludeRule.ST, ExcludeRule.NEW_STOCK],
        'factors': [], 'top_n': 10, 'rebalance_freq': 'daily',
        'task_id': 'v26_baseline_v25params',
        'push_log': lambda tid, msg: asyncio.sleep(0),
        'strategy_weights': {},
        'selected_strategies': selected,
        'volume_threshold': 2.0, 'weight_method': 'equal',
        'commission_rate': 0.0003, 'stamp_duty_rate': 0.001, 'slippage_pct': 0.002,
        'stop_loss_pct': 0.03, 'take_profit_pct': 0.07,  # 全局默认(策略级会覆盖)
        'max_hold_days': 3, 'max_position_per_stock': 0.2,
        'enable_auction_filter': True, 'enable_sentiment_cycle': True,
        'enable_force_empty': True, 'enable_stop_loss': True,
        'enable_take_profit': True, 'enable_ma60_filter': True,
        'enable_sector_concentration': True,
        'force_empty_config': {}, 'global_filter_config': {},
    }
    
    t0 = time.time()
    bt = PortfolioBacktester()
    result = await bt.run(config)
    elapsed = time.time() - t0
    
    if result and 'error' not in result:
        m = result.get('metrics', {})
        rd = m.get('returns', {})
        rk = m.get('risk', {})
        td = m.get('trades', {})
        
        print('\n=== V26 BASELINE (V25同参数=策略默认) ===')
        print(f'收益: {rd.get("total_return", 0):.2f}%')
        print(f'夏普: {rk.get("sharpe_ratio", 0):.2f}')
        print(f'回撤: {rk.get("max_drawdown", 0):.2f}%')
        print(f'胜率: {rk.get("win_rate", 0):.2f}%')
        print(f'盈亏比: {rk.get("profit_loss_ratio", 0):.2f}')
        print(f'交易数: {td.get("total_trades", 0)}')
        print(f'耗时: {elapsed:.1f}s')
        
        srs = {}
        for t in (result.get('merged_trades', []) or []):
            reason = str(t.get('reason', t.get('sell_reason', '')))
            if not reason or reason == '持仓中': continue
            if '止损' in reason or '跳空止损' in reason: srs['止损'] = srs.get('止损', 0) + 1
            elif '止盈' in reason: srs['止盈'] = srs.get('止盈', 0) + 1
            elif '冲高回落' in reason: srs['冲高回落'] = srs.get('冲高回落', 0) + 1
            elif '利润保护' in reason: srs['利润保护'] = srs.get('利润保护', 0) + 1
            elif '高开即卖' in reason: srs['高开即卖'] = srs.get('高开即卖', 0) + 1
            elif '超时' in reason or '停牌' in reason: srs['超时'] = srs.get('超时', 0) + 1
            elif '空仓' in reason or '强制' in reason: srs['强制空仓'] = srs.get('强制空仓', 0) + 1
            elif '调仓' in reason or 'rebalance' in reason or '减仓' in reason: srs['调仓'] = srs.get('调仓', 0) + 1
            else: srs['other'] = srs.get('other', 0) + 1
        print(f'卖出原因: {srs}')
        
        sr = result.get('strategy_results', {})
        for name, data in sr.items():
            print(f'  {name}: 胜率{data.get("win_rate",0):.1f}% 收益{data.get("total_return",0):.2f}% 笔数{data.get("trades_count",0)} PLR{data.get("profit_loss_ratio",0):.2f}')
    else:
        print(f'ERROR: {result}')
    
    await mongo_manager.shutdown()

asyncio.run(main())
