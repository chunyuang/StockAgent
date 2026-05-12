# 超短量化实盘系统审查报告

> 审查时间: 2026-05-12 17:50  
> 审查范围: Scanner + Broker + Scheduler + 前端 + 数据源  
> 状态: 初具雏形, 核心链路可跑, 但距实盘安全有显著差距

---

## 一、系统现状概览

### 已完成 ✅
| 模块 | 功能 | 质量 |
|------|------|------|
| Scanner | scan_once全链路(行情→因子→策略→信号→下单) | 🔶 可跑, 有隐患 |
| SimulatedBroker | 下单/撮合/涨跌停拒绝/T+1/动态滑点 | 🟢 较完整 |
| SimulatedBroker | 持仓持久化MongoDB | 🔶 有重复写入bug |
| 必盈适配器 | 涨停池/跌停池/炸板池/实时行情 | 🟢 稳定 |
| 前端 | 实时扫描/策略配置/数据源/手动交易 | 🔶 API刚修好 |
| 熔断器 | 日回撤5%/连亏3次暂停 | 🟡 基本可用 |
| PositionSizer | 仓位管理(40%/25%/15%三档) | 🔶 逻辑在但粗糙 |

### 核心链路 (一次完整扫描)
```
scan_once:
  1. _fetch_realtime_batch()  → 必盈API(涨停池+跌停池+炸板池+逐只)
  2. _merge_factors()         → 日级因子(MongoDB) + 实时因子合并
  3. _apply_strategies()      → 4策略筛选(复用回测逻辑)
  4. _detect_anomalies()      → 异动检测(3种类型)
  5. _update_signals()        → 去重 + 推送 + 执行买入
  6. _check_positions()       → 止损止盈检查 → 卖出
```

---

## 二、🔴 P0级问题 (实盘前必须修复, 否则亏钱)

### P0-1: 止损参数单位不一致 (会算错止损线)
```
strategy_defaults.py:  stop_loss_pct = 0.03 (小数, 即3%)
_check_positions:      stop_loss_pct = -risk.get("stop_loss_pct", 0.03) * 100
                        = -0.03 * 100 = -3%  ← 正确

但如果前端传的是 stop_loss_pct = 3 (百分比形式, 用户直觉):
  -3 * 100 = -300% ← 永远不会触发止损!
  
反过来如果某处传了 5.0 (回测的默认值):
  -5.0 * 100 = -500% ← 也不会触发!
```
**风险**: 止损完全失效, 亏损无下限  
**修复**: 统一为小数(0.03), 全系统强制转换

### P0-2: 持仓持久化重复写入
```
save_state: delete_many + insert_many
但如果scan_once每5分钟保存一次, 且_scan_loop和_check_positions_quick
都可能触发save_state → 并发写入导致重复
```
**风险**: 数据不一致, 账户金额算错  
**修复**: 用upsert替代delete+insert, 加save_state节流(30秒内不重复保存)

### P0-3: scan_once不保存状态
当前`_scan_loop`每5分钟`scan_once`, 但只在`_check_positions_quick`后`save_state`。
如果进程崩溃, 中间的订单和持仓状态丢失。  
**修复**: 每次`_execute_signals`成功后立即`save_state`

### P0-4: 竞价预选用的是**昨日**涨停池, 没有**今日**竞价行情
```python
_premarket_auction:
  yesterday_limit_ups = await biying.get_limit_up_pool(yesterday)  # 昨日数据
  # 缺少: 今日9:15-9:25集合竞价的实时价格/量/匹配度
```
**风险**: 竞价预选形同虚设, 无法判断今日竞价是否继续强势  
**修复**: 必盈有集合竞价接口, 需要对接; 或用实时行情中pct_chg>0的过滤

### P0-5: 信号去重逻辑有缺陷 — 只按ts_code去重
```python
_update_signals:
  existing_codes = {s.ts_code for s in self._active_signals}
```
如果同一只股在不同时间被不同策略选中, 只保留第一个策略的信号。  
例如: 000001先被"半路追涨"选中, 后又被"龙头低吸"选中 → 第二个被丢弃  
**修复**: 按 `ts_code + strategy` 去重, 不同策略的信号可以共存

### P0-6: 异动检测只检测, 不执行
```python
anomaly_signals = await self._detect_anomalies(realtime_data)
new_signals.extend(anomaly_signals)  # 加入信号列表
# → _update_signals → _execute_signals 会执行
```
但异动信号的`price=0`(没有从realtime_data提取), 导致_execute_signals跳过:
```python
if sig.price <= 0:
    continue  # ← 异动信号全被跳过!
```
**风险**: 异动检测写了等于没写  
**修复**: 异动信号必须带price

---

## 三、🟡 P1级问题 (实盘安全增强, 不修可能出事故)

### P1-1: 没有盘后结算自动触发
`daily_settlement`解锁T+1, 但目前没有定时触发机制。  
Scanner的`_scan_loop`只管盘中扫描, 收盘后就停了。  
**修复**: DailyScheduler的postmarket阶段自动调用`broker.daily_settlement()`

### P1-2: DailyScheduler和Scanner职责重叠, 状态不同步
- Scheduler有自己的`_positions`字典(从Scanner._broker抄的)
- Scheduler的`_fetch_realtime_data`还直接用必盈(绕过Scanner)
- 两者同时运行会导致: Scheduler检查止损和Scanner检查止损**重复执行**

