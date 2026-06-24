# 实盘交易审查报告 2026-06-25

**审查时间**: 2026-06-25 01:46 CST (凌晨)
**分支**: cron/nightly-fixes (merged feature/market-monitor-auto)
**Issue队列**: 空 (无待修Issue)
**测试**: ✅ 1587 passed / 0 failed / 4 skipped
**构建**: ✅ vite build 成功 (11.62s)

---

## Phase 1: 账户状态审查

### 1.1 Scanner状态
- Scanner未运行(凌晨1:46，预期行为)
- API端点 `/api/v1/scanner/status` 不可达(正常，进程未启动)

### 1.2 broker_orders vs broker_positions 一致性
- **持久化路径**: `broker.py` 使用双重写入机制
  - **关键路径**: `_sync_save_order_and_position()` — 同步pymongo写入，不依赖事件循环
  - **非关键路径**: `save_state()` — 异步写入账户等非关键数据
- **一致性保证**: 
  - ✅ 订单+持仓使用 `update_one + upsert`，按 `order_id` / `(account_id, ts_code)` 唯一键
  - ✅ 清仓持仓自动清理: `position.total_qty <= 0` 时 `delete_one`
  - ✅ `save_state()` 中清理残留持仓: `delete_many({ts_code: {$nin: current_codes}})`

### 1.3 重复订单检测
- ✅ **v2.9.92x修复**: `_save_today_orders_to_mongo()` 从 `insert_many` 改为 `update_one + upsert`
  - 根因: 两个并发 `save_state` 都查到空集 → 双重 `insert`
  - 修复: 用 `order_id` 唯一键 upsert，并发安全
- ✅ **v2.9.95f**: `_today_rejected` 去重缓存，同一 ts_code+side 同日只记一条 rejected
- ✅ **v2.9.96c**: `load_state()` 恢复前清除今日内存 orders，避免重复追加

### 1.4 持仓丢失检测
- ✅ `_restore_positions_from_mongo()`: 从 `broker_positions` 恢复所有持仓
- ✅ `buy_date` 字段 v2.9.99修复: 保存+恢复，超时强卖依赖此字段
- ✅ `stop_loss_price/take_profit_price` v2.9.95f: 买入时写入，scanner崩溃后止损监控不失效
- ⚠️ **潜在风险**: `_sync_save_order_and_position` 写入持仓时不包含 `stop_loss_price/take_profit_price`
  - 异步 `save_state` 包含这些字段，但同步写入不包含
  - 影响: 进程在异步 `save_state` 完成前崩溃，MongoDB中持仓可能缺少止损价
  - 严重性: 低 — 下次 `save_state` 或 scanner重启时会补写

---

## Phase 2: 买卖执行逻辑审查

### 2.1 broker.execute_buy 流程 ✅
- **资金检查**: `est_amount = quantity * current_price * (1 + COMMISSION_RATE)`，含佣金估算(v2.9.84修复)
- **建仓**: 新仓 `available_qty=0` (T+1锁定)，加仓重算 `avg_cost` 含佣金
- **T+1锁定**: `today_buy_qty += order.quantity`，`available_qty` 初始为0
- **日结算解锁**: `daily_settlement()` 解锁 `available_qty = total_qty`

### 2.2 broker.execute_sell 流程 ✅
- **9层时间防护**:
  1. `place_order()`: `MarketPhase.is_continuous_auction()` — 非连续竞价拒单
  2. `_check_stop_loss_only()`: `MarketPhase.is_in_trading()` — 非交易时段不执行止损
  3. `_execute_sell_list()`: 非交易时段(AFTER_CLOSE/OFF_HOURS/DEEP_NIGHT/WEEKEND/PREMARKET)跳过卖出
  4. `emergency_liquidate()`: `MarketPhase.is_in_trading()` — 非交易时段跳过紧急平仓
  5. `_check_circuit_breaker()`: 熔断后禁止交易
  6. `_can_execute_force_empty_now()`: 仅连续竞价允许强制空仓
  7. 竞价风控状态机: 09:25-09:30确认后需等09:30开盘执行
  8. LATE_TRADING: 尾盘禁止新开仓
  9. 跌停不可卖 → pending_sells挂起
- **avg_cost保存**: ✅ v2.9.98f: `order.avg_cost = pos.avg_cost`，记录到broker_orders

### 2.3 MarketPhase.is_in_trading() 覆盖 ✅
- 所有sell path均已覆盖:
  - `place_order()` → `is_continuous_auction()` (严格，含午休/竞价)
  - `_check_stop_loss_only()` → `is_in_trading()` (宽泛，含午休)
  - `_execute_sell_list()` → 显式排除 AFTER_CLOSE/OFF_HOURS/DEEP_NIGHT/WEEKEND/PREMARKET
  - `emergency_liquidate()` → `is_in_trading()`
