# 回测V13审查报告 - 全面代码审查+优化

## 基线(V12): 收益23.86% 夏普4.42 回撤3.72% 胜率49.09% 盈亏比2.11 交易110笔 耗时17.9s

---

## 已修复问题

### P0-1: `_process_non_rebalance_day`中`_prices_for_display`变量作用域泄漏
- **文件**: portfolio_backtest.py
- **问题**: holdings为空时不进入if/else分支，后续引用`_prices_for_display`会NameError
- **修复**: 方法开头初始化`_prices_for_display = {}`
- **验证**: ✅ 回测通过

### P0-2: 调仓日冲高回落/利润保护检查中`_close_p`变量未定义
- **文件**: portfolio_backtest.py
- **问题**: 半路追涨分支引用`_close_p`，但该变量只在跌停翘板分支赋值
- **修复**: 循环前初始化`_close_p = p.get('close', 0)`，半路追涨分支也更新`_close_p`
- **验证**: ✅ 回测通过

### P0-4: `factor_engine.py`中pre_close为0时intraday因子产生NaN
- **文件**: factor_engine.py
- **问题**: pre_close=0→除法产生NaN→该股在半路追涨条件筛选时被误杀
- **修复**: 计算后用fillna(0)填充NaN
- **影响**: pre_close=0的股票intraday_max_rise_pct=0→无法通过>=3%过滤→正确行为
- **验证**: ✅ 回测通过

### P1-1: `enable_*`参数读取5层fallback简化
- **文件**: ultra_short.py
- **问题**: 5层嵌套fallback(params→req_params→req_params.params→默认值)
- **修复**: 简化为2层(params顶层→默认值)
- **验证**: ✅ 回测通过

### P1-5: ALL_STRATEGIES包含未启用策略
- **文件**: strategy_defaults.py
- **问题**: 涨停开板(enabled=False)被包含在兜底列表中
- **修复**: `if cfg.get("enabled", True)`过滤
- **验证**: ✅ 回测通过

### P1-6: 跌停翘板circ_mv硬编码200000
- **文件**: portfolio_backtest.py
- **问题**: 硬编码20亿门槛，参数min_circulation_market_cap未生效
- **修复**: 从params读取并×10000转换
- **验证**: ✅ 默认值20亿，与硬编码一致

### P1-8: daily_profit格式不一致
- **文件**: portfolio_backtest.py
- **问题**: result顶层归一化小数，metrics.positions绝对值
- **修复**: 统一为归一化小数格式
- **验证**: ✅ 三路径一致(顶层/metrics/nvs)

### P2-4: GC频率5天→10天
- **文件**: portfolio_backtest.py
- **修复**: idx%5→idx%10，51天回测10次GC→5次

### 日志修复: 非调仓日显示"调仓日无交易"
- **文件**: portfolio_backtest.py
- **问题**: `_process_non_rebalance_day`日志永远显示"调仓日无交易"
- **修复**: 根据trade_date是否在rebalance_set中区分日志

### NameError守卫清理
- **文件**: portfolio_backtest.py
- **问题**: P0-1修复后`try: _prices_for_display / except NameError`过时
- **修复**: 改为`if not _prices_for_display`

### R1: 半路追涨收盘确认条件注释优化
- **文件**: portfolio_backtest.py
- **说明**: 增加阳线确认(close>=open)的注释说明，未改变实际逻辑

---

## 验证结果

| 指标 | V12基线 | V13修复后 | 变化 |
|------|---------|-----------|------|
| 收益 | 23.86% | 23.86% | = |
| 夏普 | 4.42 | 4.42 | = |
| 回撤 | 3.72% | 3.72% | = |
| 胜率 | 49.09% | 49.09% | = |
| 盈亏比 | 2.11 | 2.11 | = |
| 交易笔数 | 110 | 110 | = |
| 信号数 | 113 | 113 | = |
| 耗时 | 17.9s | 17.7s | -1.1% |

4策略组合: 34.24%收益 5.26夏普 4.18%回撤 56.92%胜率

---

## 审查范围

### 后端(全量)
- ✅ portfolio_backtest.py (3968行) - 核心引擎
- ✅ ultra_short.py (673行引擎) - 参数组装
- ✅ factor_engine.py - 因子计算
- ✅ strategy_defaults.py - 策略参数
- ✅ API层 ultra_short.py (637行) - 路由+参数映射
- ✅ models.py (283行) - Pydantic模型
- ✅ defaults.py (93行) - 默认配置

### 前端(全量)
- ✅ UltraShortBacktestViewV2.vue (959行) - 主页面
- ✅ BacktestResultPanel.vue (1117行) - 结果面板
- ✅ BacktestHistoryPanel.vue (549行) - 历史面板
- ✅ BacktestSummaryTable.vue (171行) - 摘要表
- ✅ AnsiLogPanel.vue (585行) - 日志面板

---

## Git
- Commit 2b3e3c3: 第一轮修复(P0-1/P0-2/P0-4/P1-1/P1-5/P1-6/P1-8/P2-4/R1)
- Commit 8be05ac: 第二轮修复(NameError守卫清理/日志区分)