**修复**: Scheduler盘中和盘后只调度, 所有交易逻辑走Scanner

### P1-3: ST股涨跌停比例未处理
```python
_calc_limit_prices:
  # TODO: 后续传入is_st标志  ← ST股应该是±5%
```
**风险**: ST股涨跌停价算错, 可能涨停价买入(实际已超涨停)被拒

### P1-4: 缺少停牌/退市检查
Broker有`_suspended`列表但从不更新。停牌股不会被跳过。  
**修复**: 盘前加载当日停牌列表(东方财富有API)

### P1-5: 科创板最小200股, 但PositionSizer算出的数量可能<200
```python
if sig.ts_code.startswith('688'):
    shares = int(max_amount / sig.price / 200) * 200  # ← 对
```
但如果`max_amount / sig.price < 200`, 结果是0, 信号被跳过。  
应该给出明确提示"科创板资金不足200股"。

### P1-6: 无订单超时/废单处理
限价单如果一直不成交, 没有超时撤销机制。  
当前全是市价单所以问题不大, 但如果未来加限价单就会堵住。

### P1-7: 前端5秒轮询在非交易时间浪费API
```javascript
refreshTimer = setInterval(() => {
  if (!autoRefresh.value || activeTab.value !== 'scanner') return
  fetchScanner()
}, 5000)
```
收盘后还在5秒一次请求。  
**修复**: 检测交易时间(9:30-15:00), 非交易时间30秒一次

---

## 四、🟢 P2级问题 (体验优化, 不影响核心功能)

### P2-1: 前端信号列表不支持排序/筛选
45个信号一股脑堆出来, 用户看不过来。  
**优化**: 按策略/涨跌幅/连板数筛选 + 按置信度排序

### P2-2: 没有历史交易记录查询
`_timeline`只存当天的, 次日清空。没有交易日志持久化。  
已有`broker_orders`MongoDB集合, 前端没展示。

### P2-3: 涨停池数据没展示在前端
必盈返回的涨停池包含封板资金/连板数/炸板次数, 这些是非常有价值的信息。  
前端应该有一个"今日涨停"板块。

### P2-4: 手动交易缺少价格确认
市价单看不到预估价格, 用户不知道自己将以什么价格成交。  
**优化**: 输入代码后自动获取实时行情和五档

### P2-5: 熔断器只检查不通知
熔断触发后只打日志, 不主动通知用户。  
**修复**: Redis PubSub推送到前端 + 可选消息推送

### P2-6: 缺少盘后复盘报告
每日收盘后自动生成:
- 今日操作回顾(买卖/盈亏)
- 策略表现对比
- 持仓风险分析
- 次日关注列表

---

## 五、📊 量化专业视角的额外建议

### A. 信号质量评估
当前4策略的胜率差异巨大:
- 半路追涨: 83%胜率 → 应该重仓
- 首板打板: 39%胜率 → 应该轻仓或关闭
- 跌停翘板: 90%胜率(但样本少) → 需要更多验证

**建议**: 给每个策略一个动态权重, 根据近期胜率调整仓位比例

### B. 滑点模型过于简化
当前只有0.1%/0.3%/0.5%三档。实盘滑点受:
- 盘口深度(五档量)
- 委托量/成交量比
- 时段(开盘/尾盘滑点大)
- 个股流动性

**建议**: 用必盈五档数据计算实际冲击成本

### C. 缺少信号回测验证
实盘前的信号应该和回测信号对齐验证:
- 同一天, 同一只股, Scanner选出的信号和回测选出的信号是否一致?
- 如果不一致, 是因子差异还是参数差异?

**建议**: 加一个"信号回测验证"模式, 对比两者差异

### D. 资金管理改进
当前总仓位上限70%, 单票15%, 但没有考虑:
- 连续亏损后的仓位递减(凯利公式)
- 市场整体情绪(大盘跌时降仓)
- 个股相关性(同板块持仓叠加风险)

---

## 六、修复优先级和计划

| 编号 | 问题 | 优先级 | 预估工时 | 依赖 |
|------|------|--------|----------|------|
| P0-1 | 止损参数单位统一 | 🔴P0 | 1h | 无 |
| P0-2 | 持仓持久化upsert+节流 | 🔴P0 | 1h | 无 |
| P0-3 | execute_signals后save_state | 🔴P0 | 0.5h | P0-2 |
| P0-4 | 竞价预选加入实时行情 | 🔴P0 | 2h | 必盈API |
| P0-5 | 信号按ts_code+strategy去重 | 🔴P0 | 0.5h | 无 |
| P0-6 | 异动信号补price | 🔴P0 | 0.5h | 无 |
| P1-1 | 盘后结算自动触发 | 🟡P1 | 1h | 无 |
| P1-2 | Scheduler去重 | 🟡P1 | 2h | 无 |
| P1-3 | ST股涨跌停 | 🟡P1 | 1h | 数据 |
| P1-4 | 停牌检查 | 🟡P1 | 1h | 数据 |
| P1-7 | 前端轮询优化 | 🟡P1 | 0.5h | 无 |

**建议**: 先修P0(4-6小时), 再修P1(4-5小时), 然后做一个完整的盘中测试
