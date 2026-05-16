# portfolio_backtest.py 拆分方案

## 当前状态
- 文件行数: 3718行
- 类数量: 3个（RebalanceRecord, PortfolioSnapshot, PortfolioBacktester）
- 方法数量: 30+个

## 拆分目标
- 提升可维护性
- 降低单文件复杂度
- 保持功能完整性
- 避免破坏现有功能

## 拆分方案

### 1. 数据模型层 (models.py)
**位置**: `factor_selection/models.py`（已存在，需扩展）

**内容**:
- RebalanceRecord (L61-74)
- PortfolioSnapshot (L76-85)
- 新增: RunState（运行时状态dict的数据类）

**行数**: ~50行

### 2. 日志输出层 (backtest_logger.py)
**位置**: `factor_selection/backtest_logger.py`（新建）

**内容**:
- _print_daily_header (L142-148)
- _print_market_environment (L149-274)
- _print_single_strategy_filtering (L275-465)
- _print_stock_pool_and_cleaning (L466-476)
- _print_daily_summary (L520-530)

**行数**: ~400行

### 3. 策略筛选层 (strategy_filter.py)
**位置**: `factor_selection/strategy_filter.py`（新建）

**内容**:
- _build_strategy_filter_conditions (L3046-3205)
- _get_strategy_for_stock (L2963-2969)
- 策略参数验证逻辑

**行数**: ~200行

### 4. 价格计算层 (price_calculator.py)
**位置**: `factor_selection/price_calculator.py`（新建）

**内容**:
- _get_prices (L2687-2821)
- _get_limit_pct (L2911-2924)
- _get_limit_up_price (L2925-2962)
- _get_buy_price_for_stock (L2970-3023)
- _get_stock_names (L3683-3718)

**行数**: ~200行

### 5. 风控逻辑层 (risk_manager.py)
**位置**: `factor_selection/risk_manager.py`（新建）

**内容**:
- _get_sl_tp_for_code (L3206-3218)
- _get_slippage_for_code (L3219-3227)
- 止损止盈检查逻辑（从_rebalance和非调仓日处理中提取）
- 强制空仓逻辑

**行数**: ~300行

### 6. 调仓执行层 (rebalance_executor.py)
**位置**: `factor_selection/rebalance_executor.py`（新建）

**内容**:
- _rebalance (L3228-3682) - **最大的方法，453行**
- _compute_weights (L2822-2910)
- _extract_position_multiplier (L3024-3045)

**行数**: ~500行

### 7. 结果计算层 (result_builder.py)
**位置**: `factor_selection/result_builder.py`（新建）

**内容**:
- _build_run_result (L1920-2620) - **700行**
- _record_daily_net_value (L477-519)

**行数**: ~700行

### 8. 主引擎 (portfolio_backtest.py)
**位置**: `factor_selection/portfolio_backtest.py`（保留）

**内容**:
- PortfolioBacktester类主框架
- run (L531-562)
- _run_impl (L563-646)
- _init_run_config (L647-1008)
- _process_rebalance_day (L1009-1719)
- _process_non_rebalance_day (L1720-1919)
- _load_benchmark_data (L2621-2686)

**行数**: ~1500行（从3718行减少到1500行）

## 拆分步骤

### Phase 1: 准备工作
1. 创建新文件
2. 定义接口和依赖关系
3. 添加必要的import

### Phase 2: 拆分数据模型
1. 将RebalanceRecord/PortfolioSnapshot移到models.py
2. 创建RunState数据类
3. 更新portfolio_backtest.py的import

### Phase 3: 拆分日志输出
1. 创建BacktestLogger类
2. 移动所有_print方法
3. 在PortfolioBacktester中注入logger实例

### Phase 4: 拆分策略筛选
1. 创建StrategyFilter类
2. 移动_build_strategy_filter_conditions
3. 保持策略配置的单一来源

### Phase 5: 拆分价格计算
1. 创建PriceCalculator类
2. 移动所有价格相关方法
3. 处理依赖关系（如_last_valid_price）

### Phase 6: 拆分风控逻辑
1. 创建RiskManager类
2. 移动止损止盈逻辑
3. 提取强制空仓逻辑

### Phase 7: 拆分调仓执行
1. 创建RebalanceExecutor类
2. 移动_rebalance方法
3. 处理复杂的依赖关系

### Phase 8: 拆分结果计算
1. 创建ResultBuilder类
2. 移动_build_run_result
3. 处理绩效指标计算

### Phase 9: 清理和测试
1. 删除portfolio_backtest.py中的冗余代码
2. 更新所有import
3. 运行回测测试验证功能

## 拆分原则

1. **渐进式拆分**: 每次拆分一个模块，立即测试验证
2. **保持接口**: 拆分后保持原有方法签名，避免破坏调用方
3. **依赖注入**: 使用依赖注入而非硬编码依赖
4. **单一职责**: 每个模块只负责一个功能领域
5. **最小改动**: 优先拆分独立性强的方法，避免复杂的依赖关系

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 拆分破坏功能 | 高 | 每次拆分后立即测试 |
| 依赖关系复杂 | 中 | 使用依赖注入解耦 |
| import混乱 | 低 | 明确模块边界 |
| 性能下降 | 低 | 避免过度拆分 |

## 预期收益

- 可维护性提升: 3718行→1500行（主文件）
- 代码复用: 独立模块可被其他组件使用
- 测试便利: 独立模块更容易编写单元测试
- 调试效率: 问题定位更快速

## 时间估算

- Phase 1-2: 1小时
- Phase 3-5: 2小时
- Phase 6-8: 3小时
- Phase 9: 1小时
- **总计**: 7小时

## 建议

鉴于拆分工作量较大且风险较高，建议：
1. **优先级**: 中优先级（非紧急）
2. **时机**: 在添加新功能前进行拆分
3. **方式**: 渐进式拆分，每次提交一个Phase
4. **测试**: 拆分前先添加单元测试覆盖核心逻辑

**当前建议**: 先完成其他优化项，待添加单元测试后再进行拆分。