"""优化A1：提高量比阈值测试"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

async def run_optimization_a1():
    """运行优化A1测试：提高量比阈值"""
    await mongo_manager.initialize()
    
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    task_id = f"opt_a1_{int(time.time())}"
    logs = []
    
    async def push_log(tid, msg):
        logs.append(msg)
        # 只打印关键日志
        if any(k in msg for k in ['✅', '❌', '⚠️', '📊', '🎯', '策略', '选股', '候选', '调仓', '回测结果', '收益', 'Alpha']):
            print(msg)
    
    # 优化A1参数：提高量比阈值从1.0到1.5
    params = {
        "start_date": "20260105",
        "end_date": "20260320",
        "initial_cash": 1000000,
        "period": "daily",
        "volume_threshold": 1.5,  # 优化：从1.0提高到1.5
        "stop_loss_pct": 0.03,
        "take_profit_pct": 0.07,
        "max_hold_days": 3,
        "max_position_per_stock": 0.2,
        "liquidity_threshold": 500,
        "max_position": 0.7,
        "commission_rate": 0.0002,
        "stamp_duty_rate": 0.001,
        "slippage_pct": 0.001,
        "enable_stop_loss": True,
        "enable_take_profit": True,
        "enable_ma60_filter": True,
        "enable_sector_concentration": True,
        "enable_force_empty": True,
        "enable_sentiment_cycle": True,
        "enable_auction_filter": False,
        "selected_strategies": [
            {"id": "halfway_chase", "name": "半路追涨", "params": {"min_volume_ratio": 1.5, "min_rise_pct": 0.02, "max_rise_pct": 0.05}},
        ],
    }
    
    print("🚀 优化A1测试：提高量比阈值")
    print("=" * 60)
    print(f"时间区间: {params['start_date']}~{params['end_date']}")
    print(f"初始资金: ¥{params['initial_cash']:,.0f}")
    print(f"优化内容: 量比阈值从1.0提高到1.5")
    print(f"筛选条件: 盘中最高≥2% 且 开盘≤5% 且 量比≥1.5")
    print("=" * 60)
    
    t0 = time.time()
    result = await execute_ultra_short_backtest(
        params=params,
        push_log_fn=push_log,
        node_logger=None,
        task_id=task_id,
    )
    elapsed = time.time() - t0
    
    if result.get("error"):
        print(f"\n❌ 回测失败: {result['error']}")
        return None
    
    # 提取结果
    metrics = result.get('metrics', {})
    returns = metrics.get('returns', {})
    risk = metrics.get('risk', {})
    trades = metrics.get('trades', {})
    
    tr = returns.get('total_return_pct', 0)
    br = returns.get('benchmark_return_pct', 0)
    alpha = returns.get('alpha_pct', 0)
    
    print(f"\n{'='*60}")
    print(f"📊 优化A1测试结果 ({elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  策略收益率:  {tr:+.2f}%")
    print(f"  基准收益率:  {br:+.2f}%")
    print(f"  Alpha:       {alpha:+.2f}%")
    print(f"  胜率:        {risk.get('win_rate_pct', 0):.1f}%")
    print(f"  盈亏比:      {risk.get('profit_loss_ratio', 0):.2f}")
    print(f"  最大回撤:    {risk.get('max_drawdown_pct', 0):.2f}%")
    print(f"  夏普:        {risk.get('sharpe_ratio', 0):.2f}")
    print(f"  交易笔数:    {trades.get('total_trades', 0)}笔")
    
    # 加载Phase2基准结果
    try:
        with open('phase2_test_result.json', 'r') as f:
            phase2_data = json.load(f)
        phase2_summary = phase2_data.get('summary', {})
        
        phase2_return = phase2_summary.get('total_return_pct', 0)
        phase2_win_rate = phase2_summary.get('win_rate_pct', 0)
        phase2_drawdown = phase2_summary.get('max_drawdown_pct', 0)
        phase2_sharpe = phase2_summary.get('sharpe_ratio', 0)
        phase2_trades = phase2_summary.get('total_trades', 0)
        
        print(f"\n{'='*60}")
        print("📈 与Phase2基准对比")
        print(f"{'='*60}")
        print("Phase2 (量比1.0):")
        print(f"  收益: {phase2_return:+.2f}% | 胜率: {phase2_win_rate:.1f}% | 回撤: {phase2_drawdown:.2f}% | 夏普: {phase2_sharpe:.2f} | 交易: {phase2_trades}笔")
        print(f"\n优化A1 (量比1.5):")
        print(f"  收益: {tr:+.2f}% | 胜率: {risk.get('win_rate_pct', 0):.1f}% | 回撤: {risk.get('max_drawdown_pct', 0):.2f}% | 夏普: {risk.get('sharpe_ratio', 0):.2f} | 交易: {trades.get('total_trades', 0)}笔")
        
        # 计算变化
        trade_reduction = (phase2_trades - trades.get('total_trades', 0)) / phase2_trades * 100
        return_change = tr - phase2_return
        
        print(f"\n{'='*60}")
        print("🔍 优化效果评估")
        print(f"{'='*60}")
        print(f"交易笔数减少: {trade_reduction:.1f}%")
        print(f"收益变化: {return_change:+.2f}个百分点")
        
        if trade_reduction > 20 and tr > 0:
            print(f"✅ 优化成功：交易频率降低{trade_reduction:.1f}%，仍保持正收益")
        elif tr <= 0:
            print(f"❌ 优化过度：收益转负，需要调整参数")
        else:
            print(f"⚠️  优化效果一般：交易减少{trade_reduction:.1f}%，但收益变化{return_change:+.2f}%")
        
    except Exception as e:
        print(f"⚠️  无法加载Phase2基准结果: {e}")
    
    # 保存结果
    out_file = os.path.join(BASE, 'optimization_a1_result.json')
    with open(out_file, 'w') as f:
        json.dump({
            'optimization': 'a1_volume_ratio_1.5',
            'params': params,
            'result': result,
            'summary': {
                'total_return_pct': tr,
                'benchmark_return_pct': br,
                'alpha_pct': alpha,
                'win_rate_pct': risk.get('win_rate_pct', 0),
                'profit_loss_ratio': risk.get('profit_loss_ratio', 0),
                'max_drawdown_pct': risk.get('max_drawdown_pct', 0),
                'sharpe_ratio': risk.get('sharpe_ratio', 0),
                'total_trades': trades.get('total_trades', 0),
                'elapsed_seconds': elapsed
            }
        }, f, default=str, indent=2, ensure_ascii=False)
    
    print(f"\n📁 结果已保存: {out_file}")
    return result

async def main():
    await mongo_manager.initialize()
    result = await run_optimization_a1()
    
    if result:
        print("\n🎯 优化A1测试完成")
        print("下一步建议:")
        print("1. 如果交易减少>20%且收益>0: ✅ 继续测试A3")
        print("2. 如果收益大幅下降: ⚠️ 测试A2（收窄涨幅范围）")
        print("3. 如果交易减少不足: ⚠️ 测试A3（综合收紧）")

if __name__ == "__main__":
    asyncio.run(main())