- **无遗漏**: 所有卖出路径均有时间门控

### 2.4 scanner崩溃时 save_state() 可靠性 ✅
- **v2.9.97f**: 关键路径使用同步pymongo写入 `_sync_save_order_and_position()`
  - 不依赖 asyncio 事件循环，进程崩溃前数据已落盘
  - 写入失败降级到异步 `save_state`
- **节流**: `save_state` 30秒内不重复(可 `force=True` 跳过)
- **virtual_mode保护**: replay/dry_run模式不写MongoDB，防止覆盖实盘数据

---

## Phase 3: 风控执行审查

### 3.1 止损监控: risk_loop 检测+自动卖出 ✅
- **架构**: `RiskLoopRunner` 独立线程(1秒循环)，不受asyncio事件循环影响
- **1秒止损**: `_check_stop_loss_only()` — 用缓存数据，零API成本
- **30秒quick check**: `_check_positions_quick()` — 东财缓存，零额度
- **60秒跌停超时**: `check_pending_sells_timeout()`
- **v2.9.82修复**: 用实时价格重算 `profit_pct`，避免基于过期 `current_price`
- **跌停挂起**: `_handle_limit_down()` — 跌停不可卖时挂起 `pending_sells`
- **跌停恢复**: 恢复时自动执行挂起的卖出

### 3.2 持仓比例限制 MAX_POSITION_RATIO ✅
- **Scanner**: `MAX_POSITION_RATIO = 0.7` (总仓位上限70%)
- **Broker**: 
  - `MAX_POSITION_RATIO = GLOBAL_RISK.get("max_position_per_stock", 0.35)` (单票35%)
  - `MAX_TOTAL_RATIO = GLOBAL_RISK.get("max_total_position", 0.75)` (总仓位75%)
- **执行**: `_validate_and_adjust_buy()` 中检查，超限时自动调整数量
- **板块集中度**: v2.9.92x 新增 `_apply_sector_concentration()`，同行业最多3只

### 3.3 熔断机制 circuit_breaker ✅
- **单日回撤>5%**: 暂停所有交易
- **连续亏损3次**: 暂停买入(可卖出止损)
- **手动暂停**: 支持人工干预
- **竞价风控**: Level3全清+冷却期，Level2降仓+禁开仓
- **冷却期**: 强制空仓后N天内仓位上限60%
- **线程安全**: 所有circuit_breaker操作通过 `_with_state_lock()` 保护

### 3.4 dry_run 模式正确性 ✅
- **初始化**: `_dry_run = (trade_mode == MODE_DRY_RUN)`
- **卖出跳过**: `_execute_sell_list()` 中 `if self.dry_run: 跳过卖出`
- **MongoDB保护**: 
  - `_sync_save_order_and_position()`: virtual_mode 不写
  - `save_state()`: virtual_mode 跳过
  - `emergency_liquidate()`: replay/dry_run 不覆盖实盘数据
- **timeline记录**: dry_run模式下仍记录timeline(供调试查看)

---

## 审查结论

| 检查项 | 状态 | 说明 |
|--------|------|------|
| broker_orders vs broker_positions 一致性 | ✅ | 双重写入+upsert保证 |
| 重复订单检测 | ✅ | order_id唯一键+去重缓存 |
| 持仓丢失检测 | ✅ | buy_date/止损价持久化+恢复 |
| execute_buy 流程 | ✅ | 资金检查→建仓→T+1锁定 |
| execute_sell 流程 | ✅ | 9层时间防护+avg_cost保存 |
| MarketPhase 覆盖 | ✅ | 所有sell path有时间门控 |
| save_state 可靠性 | ✅ | 同步pymongo写入关键数据 |
| 止损监控 | ✅ | 1秒风控线程+实时价格 |
| MAX_POSITION_RATIO | ✅ | 单票35%+总仓位75%+板块集中度 |
| circuit_breaker | ✅ | 回撤+亏损+竞价+冷却期 |
| dry_run 模式 | ✅ | 跳过交易+MongoDB保护 |

### 发现的潜在风险 (非阻塞)

1. **⚠️ _sync_save_order_and_position 不含止损价/止盈价** — 进程崩溃时MongoDB持仓可能缺这些字段，下次save_state补写。影响低。
2. **⚠️ MarketPhase.classify() 用系统时间** — 若系统时钟漂移可能影响时间门控。生产环境应确保NTP同步。

### 总评
实盘交易系统核心逻辑健全，关键修复(重复订单/时间防护/同步写入/止损价持久化)均已到位。无阻塞性问题，无需新建Issue。

---

*审查人: Auto-Review Agent | 分支: cron/nightly-fixes*
