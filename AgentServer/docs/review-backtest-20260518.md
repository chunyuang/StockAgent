# 回测模块全面审查报告 — 2026-05-18

## 审查范围
- 后端: ultra_short.py, portfolio_backtest.py, validator, models, API路由
- 前端: UltraShortBacktestViewV2.vue, BacktestResultPanel.vue, BacktestHistoryPanel.vue, API层

## 审查方式
- 代码审查 + 实际回测验证(2策略组合: 半路追涨+跌停翘板)

---

## 🔴 P0 - 必须修复

### P0-1: NV Series归一化数据不一致
- **现象**: net_value_series返回归一化值(net_value=1.0~1.148), 但BacktestResultPanel注释说"绝对金额需÷initial_cash归一化"
- **影响**: 前端再次归一化导致净值起始为0.000001(1.0/1000000), 图表完全错误
- **根因**: ultra_short.py返回时, 部分字段来自perf_dict用归一化值, 部分从result顶层取的是绝对金额
- **验证**: 上述回测结果 nvs[0].net_value=1.0(已归一化), 但前端注释写"绝对金额988861"
- **修复**: 统一为归一化值(1.0起始), 更新前端注释和计算逻辑

### P0-2: daily_profit单位不一致
- **现象**: 回测返回daily_profit=-0.0438(归一化小数), 前端按"绝对金额÷initial_cash×100"处理
- **影响**: 日收益图Y轴范围0.0000001级别, 图表不可用
- **修复**: 前端确认daily_profit已为归一化小数, 直接×100显示%

### P0-3: drawdown_series单位不一致
- **现象**: 回测返回drawdown=0.0368(小数), 前端注释说"drawdown是小数需×100"
- **当前状态**: 前端已×100, 但实际数据已是百分比形式(如0.0368=3.68%)
- **验证**: 需确认引擎返回的drawdown是0.0368(小数)还是3.68(百分比)
- **临时验证**: 上述结果drawdown=0.0368, 如果×100=3.68%, 与max_drawdown=8.0%数量级一致, ×100正确

### P0-4: 前端WebSocket回退轮询的status API路径错误
- **现象**: 前端onerror回退调用 backtestApi.getBacktestStatus(), 请求 /backtest/status/{id}
- **问题**: 正常流程也请求同一API, 而ultra-short的status端点挂载在/backtest下(不在/backtest/ultra-short下)
- **状态**: 实际上目前可以工作(因为status端点在__init__.py定义, 路径正确)
- **结论**: 不是bug, 但前端UltraShortBacktestViewV2.vue不应自己构建WebSocket, 应复用通用逻辑

---

## 🟡 P1 - 重要修复

### P1-1: 回测历史API task_type过滤失效
- **现象**: ultra-short/history查询条件 task_type="ultra_short", 但提交任务时未写入task_type字段
- **影响**: /backtest/ultra-short/history 可能返回空结果或遗漏记录
- **验证**: 当前显示3条历史记录, 说明MongoDB中旧记录有task_type字段, 新提交的us_33c7e4864c39可能无
- **修复**: 提交任务时写入 task_type: "ultra_short"

### P1-2: 执行耗时140秒过长
- **现象**: 2策略141个交易日回测耗时140秒(约1秒/天)
- **瓶颈**: portfolio_backtest.py中每个交易日多次MongoDB查询(涨跌停聚合+个股查询)
- **优化方向**: 批量预加载交易日数据到内存, 减少逐日查询

### P1-3: 卖出原因"other"仍有3笔
- **现象**: sell_reason_stats中other=3笔
- **根因**: 部分交易record的sell_reason/reason字段为空字符串或不匹配任何模式
- **修复**: 在portfolio_backtest.py中统一设置sell_reason

### P1-4: 月度收益图表重复
- **现象**: BacktestResultPanel中"月度收益"Tab和"月度归因"Tab都有月度收益图
- **修复**: 合并为一个Tab, 或"月度收益"显示总览, "月度归因"显示详细归因

### P1-5: 策略对比Tab雷达图max值硬编码
- **现象**: radar indicator max硬编码为50/100/5/5/20
- **问题**: 当实际值超出时图形被截断
- **修复**: 根据实际数据动态计算max

---

## 🟢 P2 - 优化建议

### P2-1: 前端页面标题V3.0过时
- 当前: "超短策略回测系统 V3.0 ✅ 专业量化版"
- 建议: 更新版本描述, 移除"2026-05-11"日期

### P2-2: KPI Strip缺少盈亏比
- 当前KPI: 累计收益/年化收益/最大回撤/夏普/胜率/交易笔数/信号数
- 缺少: 盈亏比(profit_loss_ratio) — 重要风控指标

### P2-3: 交易记录表格缺少金额列
- 当前列: 买入日/卖出日/代码/名称/策略/买入价/卖出价/收益率/持仓天数/数量/卖出原因/情绪
- 缺少: 买入金额/卖出金额/盈亏金额 — 用户最关心的

### P2-4: 深色模式下部分文字不可读
- sell-reason-bar的背景色#fafafa在深色模式下刺眼

### P2-5: 回测运行中无法取消
- 前端无取消按钮, 只能等完成
- 后端已有cancel端点

---

## ✅ 已验证正常的部分
1. 回测引擎核心逻辑: 2策略组合回测结果合理(14.78%收益, 47.5%胜率)
2. 9层筛选管道: 生效正常
3. 卖出原因统计: 6类分类工作正常
4. 参数扫描: sweep API可用
5. 历史记录: 增删改查正常
6. WebSocket/轮询: 双通道回退正常
7. 策略对比: 多策略KPI对比正常
