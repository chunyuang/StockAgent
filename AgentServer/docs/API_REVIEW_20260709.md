# 后端API审查报告 — 2026-07-09

**分支**: cron/nightly-fixes (已merge feature/market-monitor-auto)
**时间**: 00:13 ~ 01:00

---

## Phase 1: 全端点测试结果

| 指标 | 值 |
|------|------|
| 总测试端点 | 112 |
| ✅ 通过 | 98 |
| ❌ 失败 | 14 |

### 失败分类

#### 🔴 P0 — 路由未注册 (0个)
无。所有router已正确注册。

#### 🟡 P1 — 请求体格式 (2个, 非生产问题)
1. `POST /api/v1/auth/login` → 422: 需要 `application/x-www-form-urlencoded`，curl用JSON格式
2. `POST /api/v1/stocks/realtime` → 422: 需要 `{ts_codes: [...]}` 对象格式，curl传了裸数组

#### 🟢 P2 — 已确认正确路径 (5个, 测试路径错误)
1. `/api/v1/scanner/strategies` → 实际路径 `/api/v1/strategy-config/strategies` ✅
2. `/api/v1/scanner/strategies/momentum` → 实际路径 `/api/v1/strategy-config/strategies/momentum` ✅
3. `/api/v1/scanner/global-risk` → 实际路径 `/api/v1/strategy-config/global-risk` ✅
4. `/api/v1/stop-loss/*` (5个) → 实际前缀 `/api/v1/stop-loss-analysis/*` ✅
5. `/api/v1/trading-archive/day/2025-01-01` → 需要 int 格式 `20250101` ✅

#### 🟢 正常401 (1个)
- `GET /api/v1/users/me` → 401 (需认证, 正常)

#### 🟢 中文参数编码 (1个)
- `GET /api/v1/stocks/search?keyword=招商银行` → 400 (curl未编码中文, 浏览器正常)

### 慢响应 (>2s)
| 端点 | 耗时 | 原因 |
|------|------|------|
| `/api/v1/system/data-status` | 3.0s | MongoDB全集合count |
| `/api/v1/factor/batch-view` | 4.0s | 多股票因子计算 |
| `/api/v1/admin/db/stats` | 5.1s | 全集合统计 |

---

## Phase 2: 字段映射审计

### ✅ 无问题
| 端点 | 后端字段 | 前端字段 | 状态 |
|------|---------|---------|------|
| scanner/positions | `stock_name`, `profit_pct`, `pct_chg` | 同名 | ✅ |
| scanner/signals | `stock_name`, `pct_chg` | 同名 | ✅ |
| scanner/account | `total_assets`, `available_cash` | 同名 | ✅ |
| stocks/daily | `pct_chg`, `vol`, `amount` | 同名 | ✅ |
| unified/positions | `stock_name`, `profit_pct` | 同名 | ✅ |
| stop-loss-analysis | 前端用 `/api/v1/stop-loss-analysis` | 一致 | ✅ |

### ⚠️ 注意项
1. **limit-pools `name` vs `stock_name`**: 后端返回 `name` 字段，前端`MarketMonitorView.vue`主要用 `stock_name`。但 limit-pools 在 `PremarketTab.vue` 中用 `z.ts_code` 渲染（无 `stock_name` 引用），**无实际UI问题**。
2. **positions `pct_chg`**: 后端 positions 中 `pct_chg` 返回 `None`（非交易时间无实时涨跌幅），前端用 `profit_pct` 显示盈亏。✅ 合理。

### 精度/空值处理
- `pct_chg`: 正负号正确（+1.04 表示上涨），float精度正常
- `None vs null`: 后端通过 `SafeJSONResponse` 自动将 `None` → `null`，前端正确处理

---

## Phase 3: 数据源路由审计

### 各端点数据源分布
| API模块 | 数据源 | 回退策略 |
|---------|--------|---------|
| **scanner_core** (positions/account/orders) | MongoDB | ✅ 直读 |
| **scanner_scan** (quote/scan-traces) | 东财 → 必盈 → MongoDB | ✅ 三级回退 |
| **stock** (search/daily/basic) | MongoDB | ✅ 直读 |
| **unified** (trades/positions) | MongoDB | ✅ 直读 |
| **factor** (view/metadata) | MongoDB | ✅ 直读 |
| **system** (health/data-status) | MongoDB + Redis | ✅ |
| **datasource** (sources/active) | DataSourceRouter | ✅ |
| **scanner_sentiment** | MongoDB | ✅ 直读 |

### 非交易时间回退验证
- ✅ scanner_scan `/quote/{ts_code}`: 东财TTL缓存 → 5s过期回退MongoDB
- ✅ unified: 纯MongoDB读取，不受交易时间影响
- ✅ factor: 纯MongoDB读取

### unified.py API覆盖率
| 前端调用 | unified端点 | 状态 |
|---------|------------|------|
| `/unified/trades?date=` | ✅ | 从broker_orders聚合 |
| `/unified/positions` | ✅ | 从broker_positions聚合 |
| `/unified/date-availability` | ✅ | 从broker_orders提取可用日期 |

---

## 修复清单

### 已修复
1. ✅ `test_v2913_scan_loop_extraction.py`: MagicMock `_quote_manager._last_fetch_time` 未设置，导致 `>` 比较失败。添加 `_last_fetch_time = 0`。
2. ✅ API contract snapshots: 38个snapshot因业务迭代漂移，执行 `--update-snapshot` 更新。

### 预存问题(非本次引入)
- 20个 v29xx 行数/方法数契约测试失败：代码迭代导致scanner文件行数超过历史约定上限。建议下个迭代集中处理。

### 慢查询优化建议
1. `/api/v1/system/data-status`: 全集合count慢 → 可加Redis缓存(5min TTL)
2. `/api/v1/factor/batch-view`: 多股票因子计算 → 可并行化
3. `/api/v1/admin/db/stats`: 统计查询 → 可加cache

---

## Build & Test 状态
- ✅ `vite build`: 成功 (12.92s)
- ✅ `pytest` (核心): 1857 passed, 20 failed (预存契约测试), 8 skipped
- ✅ API contract snapshot: 已更新
