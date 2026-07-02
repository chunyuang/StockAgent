# 实盘交易审查报告 — 2026-07-03 06:30 (夜间)

## Phase 0: Issue队列
- **待修队列为空** ✅

## Phase 1: 账户状态 (Scanner离线，代码审查)

### 1. 账户总资产/可用资金/持仓数
- Scanner服务未运行(06:30非交易时间,正常)
- `Account` dataclass: `total_assets`/`available_cash`/`market_value`/`frozen_cash` 字段完整
- **`_recalc_account()`** 从MongoDB全量orders推算cash，不信任内存值(v2.9.108修复) ✅

### 2. broker_orders vs broker_positions一致性
- `_sync_save_order_and_position()`: 同步写入order+position到MongoDB(v2.9.97f)
- 买入时: order写入 + position upsert + accounts同步写入 ✅
- 卖出时: order写入 + position更新/删除 + accounts同步写入 ✅
- `load_state()`: 恢复account→positions→orders，然后`_reconcile_after_load()`做一致性校验 ✅
- **v2.9.108修复**: positions为权威，cash与positions不同步时从orders反推修正 ✅

### 3. 重复订单检测
- `_today_rejected` set: 同一ts_code+side同日只记一次rejected(v2.9.95f) ✅
- `_save_today_orders_to_mongo()`: 改用upsert by order_id(v2.9.92x修复并发重复) ✅
- `_restore_orders_from_mongo()`: load_state去重保护(v2.9.96c) ✅
- order_id格式: `ORD{HHMMSS}{序号:04d}` — 同秒内序号递增，不同秒不冲突 ✅

### 4. 持仓丢失检测
- `_save_positions_to_mongo()`: 持仓upsert + 清理已平仓(delete_many ts_code $nin) ✅
- `_reconcile_after_load()`: load后检测cash=初始值但positions非空→自动修复 ✅
- `_need_reconciliation` 标记: 行情首次更新后强制recalc(v2.9.108) ✅
- 卖出时position不在内存: 从MongoDB兜底查avg_cost(v2.9.109修复) ✅

## Phase 2: 买卖执行逻辑

### 5. execute_buy流程
```
place_order → _validate_prechecks(停牌/行情/整手)
           → _validate_and_adjust_buy(尾盘禁止/资金/仓位)
           → _execute_order_fill → _match(动态滑点) → _execute_buy
```
- **资金检查**: `est_amount = qty * price * (1+COMMISSION_RATE)` 含佣金(v2.9.84) ✅
- **建仓**: `available_qty=0`(T+1锁定)，`today_buy_qty=qty` ✅
- **加仓**: 重算avg_cost(含佣金)，`today_buy_qty += qty` ✅
- **尾盘禁止新开仓**: `MarketPhase.is_open_allowed()`(v2.9.110) ✅
- **涨停成交概率**: 按hit_probability模拟(v2.9.92w与回测对齐) ✅

### 6. execute_sell流程
```
place_order → _validate_prechecks → _validate_sell(持仓/跌停/可卖量)
           → _execute_order_fill → _match → _execute_sell
```
- **9层时间防护**:
  1. `MarketPhase.is_continuous_auction()` — broker.place_order门控(v2.9.97h-v9) ✅
  2. `MarketPhase.is_open_allowed()` — 尾盘禁止开仓(v2.9.110) ✅
  3. `_check_stop_loss_only` → `is_continuous_auction()`(v2.9.98→v2.9.100) ✅
  4. `_liquidate_positions_by_codes` → `is_continuous_auction()`(v2.9.106) ✅
  5. `emergency_liquidate` → `is_continuous_auction()`(v2.9.98→v2.9.107) ✅
  6. `RiskWatchdog._liquidate_positions` → `is_continuous_auction()`(v2.9.98) ✅
  7. 跌停不可市价卖出(`_validate_sell`) ✅
  8. `_risk_non_trading_sleep` — 非交易时间降低频率 ✅
  9. `_can_execute_force_empty_now` — 强制空仓时间门禁 ✅
- **avg_cost保存**: order.avg_cost = pos.avg_cost(v2.9.98f) ✅
- **profit计算**: 含佣金+印花税，与profit_amount对齐(v2.9.91) ✅
- **position不在内存兜底**: 从MongoDB查avg_cost(v2.9.109) ✅

