"""V27参数扫描 - 测试冲高回落区间阈值+龙头TP+跌停SL"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager
from core.constants import C

async def run_backtest(params_overrides=None, label=''):
    await mongo_manager.initialize()
    
    from nodes.backtest_engine.strategy_defaults import ALL_STRATEGIES, GLOBAL_RISK, STRATEGY_CONFIGS
    from nodes.backtest_engine.factor_selection import PortfolioBacktester
    from nodes.backtest_engine.factor_selection.universe import UniverseManager, ExcludeRule
    from nodes.backtest_engine.factor_selection.factor_engine import FactorEngine
    
    universe_mgr = UniverseManager()
    universe_mgr.start_date = '20260105'
    universe_mgr.end_date = '20260320'
    universe_mgr.exclude_rules = [ExcludeRule.ST, ExcludeRule.NEW_STOCK]
    universe_mgr.min_liquidity = 500
    
    selected = []
    for s in ALL_STRATEGIES:
        sid = s.get('id', '')
        cfg = STRATEGY_CONFIGS.get(sid, {})
        sel = {
            "id": sid,
            "name": s.get("name", cfg.get("name", sid)),
            "params": dict(cfg.get("params", {})),
            "riskParams": dict(cfg.get("riskParams", {})),
        }
        # 应用参数覆盖
        if params_overrides and sid in params_overrides:
            if 'params' in params_overrides[sid]:
                sel['params'].update(params_overrides[sid]['params'])
            if 'riskParams' in params_overrides[sid]:
                sel['riskParams'].update(params_overrides[sid]['riskParams'])
        selected.append(sel)
    
    config = {
        'start_date': '20260105', 'end_date': '20260320',
        'initial_cash': 1000000, 'max_position_percent': 0.2,
        'liquidity_threshold': 500, 'data_collection': C.STOCK_DAILY,
        'universe_mgr': universe_mgr, 'factor_engine': FactorEngine(),
        'exclude_rules': [ExcludeRule.ST, ExcludeRule.NEW_STOCK],
        'factors': [], 'top_n': 10, 'rebalance_freq': 'daily',
        'task_id': f'v27_scan_{label}',
        'push_log': lambda tid, msg: asyncio.sleep(0),
        'strategy_weights': {},
        'selected_strategies': selected,
        'volume_threshold': 2.0, 'weight_method': 'equal',
        'commission_rate': 0.0003, 'stamp_duty_rate': 0.001, 'slippage_pct': 0.002,
        'stop_loss_pct': 0.03, 'take_profit_pct': 0.07,
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
    
    await mongo_manager.shutdown()
    
    if result and 'error' not in result:
        m = result.get('metrics', {})
        rd = m.get('returns', {})
        rk = m.get('risk', {})
        td = m.get('trades', {})
        return {
            'label': label,
            'return': rd.get('total_return', 0),
            'sharpe': rk.get('sharpe_ratio', 0),
            'drawdown': rk.get('max_drawdown', 0),
            'win_rate': rk.get('win_rate', 0),
            'plr': rk.get('profit_loss_ratio', 0),
            'trades': td.get('total_trades', 0),
            'elapsed': elapsed,
        }
    return {'label': label, 'error': result.get('error', 'unknown') if result else 'None'}

async def main():
    # 扫描参数组合
    scans = [
        # 0: V27当前(基线)
        ({}, 'V27_基线'),
        # 1: 龙头低吸TP 10%→12%
        ({'dragon_head': {'riskParams': {'take_profit_pct': 0.12}}}, '龙头TP12%'),
        # 2: 龙头低吸TP 10%→15%
        ({'dragon_head': {'riskParams': {'take_profit_pct': 0.15}}}, '龙头TP15%'),
        # 3: 跌停翘板SL 5%→4%
        ({'limit_down_qiao': {'riskParams': {'stop_loss_pct': 0.04}}}, '跌停SL4%'),
        # 4: 半路追涨SL 5%→4%
        ({'halfway_chase': {'riskParams': {'stop_loss_pct': 0.04}}}, '半路SL4%'),
        # 5: 半路追涨TP 12%→15%
        ({'halfway_chase': {'riskParams': {'take_profit_pct': 0.15}}}, '半路TP15%'),
        # 6: 龙头TP12% + 半路TP15%
        ({'dragon_head': {'riskParams': {'take_profit_pct': 0.12}}, 'halfway_chase': {'riskParams': {'take_profit_pct': 0.15}}}, '龙头TP12%+半路TP15%'),
        # 7: 龙头TP15% + 跌停SL4%
        ({'dragon_head': {'riskParams': {'take_profit_pct': 0.15}}, 'limit_down_qiao': {'riskParams': {'stop_loss_pct': 0.04}}}, '龙头TP15%+跌停SL4%'),
    ]
    
    results = []
    for overrides, label in scans:
        r = await run_backtest(overrides, label)
        results.append(r)
        if 'error' in r:
            print(f'{label}: ERROR - {r["error"]}')
        else:
            print(f'{label}: 收益{r["return"]:.2f}% 夏普{r["sharpe"]:.2f} 回撤{r["drawdown"]:.2f}% 胜率{r["win_rate"]:.2f}% PLR{r["plr"]:.2f} {r["trades"]}笔')
    
    print('\n=== 排序(按夏普) ===')
    valid = [r for r in results if 'error' not in r]
    valid.sort(key=lambda x: x['sharpe'], reverse=True)
    for r in valid:
        print(f'{r["label"]}: 夏普{r["sharpe"]:.2f} 收益{r["return"]:.2f}% 回撤{r["drawdown"]:.2f}% 胜率{r["win_rate"]:.2f}%')

asyncio.run(main())
