# 信号管道审查报告 — 2026-07-01 02:30 CST

**分支**: cron/nightly-fixes (已合并 feature/market-monitor-auto)
**锚点**: signal-pipe-audit
**Issue队列**: 空

---

## Phase 1: 9层漏斗 ✅

### 1. L1→L9 每层数量递减 ✅
- L1 全市场(5400只) → L4 盘前预选(~50-200) → L5 竞价(~30-100) → L6 策略量能(~5-20) → L7 排序去重(≤10) → L8 仓位控制 → L9 买入执行
- `_build_trace_summary()` 正确追踪每层input/output/rejected
- `_record_layer_drop()` 记录每只被淘汰候选的具体拒绝原因

### 2. 每层过滤逻辑正确性 ✅
- L1: 涨停≥80 / 涨停≤10且跌停>0 / 大盘跌≥3% → 强制空仓（与回测GLOBAL_RISK对齐）
- L2: SpecialPeriodFilter复用回测，月末30%/周五70%
- L3: 三级策略(盘中7维/盘后5维/简化fallback)，冰点<40暂停半路追涨
- L4: ST/退市/次新(<60天)/低流动性(<500万)排除
- L5: 竞价极端(高开>7%/低开<-5%)排除，首板打板额外要求≥2%
- L6: 复用回测_build_strategy_filter_conditions
- L7: 策略优先级排序+同股去重+截断10只
- L8: 情绪×特殊×MA60×硬上限75%×冷却期
- L9: 管道外由MarketScanner执行

### 3. layerDesc中文描述完整 ✅
- 每层layer_details含完整中文描述+具体数值+触发条件
- L3新增L3_sentiment_data结构化字段(7维明细)，前端不再需要正则解析文本
- L8含冷却期+MA60具体数值

### 4. scan_traces存储完整性 ✅
- CandidateTrace追踪每只候选的逐层passed/rejected状态
- _build_trace_summary正确计算每层input/output/rejected
- _finalize_traces标记最终passed/rejected+L9默认passed
- trace持久化到MongoDB scanner_traces集合

---

## Phase 2: 扫描器架构 ✅

### 5. scanner_loop运行状态 ✅
- _scan_loop: 主循环，双层节奏(5分钟全量/30秒持仓检查)
- 阶段处理: 周末/盘前/竞价/交易/尾盘/盘后，各阶段有独立处理方法
- 尾盘(LATE_TRADING 14:30+): 仅持仓检查，禁止新开仓 ✅

### 6. scan_once流程+异常处理 ✅
- 7步流程: 行情→因子→策略+筛选→信号→持仓检查→同步→持久化
- _StepTimer分步计时，异常不向上传播(返回False让主循环继续)
- 连续3次异常→scanner退出
- 风控线程看门狗: 检测线程退出并自动重启(最多3次)

### 7. 策略路由signal_dispatcher ✅
- 统一出口: 所有信号经SignalDispatcher分发
- 多通道: Redis Stream(不可丢)/飞书(仅HIGH+CRITICAL)/日志(审计)
- 信号去重: 同ts_code+strategy 5分钟内不重复推送
- CRITICAL级不去重(熔断/强平/系统异常)
- 过期信号自动丢弃

---

## Phase 3: 卖出时间防护+实盘交易逻辑 ✅

### 8. broker.execute_buy/execute_sell完整流程 ✅
**execute_buy (_execute_buy)**:
- 加仓: 重算avg_cost = (旧成本+新成本+佣金)/总数量 ✅
- 新仓: avg_cost含佣金，available_qty=0(T+1) ✅
- today_buy_qty累加 ✅
- buy_date = trade_date ✅

**execute_sell (_execute_sell)**:
- 计算盈亏: profit = (fill_price - avg_cost) * quantity - total_cost ✅
- profit_pct含佣金(与profit_amount对齐) ✅
- order.avg_cost记录(供MongoDB查询) ✅
- 收回资金 = fill_price * quantity - total_cost ✅
- available_qty/total_qty同步减少 ✅
- total_qty<=0时del positions ✅