### 7. MarketPhase.is_in_trading()在所有sell path上
审查所有卖出路径的时间门控:
| 卖出路径 | 时间门控 | 状态 |
|----------|----------|------|
| broker.place_order(sell) | `is_continuous_auction()` | ✅ v2.9.97h-v9 |
| risk_loop止损 | `is_continuous_auction()` | ✅ v2.9.100 |
| emergency_liquidate | `is_continuous_auction()` | ✅ v2.9.107 |
| 情绪降仓 | 委托PM → broker.place_order | ✅ 间接 |
| 强制空仓 | `is_continuous_auction()` | ✅ |
| 竞价L2降仓 | `is_continuous_auction()` | ✅ v2.9.106 |
| 停止清仓 | broker.place_order | ✅ 间接 |

### 8. scanner崩溃时save_state()可靠性
- **同步写入**: `_sync_save_order_and_position()` 用pymongo同步客户端(v2.9.97f) ✅
- **不依赖事件循环**: place_order是sync方法，同步写入保证崩溃前完成 ✅
- **降级策略**: 同步写入失败时降级到asyncio.create_task(save_state) ✅
- **节流保护**: 30秒内不重复save_state(force=True跳过) ✅
- **虚拟模式保护**: dry_run/replay不写MongoDB(v2.9.92s) ✅

## Phase 3: 风控执行

### 9. 止损监控: risk_loop检测+自动卖出
- **RiskLoopRunner**: 独立threading.Thread，1秒止损检查(缓存数据，零API成本) ✅
- **止损检查**: `_check_stop_loss_only` → PM.check_stop_loss_only → _execute_sell_list_from_risk ✅
- **跌停挂起**: pending_sells + 60秒超时检查(`check_pending_sells_timeout`) ✅
- **行情缓存过期**: 120秒无更新告警 + EventBus事件 ✅
- **错误退避**: 3次→5s, 10次→30s ✅

### 10. 持仓比例限制MAX_POSITION_RATIO
- **单票上限**: `MAX_POSITION_RATIO = GLOBAL_RISK.max_position_per_stock`(默认35%) ✅
- **总仓位上限**: `MAX_TOTAL_RATIO = GLOBAL_RISK.max_total_position`(默认75%) ✅
- **尾盘禁止新开仓**: `MarketPhase.is_open_allowed()` 仅早盘+午盘允许 ✅
- **板块集中度**: 同行业最多3只(v2.9.92x与回测对齐) ✅
- **冷却期**: 强制空仓后2天内仓位上限60%(v2.9.92w) ✅

### 11. 熔断机制circuit_breaker
- **单日回撤>5%**: 暂停所有交易 + EventBus事件 ✅
- **连续亏损3次**: 暂停买入(可卖出止损) ✅
- **手动暂停**: 尊重人工干预 ✅
- **线程安全**: `_with_state_lock` 封装所有circuit_breaker读写(v2.9.17) ✅
- **每日重置**: `reset_daily_risk_state` 重置daily_start/trading_paused/consecutive_losses ✅
- **RiskWatchdog独立循环**: 30秒健康检查，心跳超时3分钟自动重启Scanner ✅

### 12. dry_run模式正确性
- **virtual_mode=True**: `_sync_save_order_and_position`跳过写入 ✅
- **save_state**: `skip_if_virtual=True`跳过 ✅
- **trade_mode判断**: `_init_broker_sim`中设置`_dry_run`标志 ✅
- **紧急平仓**: 交易时间检查仍生效(安全) ✅
- **竞价预选**: premarket_scan仍可运行(观察模式) ✅

## 构建验证
- **vite build**: ✅ 0 errors (12.34s)
- **pytest**: ✅ 1594 passed, 0 failed, 4 skipped (79.98s)

## 发现的风险点

### ⚠️ 中风险
1. **order_id非全局唯一**: `ORD{HHMMSS}{内存序号}`格式，进程重启后序号从0开始。同一天重启两次且恰好同一秒下单可能冲突。MongoDB的upsert by order_id可以防止数据覆盖，但可能丢失一笔交易。
   - 建议: 加入进程标识或UUID后缀

2. **_calc_cash_from_mongo_orders全表扫描**: `_recalc_account`每次都查全量filled orders。订单量增长后性能下降。
   - 建议: 增加缓存或只在_load_state时全量计算，后续增量更新

### 💡 低风险
3. **涨停成交概率使用random.random()**: 不确定性来源，但与回测模型对齐，属于设计选择
4. **ST股判断依赖stock_name**: 如果name未更新(ST摘帽)，可能用错误的涨跌停比例。已有`is_st`参数覆盖

## 结论
**实盘交易系统整体健康**。12个审查项全部通过，核心防护完备:
- 9层时间防护覆盖所有sell path
- 同步MongoDB写入保证崩溃安全
- 一致性校验+自动修复(v2.9.108)
- 虚拟模式数据隔离
- 独立风控线程+看门狗

2个中风险点均为理论场景，实际触发概率极低，可后续迭代优化。
