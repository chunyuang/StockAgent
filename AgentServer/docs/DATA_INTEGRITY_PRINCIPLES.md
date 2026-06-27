# 数据有效性、逻辑统一性与持久性 — 设计原则与治理框架

> 2026-06-27 创建。基于 v2.9.98zf-35/36 审计中发现的系统性问题。

## 一、问题本质

我们今天发现的不是"某个字段写错了"，而是一个**系统性设计缺陷**：

**同一指标在3-5个地方独立计算，计算方式不同，但没有人校验它们应该一致。**

| 指标 | 独立计算位置 | 结果 |
|------|-------------|------|
| **已实现盈亏** | KPI(sum of profit_amount) / Account(total_assets-100万) / deviation-attribution(sum of profit_pct) | ¥7,356 vs ¥143,267 vs ¥0 |
| **胜率** | KPI(profit_pct>=0) / deviation-attribution(profit_pct>=0但未修正) / review-hero(同左) | 50% vs 100% vs 100% |
| **市值** | broker_accounts(cost*qty) / _get_account_from_mongo(close*qty) | ¥163,472 vs ¥143,267 |
| **年化收益** | KPI(复合年化) / 累计收益率 | 999.99% vs 11.21% |
| **资金曲线** | equityCurve(初始+已实现累计) / account.total_assets(含浮盈) | ¥1,007,356 vs ¥1,143,267 |

## 二、三条根本原则

### 原则1：单一真相源 (Single Source of Truth)

**任何指标只能有一个权威计算方式。** 其他地方必须引用，不能重算。

```
❌ 错误做法：
  scanner_analysis._compute_kpi() → 独立算total_profit
  _get_account_from_mongo()       → 独立算total_profit = total_assets - 100万
  deviation-attribution           → 独立算total_profit = sum(profit_pct)
  review-hero                     → 独立算win_rate = profit_pct >= 0

✅ 正确做法：
  _compute_kpi() 是唯一的盈亏/胜率/回撤计算入口
  其他所有API从kpi读取，不重算
```

**实施规则：**
1. KPI (盈亏/胜率/回撤/夏普等) → `_compute_kpi()` 唯一计算，结果存入返回值的 `kpi` 字段
2. Account (资产/现金/持仓) → `_get_account_from_mongo()` 唯一计算
3. 任何需要"已实现盈亏"的地方 → 读 `kpi.total_profit`，不重算
4. 任何需要"胜率"的地方 → 读 `kpi.win_rate`，不重算

### 原则2：写入时修正，不只读取时修补

**当前问题：broker_orders.profit_pct 在写入时就是0，每个读取API都需要各自修正。**

```
❌ 当前：写入=0，5个读取API各自修补
  scanner_analysis.py   → 修正逻辑1
  scanner_review.py     → 修正逻辑2
  scanner_trading.py    → 修正逻辑3
  (新增API时又忘记修正) → 新bug

✅ 应该：写入时就算对，读取时直接用
  broker.execute_sell() → 写入时计算 profit_pct = (sell_price - avg_cost) / avg_cost * 100
  所有读取API → 直接用 profit_pct，不需要修正
```

**实施规则：**
1. **卖出时**必须计算 profit_pct 和 profit_amount，写入 broker_orders
2. 数据源写入的值必须是最终值，不依赖后续修正
3. 如果某字段有"特殊处理"，必须在字段定义处用注释说明

### 原则3：交叉验证，不只独立检查

**23个cron全是"字段存不存在"，0个做"数据之间是否一致"。**

```
❌ 只做独立检查：
  profit_pct字段存在 → ✅
  (值=0也是"存在"的，没人发现不合理)

✅ 做交叉验证：
  profit_pct字段存在 → ✅
  profit_pct全0 → ❌ 不合理(10笔交易不可能全部0盈亏)
  KPI.total_profit ≠ Account.total_profit → ❌ 矛盾
  deviation-attribution.win_rate ≠ KPI.win_rate → ❌ 同一指标不同值
```

**实施规则：**
1. `data_consistency_guard.py` (cron ID: da279e5b) 每天跑一次
2. 新增任何计算指标时，必须在guard里加对应的交叉验证
3. 任何"同一指标多处出现"的，guard必须检查一致性

## 三、数据流标准

### 写入层（一次性正确）

