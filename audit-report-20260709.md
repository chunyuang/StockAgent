# 实盘交易审查报告 2026-07-09

**审查时间**: 2026-07-09 06:30-06:40 (Asia/Shanghai)
**分支**: cron/nightly-fixes (merged feature/market-monitor-auto)
**Issue队列**: 空

---

## Phase 1: 账户状态 ✅

| 指标 | 值 | 状态 |
|------|------|------|
| 总资产 | ¥829,448 | -17.1% (初始100万) |
| 可用现金 | ¥560,761 | ✅ 与推算一致(差异=0) |
| 持仓市值 | ¥268,687 | 5只持仓 |
| 总仓位 | 32.4% | ✅ < 75%上限 |
| 今日盈亏 | ¥0 | (非交易日,无变化) |

### 持仓明细

| 代码 | 名称 | 数量 | 成本 | 现价 | 盈亏% | 策略 | 买入日 |
|------|------|------|------|------|-------|------|--------|
| 002396.SZ | 星网锐捷 | 1400 | 29.28 | 29.10 | -0.6% | first_limit_up | 07-08 |
| 002429.SZ | 兆驰股份 | 5900 | 11.10 | 10.55 | -5.0% | halfway_chase | 07-07 |
| 301201.SZ | 诚达药业 | 1100 | 45.85 | 41.13 | -10.3% | halfway_chase | 07-08 |
| 603065.SH | 宿迁联盛 | 2100 | 21.39 | 21.91 | +2.4% | halfway_chase | 07-08 |
| 603903.SH | 中持股份 | 4700 | 15.63 | 15.84 | +1.3% | first_limit_up | 07-06 |

### 一致性检查

- ✅ broker_orders vs broker_positions: 无交叉差异
- ✅ 无重复成交订单(order_id唯一)
- ✅ 无零仓位残留
- ✅ 买入-持仓一致
- ✅ 资金推算与存储完全一致(差异=0)
- ✅ 已实现盈亏 +4,965 / 未实现 -6,647
- ✅ 单票仓位均 < 35%上限(最大9.0%)

### 拒绝订单统计

共5笔拒绝(历史):
- 涨停未成交(成交概率55%): 4次 — 正常(模拟涨停成交概率)
- 非连续竞价时间禁止自动成交: 1次 — 正常(时间门控生效)

---

## Phase 2: 买卖执行逻辑 ✅

### 5. broker.execute_buy流程

**资金检查→建仓→T+1锁定** 流程完整:
1. `_validate_prechecks()`: 停牌/行情/整手检查
2. `_validate_and_adjust_buy()`: 资金检查 + 仓位调整 + 持仓数量上限 + 尾盘禁止新开仓
3. `_execute_order_fill()` → `_execute_buy()`: 撮合 + 更新持仓/资金
4. `_sync_save_order_and_position()`: 同步写入MongoDB(关键路径)
5. T+1锁定: `available_qty=0`, `today_buy_qty=order.quantity`

**v2.9.110修复**: 尾盘禁止新开仓(与MarketPhase.is_open_allowed对齐)

### 6. broker.execute_sell流程

**9层时间防护→卖出→avg_cost保存** 流程完整:

| 层级 | 检查点 | 位置 |
|------|--------|------|
| L1 | is_continuous_auction() | broker.place_order |
| L2 | is_open_allowed() | broker._validate_and_adjust_buy(仅买入) |
| L3 | is_continuous_auction() | position_manager.execute_sell_list_from_risk |
| L4 | is_continuous_auction() | position_manager.execute_risk_sell |
| L5 | is_continuous_auction() | position_manager.liquidate_positions |
| L6 | is_continuous_auction() | risk_watchdog._liquidate_positions |
| L7 | is_continuous_auction() | position_checker._execute_sell_list |
| L8 | is_continuous_auction() | scanner._liquidate_positions |
| L9 | is_continuous_auction() | scanner._liquidate_positions_by_codes |

✅ 所有sell路径统一使用`is_continuous_auction()`(非`is_in_trading()`,避免午休误触)

**avg_cost保存**: 卖出时`order.avg_cost = pos.avg_cost`写入MongoDB ✅

### 7. MarketPhase.is_in_trading()在所有sell path上

所有sell路径已从`is_in_trading()`升级到`is_continuous_auction()`:
- 旧`is_in_trading()`含午休(11:30-13:00), broker因非连续竞价拒单→无意义rejected
- 新`is_continuous_auction()`仅早盘/午盘/尾盘, 与broker门控一致

