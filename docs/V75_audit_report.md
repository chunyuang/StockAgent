# V75 回测模块审查报告

## 审查范围
- portfolio_backtest.py (4667行) - 逐行审查
- sell_signal_checker.py (875行) - 重点审查
- factor_engine.py (745行) - 重点审查
- factor_quality_checker.py (231行) - 完整审查
- strategy_defaults.py (210行) - 完整审查

## 基线（V74, 3个月 20260105-20260511）
| 指标 | 值 |
|------|-----|
| 总收益 | 434.01% |
| 最大回撤 | 4.87% |
| 夏普比率 | 13.61 |
| 胜率 | 75.5% |
| 交易笔数 | 204 |

## 发现的问题

### P0级（影响回测正确性）

#### P0-1: 首板打板hit_probability_slow与strategy_defaults不一致
- **文件**: portfolio_backtest.py L4216
- **问题**: `_apply_limit_up_hit_probability`中fallback值为`0.45`，但strategy_defaults.py中`hit_probability_slow`为`0.55`
- **影响**: 当_strategy_params无首板打板参数时（如通过API直接调用），fallback为0.45而非0.55
- **修复**: 使用_param_or_default或直接从STRATEGY_CONFIGS读取

#### P0-2: _build_run_result中strategy_results.total_return语义混乱
- **文件**: portfolio_backtest.py L3089
- **问题**: strategy_results[sname]['total_return'] = sum(profit_pct)，这是单笔盈亏%之和而非策略级真实收益率
- **影响**: 龙头低吸82笔，total_return=672.82%看起来是6倍收益，但实际是82笔profit_pct之和
- **修复**: 保留cumulative_profit_pct(明确语义)，total_return改为策略级真实收益率(按策略持仓市值计算)

#### P0-3: _record_daily_net_value中停牌折价可能导致负持仓市值
- **文件**: portfolio_backtest.py L761-780
- **问题**: 停牌超过3天的股票每天-1%折价(0.99^N)，极端情况下折价可能使市值估算过低
- **影响**: 长期停牌股（如停牌30天）折价0.99^27=0.76，可能导致净值曲线失真
- **修复**: 添加折价下限(最低0.7=30%折价)

### P1级（影响代码质量/可维护性）

#### P1-1: _print_single_strategy_filtering中大量重复的参数fallback逻辑
- **文件**: portfolio_backtest.py L620-740
- **问题**: 半路追涨/首板打板/涨停开板/龙头低吸/跌停翘板各有一段独立的参数读取+fallback代码
- **影响**: 与strategy_defaults.py的定义可能不同步（如min_turnover_rate单位）
- **修复**: 统一使用_param_or_default，从strategy_defaults动态读取

#### P1-2: _rebalance方法中减仓检查的止损检查重复
- **文件**: portfolio_backtest.py L4160-4190
- **问题**: 减仓股的止损/冲高回落检查逻辑与sell_codes的检查逻辑完全相同，代码重复
- **影响**: 逻辑变更时需同步两处，易遗漏
- **修复**: 提取为_check_sell_signals_for_code方法

#### P1-3: 情绪评分缓存复用可能导致非调仓日市场环境判断滞后
- **文件**: portfolio_backtest.py L1093-1103
- **问题**: 非调仓日直接复用上一次调仓日的情绪评分，但如果中间有极端行情（如暴跌），非调仓日的强制空仓判断会滞后
- **影响**: 极端行情下非调仓日止损可能不及时
- **修复**: 非调仓日也检查强制空仓条件（但不做选股），缓存仅用于仓位系数

#### P1-4: _get_prices每日缓存效率可优化
- **文件**: portfolio_backtest.py L3398
- **问题**: 同一天多次调用_get_prices时，第二次会检查缓存中已有的和缺失的，但缺失的会重新查MongoDB
- **影响**: _get_prices平均每天被调用3-4次，第二次有部分缓存但仍有1-2次小查询
- **修复**: 已有缓存时直接返回（全部命中时不查DB），缺失时批量补充到缓存

### P2级（体验/优化/文档）

#### P2-1: 日志输出过于冗长
- **问题**: 每日日志约40-60行，2年回测日志总量约50万行
- **修复**: 添加日志级别控制，关键信息(INFO)+详细信息(DEBUG)

#### P2-2: 回测结果中缺少关键风险指标
- **问题**: 缺少最大连续亏损天数、最大单日亏损%、单笔最大亏损金额
- **修复**: 在strategy_results中添加这些指标

#### P2-3: 月度收益计算在最后一个月可能有精度问题
- **问题**: 最后一月直接用nv变量（循环外），如果循环为空则nv未定义
- **修复**: 使用net_value_series[-1]替代循环外nv变量

---
*审查时间: 2026-05-28*
*审查人: AI Agent*
