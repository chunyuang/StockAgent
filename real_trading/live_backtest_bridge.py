"""
实盘-回测互惠校准模块

功能：
1. 读取实盘交易记录，计算实际滑点/成交率
2. 与回测假设对比，生成校准建议
3. 输出可手动应用到strategy_defaults.py的参数调整建议
4. 【V63:实盘vs回测偏差监控,超阈值自动告警】
5. 【V63:回测参数变更自动同步到实盘(通过读取最新strategy_defaults.py)】

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
    # 【V66-P0-2修复】兼容trade_history.json格式: 字段为sell_date而非date
    recent = [t for t in all_trades if str(t.get('sell_date', t.get('date', ''))) >= cutoff]
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
        # 【V65修复】兼容多种交易记录格式: action字段或buy_date/sell_date推断
        is_buy = t.get('action') == 'buy' or (t.get('buy_date') and not t.get('sell_date'))
        slippage = t.get('slippage_pct') or t.get('slippage_actual_pct')  # 兼容两种字段名
        if is_buy and slippage is not None:
            by_strategy[strategy].append(float(slippage))
    
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


def check_live_backtest_deviation(wr_results: dict, slip_results: dict) -> list:
    """【V63】实盘vs回测偏差监控:超阈值自动告警
    
    阈值:
    - 胜率偏差 > 15% → 告警(实盘胜率远低于回测)
    - 收益偏差 > 3% → 告警(实盘均盈亏远低于回测)
    - 滑点偏差 > 0.2% → 告警(实盘滑点远超回测假设)
    
    Returns:
        list: 告警消息列表
    """
    alerts = []
    
    # 胜率偏差
    WIN_RATE_THRESHOLD = 15.0  # 百分点
    for strategy, data in wr_results.items():
        if data['live_count'] >= 3:  # 至少3笔实盘交易才有效
            wr_gap = abs(data['wr_gap'])
            if data['wr_gap'] < -WIN_RATE_THRESHOLD:
                alerts.append(f"🔴 **{strategy}** 胜率严重偏差: 实盘{data['live_win_rate']:.1f}% vs 回测{data['bt_win_rate']:.1f}% (差{data['wr_gap']:+.1f}%)")
            elif data['wr_gap'] < -WIN_RATE_THRESHOLD / 2:
                alerts.append(f"🟡 **{strategy}** 胜率轻度偏差: 实盘{data['live_win_rate']:.1f}% vs 回测{data['bt_win_rate']:.1f}% (差{data['wr_gap']:+.1f}%)")
    
    # 收益偏差
    PNL_THRESHOLD = 3.0  # 百分点
    for strategy, data in wr_results.items():
        if data['live_count'] >= 3:
            pnl_gap = data['live_avg_pnl'] - data['bt_avg_pnl']
            if pnl_gap < -PNL_THRESHOLD:
                alerts.append(f"🔴 **{strategy}** 收益严重偏差: 实盘均{data['live_avg_pnl']:.2f}% vs 回测{data['bt_avg_pnl']:.2f}% (差{pnl_gap:+.2f}%)")
    
    # 滑点偏差
    SLIP_THRESHOLD = 0.002  # 0.2%
    for strategy, data in slip_results.items():
        if data['deviation'] > SLIP_THRESHOLD:
            alerts.append(f"🟡 **{strategy}** 滑点偏差: 实盘{data['avg_actual']*100:.2f}% vs 假设{data['assumed']*100:.2f}% (差{data['deviation']*100:+.2f}%)")
    
    return alerts


def check_param_sync_status() -> list:
    """【V63】检查实盘参数与最新strategy_defaults.py的同步状态
    
    读取strategy_defaults.py中的最新参数,与实盘模块使用的参数对比。
    实盘模块通过from...import读取,只要重启服务就会获取最新参数。
    这里检查的是:是否有需要重启才能生效的参数变更。
    
    Returns:
        list: 同步状态消息列表
    """
    status = []
    
    # 检查strategy_defaults.py最近修改时间
    defaults_path = PROJECT_ROOT / "AgentServer" / "nodes" / "backtest_engine" / "strategy_defaults.py"
    if defaults_path.exists():
        mtime = datetime.fromtimestamp(defaults_path.stat().st_mtime)
        hours_ago = (datetime.now() - mtime).total_seconds() / 3600
        status.append(f"strategy_defaults.py 最后修改: {mtime.strftime('%Y-%m-%d %H:%M')} ({hours_ago:.1f}小时前)")
        if hours_ago < 1:
            status.append(f"⚠️ strategy_defaults.py 在{hours_ago:.1f}小时内被修改,实盘服务需要重启才能生效")
    
    # 检查关键参数当前值
    status.append(f"当前参数: stop_loss={GLOBAL_RISK['stop_loss_pct']*100:.0f}%, "
                  f"take_profit={GLOBAL_RISK['take_profit_pct']*100:.0f}%, "
                  f"max_hold={GLOBAL_RISK['max_hold_days']}天, "
                  f"intraday_lock_high={GLOBAL_RISK.get('intraday_lock_min_high_rise', 0.05)*100:.0f}%")
    
    return status


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
    
    # 4. 持仓集中度校准
    report.append("\n## 4. 持仓集中度校准\n")
    live_positions = {}  # TODO: 从实盘持仓读取
    if live_positions:
        live_count = len(live_positions)
        report.append(f"实盘当前持仓: {live_count}只")
    else:
        report.append("暂无实盘持仓数据\n")
    
    # 5. 回测参数敏感性
    report.append("\n## 5. 回测参数敏感性\n")
    report.append("以下参数调整可能影响回测表现(仅供参考):\n")
    report.append("- max_position_per_stock: 当前0.35, 降至0.30可降低集中度风险但减少总收益")
    report.append("- intraday_lock_min_high_rise: 当前0.05, 降至0.04可更早锁定利润但可能过早退出")
    report.append("- hold_protection_threshold: 当前0.05, 降至0.04可保护更多盈利股但可能阻碍调仓")
    
    # 【V63新增:实盘vs回测偏差监控】
    report.append("\n## 6. 实盘vs回测偏差监控 【V63】\n")
    deviation_alerts = check_live_backtest_deviation(wr_results, slip_results)
    if deviation_alerts:
        for alert in deviation_alerts:
            report.append(f"- {alert}")
    else:
        report.append("✅ 实盘与回测偏差在正常范围内\n")
    
    # 【V63新增:回测参数变更自动同步状态】
    report.append("\n## 7. 回测参数同步状态 【V63】\n")
    sync_status = check_param_sync_status()
    if sync_status:
        for item in sync_status:
            report.append(f"- {item}")
    else:
        report.append("✅ 实盘参数与strategy_defaults.py一致\n")
    
    # 自动化校准流程
    report.append("\n## 8. 自动化校准流程\n")
    report.append("```\n")
    report.append("1. 每周运行: python -m real_trading.live_backtest_bridge --days 7\n")
    report.append("2. 检查滑点偏差: |实盘均滑点 - 回测假设| > 0.1% → 调整slippage_pct\n")
    report.append("3. 检查胜率偏差: 实盘胜率 < 回测胜率-15% → 检查选股条件\n")
    report.append("4. 修改参数: 只修改strategy_defaults.py, 不修改其他文件\n")
    report.append("5. 验证: 修改后运行回测,确认回测指标不退化\n")
    report.append("```\n")
    
    report.append("\n---")
    report.append(f"\n*此报告由 live_backtest_bridge.py V63 自动生成，不自动修改任何参数*")
    report.append(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    
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
