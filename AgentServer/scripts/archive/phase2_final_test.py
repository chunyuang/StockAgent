"""Phase2修复最终测试 - 验证收益变化"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager

async def run_phase2_test():
    """运行Phase2修复测试"""
    await mongo_manager.initialize()
    
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
    
    task_id = f"phase2_test_{int(time.time())}"
    logs = []
    
    async def push_log(tid, msg):
        logs.append(msg)
        # 只打印关键日志
        if any(k in msg for k in ['✅', '❌', '⚠️', '📊', '🎯', '策略', '选股', '候选', '调仓', '回测结果', '收益', 'Alpha']):
            print(msg)
    
    # Phase2测试参数 - 重点测试半路追涨
    params = {
        "start_date": "20260105",
        "end_date": "20260320",
        "initial_cash": 1000000,
        "period": "daily",
        "volume_threshold": 1.0,
        "stop_loss_pct": 0.03,  # 3%止损
        "take_profit_pct": 0.07,  # 7%止盈
        "max_hold_days": 3,
        "max_position_per_stock": 0.2,  # 20%单票仓位
        "liquidity_threshold": 500,  # 500万流通市值
        "max_position": 0.7,  # 70%总仓位
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
            {"id": "halfway_chase", "name": "半路追涨", "params": {"min_volume_ratio": 1.0, "min_rise_pct": 0.02, "max_rise_pct": 0.05}},
        ],
    }
    
    print("🚀 Phase2修复最终测试")
    print("=" * 60)
    print(f"时间区间: {params['start_date']}~{params['end_date']}")
    print(f"初始资金: ¥{params['initial_cash']:,.0f}")
    print(f"测试策略: 半路追涨 (Phase2修复后)")
    print(f"筛选条件: 盘中最高≥2% 且 开盘≤5% 且 量比≥1.0")
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
    print(f"📊 Phase2修复测试结果 ({elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  策略收益率:  {tr:+.2f}%")
    print(f"  基准收益率:  {br:+.2f}%")
    print(f"  Alpha:       {alpha:+.2f}%")
    print(f"  胜率:        {risk.get('win_rate_pct', 0):.1f}%")
    print(f"  盈亏比:      {risk.get('profit_loss_ratio', 0):.2f}")
    print(f"  最大回撤:    {risk.get('max_drawdown_pct', 0):.2f}%")
    print(f"  夏普:        {risk.get('sharpe_ratio', 0):.2f}")
    print(f"  交易笔数:    {trades.get('total_trades', 0)} (赢{trades.get('winning_trades',0)}/亏{trades.get('losing_trades',0)})")
    
    # 与Phase1结果对比
    print(f"\n{'='*60}")
    print("📈 与Phase1结果对比")
    print(f"{'='*60}")
    print("Phase1 (修复前):")
    print("  收益: +61.4% | 胜率: 70% | 回撤: 1.80% | 夏普: 12.2 | 交易: 2886笔")
    print(f"\nPhase2 (修复后):")
    print(f"  收益: {tr:+.2f}% | 胜率: {risk.get('win_rate_pct', 0):.1f}% | 回撤: {risk.get('max_drawdown_pct', 0):.2f}% | 夏普: {risk.get('sharpe_ratio', 0):.2f} | 交易: {trades.get('total_trades', 0)}笔")
    
    # 分析变化
    print(f"\n{'='*60}")
    print("🔍 修复效果分析")
    print(f"{'='*60}")
    
    if tr > 0:
        print(f"✅ 策略仍保持正收益: {tr:+.2f}%")
        if tr < 61.4:
            print(f"⚠️  收益下降: {61.4-tr:.1f}个百分点 (消除未来函数的正常代价)")
        else:
            print(f"🎉 收益提升: {tr-61.4:.1f}个百分点")
    else:
        print(f"❌ 策略负收益: {tr:+.2f}% (需要进一步优化)")
    
    if risk.get('win_rate_pct', 0) >= 60:
        print(f"✅ 胜率合理: {risk.get('win_rate_pct', 0):.1f}%")
    else:
        print(f"⚠️  胜率偏低: {risk.get('win_rate_pct', 0):.1f}% (可能需要调整参数)")
    
    if risk.get('max_drawdown_pct', 0) < 5:
        print(f"✅ 回撤控制良好: {risk.get('max_drawdown_pct', 0):.2f}%")
    else:
        print(f"⚠️  回撤较大: {risk.get('max_drawdown_pct', 0):.2f}%")
    
    # 保存结果
    out_file = os.path.join(BASE, 'phase2_test_result.json')
    with open(out_file, 'w') as f:
        json.dump({
            'phase': 'phase2_final',
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
    result = await run_phase2_test()
    
    if result:
        print("\n🎯 Phase2修复测试完成")
        print("下一步建议:")
        print("1. 如果收益>0且胜率>60%: ✅ 修复成功，可以继续")
        print("2. 如果收益<0或胜率<50%: ⚠️ 需要调整策略参数")
        print("3. 检查其他策略的类似问题")

if __name__ == "__main__":
    asyncio.run(main())