✅ 所有6个sell入口点均已对齐

### 8. scanner崩溃时save_state()可靠性

**多层保障**:
1. `_sync_save_order_and_position()`: 同步pymongo写入(关键路径,不依赖事件循环)
2. `_recalc_account()`: 从MongoDB全量orders推算available_cash(v2.9.108)
3. `_reconcile_after_load()`: load_state后一致性校验, 以positions为权威
4. `_need_reconciliation`: 行情首次更新后强制recalc(解决current_price=0问题)

✅ 崩溃恢复路径可靠

---

## Phase 3: 风控执行 ✅

### 9. 止损监控

**风控独立线程** `_risk_loop_sync`:
- 1秒止损检查(`_check_stop_loss_only`): 用缓存数据,零API成本
- 30秒quick check: 东财缓存,零额度
- 60秒跌停挂起超时检查
- ATR自适应止损(v2.9.119): `stop_loss = min(max(strategy_min, 1.2*ATR%), ATR_STOP_CAP%)`

**止损路径**:
- 风控线程 → `check_stop_loss_only()` → `execute_sell_list_from_risk()` → `execute_risk_sell()`
- 扫描循环 → `check_stop_loss_take_profit()` → `_execute_sell_list()` → `_place_sell_order()`

✅ 两条路径均正确工作

### 10. 持仓比例限制MAX_POSITION_RATIO

- 单票: 35% (`MAX_POSITION_RATIO`) ✅ 当前最大9.0%
- 总仓位: 75% (`MAX_TOTAL_RATIO`) ✅ 当前32.4%
- 持仓数: 动态`_dynamic_max_positions`(基准10) ✅ 当前5只

### 11. 熔断机制circuit_breaker

| 规则 | 阈值 | 效果 |
|------|------|------|
| 单日回撤 | >5% | 暂停所有交易 |
| 连续亏损 | ≥3次 | 暂停买入(可卖出) |
| 手动暂停 | 人工触发 | 暂停交易 |

✅ 线程安全(通过`_with_state_lock`保护)
✅ 熔断触发后通过EventBus/推送通知

### 12. dry_run模式正确性

- `MODE_DRY_RUN = "dry_run"`: 只扫描不交易
- `_handle_dry_run()`: 记录would_buy_shares/would_buy_amount, 不执行place_order
- `signal_status = "skipped"`: 标记为跳过
- `_virtual_mode = True`: save_state跳过, 不覆盖MongoDB实盘数据

✅ dry_run模式正确隔离

---

## 发现并修复的问题

### 🔴 P2: broker止损/止盈价使用全局默认值而非策略级参数

**问题**: `_save_positions_to_mongo`和`_sync_save_order_and_position`写入MongoDB的`stop_loss_price`/`take_profit_price`使用全局默认值(3%/7%), 而非策略级参数。

**根因**: `strat_cfg.get('stop_loss_pct')`在顶层查找, 但实际值在`strat_cfg['riskParams']['stop_loss_pct']`中。`_sync_save_order_and_position`更差——`getattr(position, 'stop_loss_price', 0)`始终=0(Position dataclass无此属性)。

**影响范围**: 
- 仅影响MongoDB中存储的止损/止盈价元数据(前端显示)
- **实际止损执行不受影响**(PositionManager._get_risk_with_overrides正确读取riskParams)

**修复**: 
1. `_save_positions_to_mongo`: 从`riskParams`子字典读取
2. `_sync_save_order_and_position`: 计算策略级止损/止盈价

**Commit**: 1b13f4f4 (v2.9.120)

---

## 测试结果

| 项目 | 结果 |
|------|------|
| pytest (1607 tests) | ✅ 全部通过 |
| vite build | ✅ 构建成功(12.66s) |
| pre-commit hooks | ✅ 通过(broker watchdog + duplicate_methods) |

---

## 审查结论

**系统整体健康**: ✅

1. 账户一致性: 现金推算差异=0, 无重复订单, 无零仓位残留
2. 买卖执行: 9层时间防护完整, T+1正确, avg_cost持久化
3. 风控: 止损独立线程可靠, ATR自适应, 熔断机制完善
4. 崩溃恢复: 同步写入+一致性校验+reconciliation三重保障
5. 发现1个P2问题(止损价元数据)已修复并提交

**关注项**:
- 兆驰股份(-5.0%)和诚达药业(-10.3%)浮亏较大, 但在ATR止损范围内
- 中持股份持仓3天(07-06买入), 首板策略max_hold=2天已超时, 应关注今日是否止损
