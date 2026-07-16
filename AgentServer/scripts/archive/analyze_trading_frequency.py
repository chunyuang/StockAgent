"""分析交易频率高的原因及优化方案"""
import json

def analyze_phase2_results():
    """分析Phase2测试结果"""
    try:
        with open('phase2_test_result.json', 'r') as f:
            data = json.load(f)
        
        params = data.get('params', {})
        summary = data.get('summary', {})
        
        print('📊 Phase2交易频率分析')
        print('=' * 60)
        
        # 基础信息
        start_date = params.get('start_date', '20260105')
        end_date = params.get('end_date', '20260320')
        total_trades = summary.get('total_trades', 0)
        
        # 计算交易日数量（简化估算）
        # 20260105到20260320约49个交易日
        trading_days = 49
        daily_trades = total_trades / trading_days
        
        print(f'测试区间: {start_date} ~ {end_date}')
        print(f'交易日数: {trading_days}天')
        print(f'总交易笔数: {total_trades}笔')
        print(f'日均交易: {daily_trades:.1f}笔/天')
        
        # 分析策略参数
        print('\n🔍 策略参数分析:')
        selected_strategies = params.get('selected_strategies', [])
        for strategy in selected_strategies:
            if strategy.get('id') == 'halfway_chase':
                print(f'  策略: {strategy.get("name")}')
                strategy_params = strategy.get('params', {})
                print(f'    min_volume_ratio: {strategy_params.get("min_volume_ratio", 1.0)}')
                print(f'    min_rise_pct: {strategy_params.get("min_rise_pct", 0.02)} (2%)')
                print(f'    max_rise_pct: {strategy_params.get("max_rise_pct", 0.05)} (5%)')
        
        # 全局参数
        print('\n🔍 全局参数分析:')
        global_params = params.get('params', {})
        print(f'   单票最大仓位: {global_params.get("max_position_per_stock", 0.2)*100}%')
        print(f'   总仓位上限: {global_params.get("max_position", 0.7)*100}%')
        print(f'   止损比例: {global_params.get("stop_loss_pct", 0.03)*100}%')
        print(f'   止盈比例: {global_params.get("take_profit_pct", 0.07)*100}%')
        print(f'   最大持仓天数: {global_params.get("max_hold_days", 3)}天')
        
        # 分析高交易频率的原因
        print('\n🔍 高交易频率原因分析:')
        print('1. 筛选条件宽松:')
        print(f'   - 量比阈值: {strategy_params.get("min_volume_ratio", 1.0)} (较低)')
        print(f'   - 涨幅范围: {strategy_params.get("min_rise_pct", 0.02)*100}%~{strategy_params.get("max_rise_pct", 0.05)*100}% (较宽)')
        
        print('\n2. 仓位管理规则:')
        print(f'   - 单票仓位: {global_params.get("max_position_per_stock", 0.2)*100}% (可分散到多只股票)')
        print(f'   - 最大持仓天数: {global_params.get("max_hold_days", 3)}天 (调仓频繁)')
        
        print('\n3. 市场环境:')
        print('   - 2026年1-3月市场活跃')
        print('   - 新因子条件捕捉更多机会')
        
        # 优化建议
        print('\n🎯 优化建议:')
        print('=' * 60)
        
        print('方案A: 收紧筛选条件')
        print('  1. 提高量比阈值: 1.0 → 1.5 或 2.0')
        print('  2. 收窄涨幅范围: 2-5% → 2-4% 或 3-5%')
        print('  3. 增加换手率要求: ≥3%')
        
        print('\n方案B: 调整仓位规则')
        print('  1. 降低单票仓位: 20% → 15%')
        print('  2. 延长持仓时间: 3天 → 5天')
        print('  3. 提高总仓位限制: 70% → 80% (减少调仓)')
        
        print('\n方案C: 组合筛选')
        print('  1. 增加市值要求: 流通市值≥100亿')
        print('  2. 增加价格要求: 股价≥10元')
        print('  3. 增加波动率要求: 振幅≤8%')
        
        print('\n🔧 建议测试顺序:')
        print('1. 方案A（收紧筛选条件）- 预计效果最明显')
        print('2. 方案B（调整仓位规则）- 平衡交易频率和收益')
        print('3. 方案C（组合筛选）- 精细化选股')
        
        return {
            'total_trades': total_trades,
            'daily_trades': daily_trades,
            'strategy_params': strategy_params,
            'global_params': global_params
        }
        
    except Exception as e:
        print(f'❌ 分析失败: {e}')
        return None

def create_optimization_plan(analysis):
    """创建优化测试计划"""
    if not analysis:
        return
    
    print('\n📋 优化测试计划')
    print('=' * 60)
    
    plans = [
        {
            'name': '优化A1: 提高量比阈值',
            'params': {
                'min_volume_ratio': 1.5,
                'min_rise_pct': 0.02,
                'max_rise_pct': 0.05
            },
            'expected_trades_reduction': '30-40%'
        },
        {
            'name': '优化A2: 收窄涨幅范围',
            'params': {
                'min_volume_ratio': 1.0,
                'min_rise_pct': 0.02,
                'max_rise_pct': 0.04
            },
            'expected_trades_reduction': '20-30%'
        },
        {
            'name': '优化A3: 综合收紧',
            'params': {
                'min_volume_ratio': 1.5,
                'min_rise_pct': 0.02,
                'max_rise_pct': 0.04
            },
            'expected_trades_reduction': '40-50%'
        },
        {
            'name': '优化B1: 降低单票仓位',
            'params': {
                'min_volume_ratio': 1.0,
                'min_rise_pct': 0.02,
                'max_rise_pct': 0.05,
                'max_position_per_stock': 0.15
            },
            'expected_trades_reduction': '25-35%'
        },
        {
            'name': '优化B2: 延长持仓时间',
            'params': {
                'min_volume_ratio': 1.0,
                'min_rise_pct': 0.02,
                'max_rise_pct': 0.05,
                'max_hold_days': 5
            },
            'expected_trades_reduction': '40-50%'
        }
    ]
    
    print('序号 | 优化方案 | 关键参数调整 | 预期交易减少')
    print('----|----------|-------------|------------')
    
    for i, plan in enumerate(plans, 1):
        params = plan['params']
        param_str = []
        
        if 'min_volume_ratio' in params:
            param_str.append(f'量比≥{params["min_volume_ratio"]}')
        if 'max_rise_pct' in params:
            param_str.append(f'涨幅≤{params["max_rise_pct"]*100}%')
        if 'max_position_per_stock' in params:
            param_str.append(f'单票仓位{params["max_position_per_stock"]*100}%')
        if 'max_hold_days' in params:
            param_str.append(f'持仓{params["max_hold_days"]}天')
        
        print(f'{i:2d} | {plan["name"]} | {", ".join(param_str)} | {plan["expected_trades_reduction"]}')
    
    print('\n🎯 建议执行顺序:')
    print('1. 优化A1 (提高量比阈值) - 简单有效')
    print('2. 优化A3 (综合收紧) - 平衡效果')
    print('3. 优化B2 (延长持仓时间) - 降低调仓频率')

if __name__ == "__main__":
    analysis = analyze_phase2_results()
    if analysis:
        create_optimization_plan(analysis)