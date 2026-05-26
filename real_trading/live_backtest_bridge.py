"""
实盘-回测互惠校准模块

功能：
1. 读取实盘交易记录，计算实际滑点/成交率
2. 与回测假设对比，生成校准建议
3. 输出可手动应用到strategy_defaults.py的参数调整建议

使用方式:
  python -m real_trading.live_backtest_bridge [--days 30] [--output calibration_report.md]

设计原则：
- 只读取数据，不自动修改参数（人工审核后才应用）
- 不影响回测模块代码
- 不影响实盘模块代码
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "AgentServer"))

from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK


def load_live_trades(days: int = 30) -> list:
    """从实盘交易历史文件读取最近N天的交易"""
    trade_file = PROJECT_ROOT / "real_trading" / "trade_history.json"
    if not trade_file.exists():
        print(f"⚠️ 实盘交易文件不存在: {trade_file}")
        return []
    
    with open(trade_file) as f:
        all_trades = json.load(f)
    
    # 过滤最近N天
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    recent = [t for t in all_trades if str(t.get('date', '')) >= cutoff]
    return recent


def load_backtest_trades(task_id: str = None) -> list:
    """从MongoDB读取最近一次回测的交易记录"""
    try:
        import asyncio
        from core.managers.mongo_manager import mongo_manager
        
        async def _load():
            await mongo_manager.initialize()
            coll = mongo_manager.db['backtest_tasks']
            if task_id:
                doc = await coll.find_one({'task_id': task_id})
            else:
                doc = await coll.find_one({}, sort=[('_id', -1)])
            await mongo_manager.shutdown()
            if doc and 'result' in doc:
                return doc['result'].get('merged_trades', [])
            return []
        
        return asyncio.run(_load())
    except Exception as e:
        print(f"⚠️ 读取回测数据失败: {e}")
        return []


def analyze_slippage_calibration(live_trades: list) -> dict:
    """分析实盘滑点，与回测假设对比"""
    by_strategy = defaultdict(list)
    
    for t in live_trades:
        strategy = t.get('strategy', '未知')
        if t.get('action') == 'buy' and t.get('slippage_pct') is not None:
            by_strategy[strategy].append(t.get('slippage_pct', 0))
    
    results = {}
    for strategy, slippages in by_strategy.items():
        if not slippages:
            continue
        avg_slip = sum(slippages) / len(slippages)
        max_slip = max(slippages)
        
        # 从strategy_defaults读取假设滑点
        _NAME_TO_ID = {cfg["name"]: sid for sid, cfg in STRATEGY_CONFIGS.items()}
        sid = _NAME_TO_ID.get(strategy, '')
        assumed_slip = STRATEGY_CONFIGS.get(sid, {}).get('riskParams', {}).get('slippage_pct', GLOBAL_RISK['slippage_pct'])
        
        results[strategy] = {
            'avg_actual': avg_slip,
            'max_actual': max_slip,
            'assumed': assumed_slip,
            'count': len(slippages),
            'deviation': avg_slip - assumed_slip,
        }
    
    return results


def analyze_win_rate_calibration(live_trades: list, backtest_trades: list) -> dict:
    """对比实盘和回测的胜率/盈亏比"""
    # 实盘胜率
    live_by_strategy = defaultdict(list)
    for t in live_trades:
        if t.get('action') == 'sell' and t.get('profit_pct') is not None:
            strategy = t.get('strategy', '未知')
            live_by_strategy[strategy].append(t['profit_pct'])
    
    # 回测胜率
    bt_by_strategy = defaultdict(list)
    for t in backtest_trades:
        if t.get('sell_reason') != '持仓中' and t.get('profit_pct') is not None:
            strategy = t.get('strategy', '未知')
            bt_by_strategy[strategy].append(t['profit_pct'])
    
    results = {}
    all_strategies = set(list(live_by_strategy.keys()) + list(bt_by_strategy.keys()))
    for strategy in all_strategies:
        live_pnls = live_by_strategy.get(strategy, [])
        bt_pnls = bt_by_strategy.get(strategy, [])
        
        live_wr = sum(1 for p in live_pnls if p > 0) / len(live_pnls) * 100 if live_pnls else 0
        bt_wr = sum(1 for p in bt_pnls if p > 0) / len(bt_pnls) * 100 if bt_pnls else 0
        
        results[strategy] = {
            'live_count': len(live_pnls),
            'live_win_rate': live_wr,
            'live_avg_pnl': sum(live_pnls) / len(live_pnls) if live_pnls else 0,
            'bt_count': len(bt_pnls),
            'bt_win_rate': bt_wr,
            'bt_avg_pnl': sum(bt_pnls) / len(bt_pnls) if bt_pnls else 0,
            'wr_gap': live_wr - bt_wr,
        }
    
    return results


def generate_calibration_report(days: int = 30) -> str:
    """生成校准报告"""
    live_trades = load_live_trades(days)
    backtest_trades = load_backtest_trades()
    
    report = []
    report.append(f"# 实盘-回测互惠校准报告")
    report.append(f"\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append(f"实盘数据: 最近{days}天, {len(live_trades)}笔交易")
    report.append(f"回测数据: {len(backtest_trades)}笔交易\n")
    
    # 1. 滑点校准
    report.append("## 1. 滑点校准\n")
    slip_results = analyze_slippage_calibration(live_trades)
    if slip_results:
        report.append("| 策略 | 实盘均滑点 | 回测假设 | 偏差 | 笔数 | 建议 |")
        report.append("|------|-----------|---------|------|------|------|")
        for strategy, data in sorted(slip_results.items()):
            deviation = data['deviation']
            if abs(deviation) > 0.001:  # 偏差>0.1%
                suggestion = f"调整slippage_pct→{data['avg_actual']:.4f}"
            else:
                suggestion = "无需调整"
            report.append(f"| {strategy} | {data['avg_actual']*100:.2f}% | {data['assumed']*100:.2f}% | {deviation*100:+.2f}% | {data['count']} | {suggestion} |")
    else:
        report.append("暂无实盘滑点数据\n")
    
    # 2. 胜率校准
    report.append("\n## 2. 胜率校准\n")
    wr_results = analyze_win_rate_calibration(live_trades, backtest_trades)
    if wr_results:
        report.append("| 策略 | 实盘笔数 | 实盘胜率 | 回测胜率 | 胜率差 | 实盘均盈亏 | 回测均盈亏 |")
        report.append("|------|---------|---------|---------|-------|-----------|-----------|")
        for strategy, data in sorted(wr_results.items()):
            if data['live_count'] > 0:
                report.append(f"| {strategy} | {data['live_count']} | {data['live_win_rate']:.1f}% | {data['bt_win_rate']:.1f}% | {data['wr_gap']:+.1f}% | {data['live_avg_pnl']:.2f}% | {data['bt_avg_pnl']:.2f}% |")
    else:
        report.append("暂无实盘交易数据\n")
    
    # 3. 参数建议
    report.append("\n## 3. 参数调整建议\n")
    report.append("以下建议基于实盘数据，需人工审核后应用到 strategy_defaults.py:\n")
    
    for strategy, data in slip_results.items():
        if abs(data['deviation']) > 0.001:
            _NAME_TO_ID = {cfg["name"]: sid for sid, cfg in STRATEGY_CONFIGS.items()}
            sid = _NAME_TO_ID.get(strategy, '')
            report.append(f"- **{strategy}**: `STRATEGY_CONFIGS['{sid}']['riskParams']['slippage_pct']` → {data['avg_actual']:.4f}")
    
    for strategy, data in wr_results.items():
        if data['live_count'] >= 5 and data['wr_gap'] < -15:
            report.append(f"- **{strategy}**: 实盘胜率({data['live_win_rate']:.1f}%)远低于回测({data['bt_win_rate']:.1f}%), 建议检查选股条件是否过松")
    
    report.append("\n---\n*此报告由 live_backtest_bridge.py 自动生成，不自动修改任何参数*")
    
    return '\n'.join(report)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='实盘-回测互惠校准')
    parser.add_argument('--days', type=int, default=30, help='分析最近N天实盘数据')
    parser.add_argument('--output', type=str, default=None, help='输出文件路径')
    args = parser.parse_args()
    
    report = generate_calibration_report(args.days)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"✅ 报告已写入: {args.output}")
    else:
        print(report)
