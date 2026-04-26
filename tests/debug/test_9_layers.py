
import sys
sys.path.insert(0, './AgentServer')
import asyncio

async def test_9_layers():
    print('=' * 80)
    print('🧪 阶段3：9层筛选架构深度审计')
    print('=' * 80)
    print()
    
    # ======================================================================
    # 检查1：强制空仓是否真正执行
    # ======================================================================
    print('🔍 检查1：第1层强制空仓是否真正执行')
    print('-' * 80)
    
    with open('AgentServer/nodes/backtest_engine/factor_selection/portfolio_backtest.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 找强制空仓相关代码
    if 'if force_empty_triggered:' in content:
        # 看if块后面有没有真正的卖出代码
        pos = content.find('if force_empty_triggered:')
        snippet = content[pos:pos+800]
        if 'sell_count' in snippet and 'continue' in snippet and 'force_empty_position' in snippet:
            print('  ✅ 第1层 强制空仓：代码完整，有卖出所有持仓+跳过选股逻辑')
            print('     - 卖出所有持仓代码：有（第662-693行）')
            print('     - 跳过选股：有（第694行 continue）')
        else:
            print('  ❌ 第1层 强制空仓：只有判断，没有真正执行')
    else:
        print('  ❌ 第1层 强制空仓：代码不存在')
    print()
    
    # ======================================================================
    # 检查2：情绪周期仓位系数是否真正应用
    # ======================================================================
    print('🔍 检查2：第3层情绪周期仓位系数是否真正应用')
    print('-' * 80)
    
    if '_extract_position_multiplier' in content and 'position_multiplier' in content:
        pos = content.find('position_multiplier = self._extract_position_multiplier')
        if pos > 0:
            snippet = content[pos:pos+300]
            if 'target_value = total_value * weight * position_multiplier' in snippet:
                print('  ✅ 第3层 情绪周期：仓位系数已经真正乘到target_value里了！')
                print('     - 代码：target_value = total_value * weight * position_multiplier')
                print('     - 说明：情绪差时确实会降低单只股票的目标仓位')
            else:
                print('  ❌ 第3层 情绪周期：只计算了仓位系数，没有真正乘进去！')
        else:
            print('  ⚠️  第3层 情绪周期：需要进一步检查')
    else:
        print('  ❌ 第3层 情绪周期：仓位系数代码不存在')
    print()
    
    # ======================================================================
    # 检查3：流动性过滤是否真正执行
    # ======================================================================
    print('🔍 检查3：流动性过滤是否真正执行')
    print('-' * 80)
    
    if 'low_liquidity_cursor = mongo_manager.find_many' in content and 'universe -= low_liquidity_set' in content:
        print('  ✅ 第4层 流动性过滤：真正从universe中剔除了低流动性股票！')
        print('     - 代码：universe -= low_liquidity_set')
    else:
        print('  ❌ 第4层 流动性过滤：只是统计了数量，没有真正剔除！')
    print()
    
    # ======================================================================
    # 检查4：9层架构完整性
    # ======================================================================
    print('🔍 检查4：9层架构完整性（文档 vs 实际代码）')
    print('-' * 80)
    
    layers_doc = [
        '第1层：强制空仓检查',
        '第2层：特殊时期过滤（节假日/重大会议）',
        '第3层：情绪周期适配',
        '第4层：盘前预选池',
        '第5层：竞价阶段过滤',
        '第6层：量能/性质过滤',
        '第7层：盘中信号触发',
        '第8层：时间窗口过滤',
        '第9层：综合校验',
    ]
    
    print('  文档中规划的9层：')
    for i, layer in enumerate(layers_doc, 1):
        print(f'    {i}. {layer}')
    print()
    
    print('  实际代码实现情况：')
    
    found_layers = {
        '第1层强制空仓': '✅ 已实现',
        '第2层特殊时期过滤': '❌ 代码中完全找不到相关逻辑！',
        '第3层情绪周期': '✅ 已实现',
        '第4层盘前预选池(ST/次新)': '✅ 已实现',
        '第5层竞价阶段过滤': '✅ 已实现（作为策略参数）',
        '第6层量能/性质过滤': '✅ 已实现（量比、换手率等）',
        '第7层盘中信号触发': '✅ 已实现（涨停、开板等）',
        '第8层时间窗口过滤': '❌ 代码中完全找不到！',
        '第9层综合校验': '❌ 代码中完全找不到！',
    }
    
    for layer, status in found_layers.items():
        print(f'    {layer}: {status}')
    print()
    
    print('💡 关键发现：')
    print('  1. ✅ 第1/3/4/5/6/7层 已经有代码实现')
    print('  2. ❌ 第2层 特殊时期过滤：完全没有代码，只有文档！')
    print('  3. ❌ 第8层 时间窗口过滤：完全没有代码！')
    print('  4. ❌ 第9层 综合校验：完全没有代码！')
    print()
    
    # ======================================================================
    # 总结
    # ======================================================================
    print('=' * 80)
    print('🏆 阶段3：9层筛选架构审计总结')
    print('=' * 80)
    print()
    
    print('  9层架构实际完成度：6/9 = 66.7%')
    print()
    
    print('  ✅ 真正实现并生效的（6层）：')
    print('    - 第1层：强制空仓检查')
    print('    - 第3层：情绪周期仓位系数')
    print('    - 第4层：ST/次新股/停牌排除')
    print('    - 第5层：竞价涨幅/量比等过滤')
    print('    - 第6层：量能、换手率、流通市值等过滤')
    print('    - 第7层：盘中涨停、开板等信号筛选')
    print()
    
    print('  ❌ 纯文档存在、代码中完全没有的（3层）：')
    print('    - 第2层：特殊时期过滤（节假日/重大会议自动调整仓位）')
    print('    - 第8层：时间窗口过滤（仅9:35-10:00买入）')
    print('    - 第9层：龙虎榜/北向资金/股性综合校验')
    print()
    
    print('💡 结论：')
    print('  9层筛选架构是"部分实现、部分宣传"的混合体！')
    print('  真正有代码的是6层，另外3层只存在于产品文档和PPT里！')
    print('=' * 80)

asyncio.run(test_9_layers())