### 9. 所有sell path都有is_continuous_auction()检查 ✅ ⭐关键
**6个卖出路径全部已覆盖**:
1. `broker.place_order` (最内层门控) → MarketPhase.is_continuous_auction() ✅
2. `position_manager.execute_sell_list_from_risk` → is_continuous_auction() ✅
3. `position_manager.execute_risk_sell` → is_continuous_auction() ✅
4. `position_manager.liquidate_positions` → is_continuous_auction() ✅
5. `position_checker._execute_sell_list` → is_continuous_auction() ✅
6. `scanner._check_stop_loss_only` → is_continuous_auction() ✅
7. `daemon_watchdog_mixin` → is_continuous_auction() ✅
8. `risk_watchdog` → is_continuous_auction() ✅

**统一从is_in_trading迁移到is_continuous_auction**:
- 旧: is_in_trading() 含午休(11:30-13:00)，broker会因非连续竞价拒单→产生无意义rejected
- 新: is_continuous_auction() 仅早盘/午盘/尾盘，与broker门控一致
- 所有路径已对齐，无遗漏

### 10. T+1规则验证 ✅
- Position.available_qty: 可卖数量(=total_qty - today_buy_qty)
- 买入时: available_qty=0, today_buy_qty累加 ✅
- 卖出校验: available_qty<=0 → "无可用持仓(T+1限制)" ✅
- daily_settlement: 解锁T+1(available_qty=total_qty, today_buy_qty=0) ✅
- liquidate_positions: 跳过available_qty<=0的持仓 ✅

### 11. avg_cost保存验证 ✅
- 买入时avg_cost含佣金 ✅
- 加仓时avg_cost重算(含佣金) ✅
- _sync_save_order_and_position同步写入avg_cost到MongoDB ✅
- _save_positions_to_mongo持久化avg_cost ✅
- order.avg_cost记录(供MongoDB查询) ✅
- _recalc_account用avg_cost推算market_value ✅

### 12. MarketPhase各阶段判断正确性 ✅
- WEEKEND: weekday>=5 ✅
- DEEP_NIGHT: 23:00-08:00 ✅
- PREMARKET: 09:00-09:25 ✅
- AUCTION: 09:25-09:30 ✅
- MORNING: 09:30-11:30 ✅
- LUNCH: 11:30-13:00 ✅
- AFTERNOON: 13:00-14:30 ✅
- LATE_TRADING: 14:30-15:00 ✅ (禁止新开仓)
- AFTER_CLOSE: 15:05+ ✅
- OFF_HOURS: 其他 ✅

---

## Phase 4: 修复+验证

### 发现的Bug: 0

本次审查未发现新bug。所有关键逻辑点均已被此前版本修复:

- v2.9.98: is_in_trading→is_continuous_auction统一(6+路径)
- v2.9.80: _record_layer_drop从trace_candidates查找(而非result.candidates)
- v2.9.82: 卖出盈亏使用broker实际成交价(而非预估值)
- v2.9.89: L4次新排除从factors获取list_date
- v2.9.91: profit_pct含佣金与profit_amount对齐
- v2.9.95f: 当日拒绝去重缓存(防止rejected堆积)
- v2.9.96: decision_trace完整决策轨迹
- v2.9.99: buy_date保存/恢复(超时强卖依赖)
- v2.9.108: load_state一致性校验(accounts从positions反推)
- v2.9.106: risk_decisions审计trail统一

### 验证结果
- pytest: **1594 passed, 4 skipped, 0 failed** ✅
- vite build: **成功(12.24s)** ✅
- WEB布局: 未改动 ✅
- null ref: 关键路径已有?.防御 ✅

---

## 总结

| 检查项 | 状态 | 备注 |
|--------|------|------|
| 9层漏斗递减 | ✅ | trace追踪完整 |
| 过滤逻辑正确性 | ✅ | 与回测对齐 |
| layerDesc中文描述 | ✅ | 含7维结构化数据 |
| scan_traces完整性 | ✅ | CandidateTrace+summary |
| scanner_loop状态 | ✅ | 阶段处理+看门狗 |
| scan_once异常处理 | ✅ | 不传播+3次退出 |
| signal_dispatcher | ✅ | 统一出口+去重+多通道 |
| execute_buy/sell | ✅ | avg_cost含佣金+T+1 |
| sell path时间防护 | ✅ | 8个路径全部is_continuous_auction |
| T+1规则 | ✅ | available_qty正确维护 |
| avg_cost保存 | ✅ | 同步+异步双写 |
| MarketPhase判断 | ✅ | 9阶段分类正确 |

**信号管道健康度: 🟢 优秀 — 无新bug，0失败，可安全上线**
