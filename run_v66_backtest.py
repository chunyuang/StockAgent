"""V66回测验证 - 4级情绪仓位 + 参数对齐"""
import asyncio, json, sys
sys.path.insert(0, '.')

async def main():
    from AgentServer.nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
    
    bt = PortfolioBacktester(
        start_date="20250101",
        end_date="20250331",
        initial_capital=1000000,
        selected_strategies=[
            {"id": "halfway_chase"},
            {"id": "first_limit_up"},
            {"id": "dragon_head"},
            {"id": "limit_down_qiao"},
        ]
    )
    result = await bt.run()
    
    # 输出结果
    print("\n" + "="*60)
    print("V66 回测结果 (2025Q1) - 4级情绪仓位 + 参数对齐")
    print("="*60)
    print(f"总收益: {result.get('total_return', 0):.2f}%")
    print(f"年化收益: {result.get('annualized_return', 0):.2f}%")
    print(f"最大回撤: {result.get('max_drawdown', 0):.2f}%")
    print(f"胜率: {result.get('win_rate', 0):.2f}%")
    print(f"夏普: {result.get('sharpe_ratio', 0):.2f}")
    print(f"索提诺: {result.get('sortino_ratio', 0):.2f}")
    print(f"卡玛: {result.get('calmar_ratio', 0):.2f}")
    print(f"盈亏比: {result.get('profit_loss_ratio', 0):.2f}")
    print(f"交易笔数: {result.get('total_trades', 0)}")
    
    # 策略分解
    strategy_results = result.get('strategy_results', {})
    if strategy_results:
        print("\n策略分解:")
        for sname, sdata in strategy_results.items():
            print(f"  {sname}: {sdata.get('total_trades',0)}笔 胜率{sdata.get('win_rate',0):.1f}% 收益{sdata.get('total_return',0):.2f}% 盈亏比{sdata.get('profit_loss_ratio',0):.2f}")
    
    # 月度收益
    monthly = result.get('monthly_returns', {})
    if monthly:
        print("\n月度收益:")
        for m, r in sorted(monthly.items()):
            print(f"  {m}: {r:.2f}%")
    
    # 与V65c对比
    print("\n" + "="*60)
    print("与V65c对比")
    print("="*60)
    v65c = {"总收益": 286.28, "最大回撤": 4.42, "夏普": 10.77, "胜率": 81.25, "盈亏比": 2.80, "交易笔数": 96}
    v66 = {"总收益": result.get('total_return',0), "最大回撤": result.get('max_drawdown',0), "夏普": result.get('sharpe_ratio',0), "胜率": result.get('win_rate',0), "盈亏比": result.get('profit_loss_ratio',0), "交易笔数": result.get('total_trades',0)}
    for k in v65c:
        diff = v66[k] - v65c[k]
        print(f"  {k}: V65c={v65c[k]} V66={v66[k]:.2f} 差值={diff:+.2f}")

if __name__ == '__main__':
    asyncio.run(main())
