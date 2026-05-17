# 实盘交易全面审查报告 V3 (2026-05-18)

## 审查范围
- scanner.py (市场扫描器核心, 2200+行)
- broker.py (仿真撮合引擎, 717行)
- live_filter_pipeline.py (9层筛选管道, 502行)
- api/scanner.py (REST API, 1684行)
- api/trading.py (交易API, 619行)
- websocket.py (WebSocket推送, 239行)
- daily_scheduler.py (日调度器, 832行)
- MarketMonitorView.vue (前端主视图, 637行)

---

## P0 (会导致资金损失/数据错误)

### P0-1: `_check_circuit_breaker` 同步方法中用了 `await`
- **文件**: scanner.py:1923
- **问题**: `_check_circuit_breaker` 是 `def` (同步方法), 但内部调用了 `await self._publish_scanner_event(...)`. Python允许在同步方法中写await(不会语法错误), 但运行时会报 `RuntimeError: no running event loop` 或返回未awaited coroutine.
- **影响**: 熔断触发时推送通知失败, 且方法返回值可能不正确
- **修复**: ✅ 已修复 — 改为 `async def _check_circuit_breaker`, 两个调用点改为 `await self._check_circuit_breaker()`

### P0-2: `save_state` 节流导致止损后关键数据丢失
- **文件**: broker.py:135, scanner.py:1546/1650
- **问题**: `save_state()` 有30秒节流, 止损/止盈卖出后调用 `save_state()` 可能被节流跳过, 导致关键交易数据丢失
- **影响**: 止损卖出后30秒内重启, 止损记录丢失, 持仓/账户状态不一致
- **修复**: ✅ 已修复 — `save_state(force=True)` 参数, 止损/止盈后强制保存

### P0-3: `_execute_sell` 盈亏计算 — 手续费双重扣除
- **文件**: broker.py:658-662
- **问题**: `profit = (fill_price - avg_cost) * qty - total_cost` 和 `amount = fill_price * qty - total_cost`, `available_cash += amount`. 这里 profit 扣了手续费, amount 也扣了手续费, 但 total_profit 加的是 profit (已扣手续费), available_cash 加的是 amount (也扣了手续费). 实际上这是正确的: 卖出后到手金额确实是 fill_price * qty - total_cost, 盈亏也确实是 (fill_price - avg_cost) * qty - total_cost.
- **结论**: ✅ 无bug, 逻辑正确

### P0-4: 信号过期后未自动清理
- **文件**: scanner.py
- **问题**: 信号5分钟后应标记为expired并从_active_signals中移除, 但当前只在scan_once开头检查过期, 如果scanner停止再启动, 过期信号不会被清理
- **影响**: 过期信号堆积, 前端显示混乱
- **修复**: 在scan_once开头添加信号过期清理逻辑

---

## P1 (影响实盘稳定性)

### P1-1: `stop()` 方法不保存状态
- **文件**: scanner.py:343
- **问题**: 停止扫描时没有保存当前状态(持仓/账户/时间线)到MongoDB, 重启后可能丢失
- **修复**: ✅ 已修复 — stop()中添加强制save_state(force=True)和_save_timeline()

### P1-2: 交易终止无清仓选项
- **文件**: scanner.py:343, api/scanner.py:230
- **问题**: 停止扫描只停止循环, 不清仓, 用户需要手动逐个卖出
- **修复**: ✅ 已修复 — stop(sell_all=True)支持清仓选项

### P1-3: 前端5次并发请求效率低
- **文件**: MarketMonitorView.vue:fetchScanner()
- **问题**: fetchScanner()并发5个HTTP请求(status/signals/positions/timeline/orders), 已有fetchScannerFast()用/all合并端点但未默认使用
- **修复**: 默认使用fetchScannerFast(), 仅在需要全量数据时用fetchScanner()

### P1-4: WebSocket断线后无重连提示
- **文件**: MarketMonitorView.vue:connectWS()
- **问题**: WebSocket断线后自动3秒重连, 但前端无任何提示, 用户不知道数据是否实时
- **修复**: 添加连接状态指示器(绿/红/灰)

### P1-5: 持仓盈亏未实时更新
- **文件**: scanner.py:get_positions()
- **问题**: 持仓的current_price依赖update_realtime()调用, 非交易时间价格不更新, 盈亏显示为0或旧值
- **修复**: get_positions()中从东方财富缓存获取最新价格

### P1-6: 交易报告缺少策略维度分析
- **文件**: api/scanner.py:get_daily_report()
- **问题**: 日报只有总体统计, 缺少按策略维度的胜率/收益/回撤分析
- **修复**: 增强日报, 添加策略维度统计

### P1-7: 危出后持仓对象被修改但timeline记录用的是旧pos
- **文件**: scanner.py:_check_positions()
- **问题**: `profit_amount: round((pos.current_price - pos.avg_cost) * pos.available_qty, 2)` 在 `place_order` 之后, pos.available_qty已被修改(减少), 导致profit_amount计算错误
- **修复**: 在place_order之前保存available_qty, 用保存的值计算

---

## P2 (代码质量和性能优化)

### P2-1: broker.py save_state中delete_many+insert_many效率低
- **文件**: broker.py
- **问题**: 持仓保存用delete_many+insert_many, 已改为upsert, 但清理已平仓持仓的delete_many仍可能误删
- **修复**: 已用upsert替代, 清理逻辑保留但加安全检查

### P2-2: scanner.py _merge_factors中merge可能产生大量NaN
- **文件**: scanner.py
- **问题**: rt_df.merge(daily_sub) 用left join, 日级因子缺失时产生NaN, 虽然有fillna(0)但0可能影响策略筛选
- **修复**: 策略筛选时对NaN/0做特殊处理

### P2-3: 前端信号过期倒计时每秒更新DOM
- **文件**: MarketMonitorView.vue
- **问题**: setInterval每秒更新nowMs, 触发所有信号的remaining计算和DOM更新, 信号多时性能差
- **修复**: 用requestAnimationFrame或减少更新频率

### P2-4: api/scanner.py _get_scanner()全局单例不安全
- **文件**: api/scanner.py
- **问题**: 全局_scanner_instance在多线程/多进程环境下不安全, 但当前单进程无问题
- **修复**: 低优先级, 当前架构下可接受

---

## 已修复汇总

| 编号 | 级别 | 描述 | 状态 |
|------|------|------|------|
| P0-1 | P0 | _check_circuit_breaker同步方法用await | ✅ 已修 |
| P0-2 | P0 | save_state节流导致止损数据丢失 | ✅ 已修 |
| P1-1 | P1 | stop()不保存状态 | ✅ 已修 |
| P1-2 | P1 | 交易终止无清仓选项 | ✅ 已修 |