| 写入操作 | 必须写入的字段 | 验证 |
|---------|--------------|------|
| broker.execute_buy() | ts_code, filled_price, filled_qty, strategy, avg_cost | filled_price > 0 |
| broker.execute_sell() | 同上 + **profit_pct**, **profit_amount**, reason | profit_pct = (sell-buy)/buy*100 |
| broker_positions 更新 | current_price (收盘价), market_value (收盘价*qty) | market_value = price * qty |
| broker_accounts 更新 | market_value (收盘价*总qty), total_assets | market_value = sum(position.market_value) |

### 读取层（从权威源读取）

| 需求 | 权威源 | 禁止 |
|------|--------|------|
| 已实现盈亏 | kpi.total_profit | ❌ total_assets - 1000000 |
| 未实现盈亏 | kpi.unrealized_pnl | ❌ account.market_value - account.total_cost |
| 总盈亏 | kpi.total_pnl_all | ❌ total_assets - 1000000 |
| 胜率 | kpi.win_rate | ❌ profit_pct >= 0 计数(修正前) |
| 年化收益 | kpi.annual_return (短期不年化) | ❌ 2天数据直接年化 |
| 最大回撤 | kpi.max_drawdown | ❌ 从资金曲线推算(不含浮盈) |

### 持久层（数据不可变+可追溯）

| 原则 | 实现 |
|------|------|
| 交易记录不可改 | broker_orders 是追加写入，不允许 update/delete |
| 持仓是持续状态 | broker_positions 随买卖更新，但保留 avg_cost 不变 |
| 历史可追溯 | runtime_snapshot 按(account_id, trade_date) upsert, TTL 30天 |
| 审计trail | risk_decisions 集合记录每个卖出决策 |

## 四、具体修复清单

### P0 — 根因修复（写入时修正）

- [ ] **broker.execute_sell() 必须计算 profit_pct** — 这是所有后续bug的根源
  - 当前：写入 profit_pct=0
  - 修正：profit_pct = round((filled_price - avg_cost) / avg_cost * 100, 2)
  - 修正：profit_amount = round((filled_price - avg_cost) * filled_qty, 2)
  - 修正后：所有读取API不再需要各自修补

### P1 — 统一读取（删除重复计算）

- [ ] **deviation-attribution** — 从kpi读取win_rate/total_profit，不重算
- [ ] **review-hero** — 从kpi读取，不重算
- [ ] **review-monthly** — 从kpi读取，不重算
- [ ] **weekly-review** — 已有fallback_pnl，但应统一

### P2 — 持久化修复

- [ ] **broker_accounts.market_value** — 应该用收盘价*qty，不是成本价*qty
- [ ] **broker_positions.current_price** — 盘后应刷新为收盘价
- [ ] **equityCurve** — 应包含浮盈浮亏日间变化(需要每日资产快照)

## 五、守卫与治理

### 自动守卫

| 守卫 | 频率 | 检查项 |
|------|------|--------|
| data_consistency_guard.py | 每天22:20 | 5项交叉验证 |
| mongodb_data_guard.py | 每天07:00 | trade_date类型/必填字段/重复数据 |
| check_params_alignment.py | 每天22:00 | 实盘vs回测参数 |

### 新增代码审查规则

1. **任何新增"盈亏/胜率/回撤"计算必须复用 `_compute_kpi()`**，不新写独立计算
2. **任何写入broker_orders/broker_positions的字段必须在写入时就是最终值**
3. **新增显示数字时，必须注明数据来源（kpi/account/直查）**
4. **修改计算逻辑时，必须更新 `data_consistency_guard.py` 的交叉验证**

## 六、历史教训索引

| 日期 | 问题 | 根因 | 对应原则 |
|------|------|------|----------|
| 2026-06-27 | 已实现盈亏虚高22倍 | 5个API独立计算realizedPnl | 原则1: 单一真相源 |
| 2026-06-27 | profit_pct全0 | 写入时不算，读取时各自修补 | 原则2: 写入时修正 |
| 2026-06-27 | 胜率100% | 同上，profit_pct=0导致>=0全True | 原则2: 写入时修正 |
| 2026-06-27 | 年化999.99% | 2天数据年化放大 | 原则1: 短期不年化 |
| 2026-06-27 | 守卫全通过 | 只检查字段存在，不检查值合理 | 原则3: 交叉验证 |
| 2026-06-15 | trade_date string vs int | 同一集合两种类型 | 原则2: 写入时归一化 |
| 2026-06-13 | 000517重复订单 | broker写入无幂等 | 持久层: 追加写入+去重 |
| 2026-04-20 | _get_prices返回空 | string date vs int date | 原则2: 写入时归一化 |
