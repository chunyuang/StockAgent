# 后端API审查报告 — 2026-07-10

**分支**: cron/nightly-fixes (已merge feature/market-monitor-auto)
**时间**: 00:13 ~ 01:00

---

## Phase 0: Issue队列
✅ 待修队列为空

---

## Phase 1: 全端点测试结果

| 指标 | 值 |
|------|------|
| OpenAPI注册端点 | 205 |
| GET端点(无path参数) | 136 |
| 测试通过 | 131 ✅ |
| 422(缺少必填query参数) | 2 (正常) |
| 401(需认证) | 4 (正常) |
| 超时(>5s) | 1 |

### 慢端点 (>1s)

| 端点 | 耗时 | 说明 |
|------|------|------|
| `/api/v1/admin/db/stats` | ~5s | MongoDB全库统计,可接受 |
| `/api/v1/factor/batch-view` | ~4s | 因子批量查询,数据量大 |
| `/api/v1/system/auto-fill-detect` | ~4s | 数据完整性扫描 |
| `/api/v1/system/data-status` | ~3s | 多集合状态检查 |
| `/api/v1/scanner/factor-effectiveness` | ~1.4s | 因子效果分析 |
| `/api/v1/scanner/timeline/history` | ~0.9s | 历史时间线聚合 |

### 422端点 (正常 - 缺少必填参数)
1. `/api/v1/stocks/search` → 需要 `?keyword=xxx`
2. `/api/v1/factor/view` → 需要 `?ts_code=xxx`

### 401端点 (正常 - 需要JWT认证)
1. `/api/v1/users/me`
2. `/api/v1/users/me/preferences`
3. `/api/v1/users/me/watchlist`
4. `/api/v1/backtest/history`

### 参数化GET端点测试

| 端点 | 状态 | 说明 |
|------|------|------|
| `/api/v1/stocks/600036.SH/basic` | ✅ 200 | 143B |
| `/api/v1/stocks/600036.SH/daily` | ✅ 200 | 24KB, pct_chg=-1.03 |
| `/api/v1/scanner/kline/600036.SH` | ✅ 200 | 4.4KB |
| `/api/v1/scanner/quote/600036.SH` | ✅ 200 | 非交易时间→MongoDB回退 |
| `/api/v1/scanner/analysis/stock/600036.SH` | ✅ 200 | 57B |
| `/api/v1/stocks/by-industry/银行` | ✅ 200 | 空数组(URL编码问题,实际需%编码) |

---

## Phase 2: 字段映射审查

### 2.1 ScannerPosition 字段对比

| 前端Store (scanner.ts) | API响应 | 状态 |
|------------------------|---------|------|
| avg_cost | cost_price | ⚠️ 名称不匹配 |
| total_qty | shares | ⚠️ 名称不匹配 |
| profit_pct | profit_pct | ✅ |
| available_qty | available_qty | ✅ |
| stop_loss_price | stop_loss_price | ✅ |
| take_profit_price | take_profit_price | ✅ |

**结论**: Monitor主视图(MarketMonitorView/OpsTab/AccountTab/AnalysisTab)均直接使用API字段名(cost_price/shares),
scanner.ts中的ScannerPosition接口定义是旧的,但实际Monitor代码通过useScannerMonitor.ts的PositionInfo接口使用了正确的字段名。
**不构成bug,但scanner.ts的接口定义需要同步更新以避免混淆。**

### 2.2 pct_chg 正负号约定

- 后端返回: float, 如 `-1.03` (表示跌1.03%)
- 前端展示: `pct_chg > 0 ? '+' : ''` + `.toFixed(1)` + `%`
- **约定一致** ✅

### 2.3 None vs null

- 后端Pydantic Optional[float]字段 → JSON中为 `null`
- 前端处理: `v != null` 或 `v || 0` 均可正确处理
- **stock_daily的change字段**: MongoDB中部分文档为None, JSON序列化为null, 前端不直接使用此字段
- **无NaN/Infinity问题** ✅

### 2.4 止损止盈百分比

- 后端positions返回: 百分比格式 (3.0 = 3%)
- 后端params/strategy-config存储: 小数格式 (0.03 = 3%)
- 前端`normalizePct()`函数统一处理: `< 1` 则 `×100`
- **约定一致** ✅

---

## Phase 3: 数据源路由审查

### 3.1 各API数据源

| API | 数据源 | 非交易时间回退 |
|-----|--------|--------------|
| `/stocks/realtime` | MongoDB最新日线 | ✅ 自动 |
| `/scanner/quote/{ts_code}` | Scanner缓存→Broker缓存→东财→必盈→MongoDB | ✅ v2.9.99优化跳过东财/必盈 |
| `/scanner/kline/{ts_code}` | MongoDB | N/A(历史数据) |
| `/scanner/positions` | Scanner内存→MongoDB broker_positions | ✅ |
| `/unified/trades` | MongoDB broker_orders | ✅ |
| `/unified/positions` | MongoDB broker_positions | ✅ |
| `/scanner/market-sentiment` | Scanner内存 | ✅ |
| `/scanner/limit-pools` | Scanner内存/必盈 | ✅ |
| `/factor/*` | MongoDB daily_factors | ✅ |
| `/system/data-status` | MongoDB多集合 | ✅ |

### 3.2 unified.py API覆盖率

| API | 覆盖场景 | 状态 |
|-----|---------|------|
| `GET /unified/trades` | 统一交易查询(broker_orders) | ✅ |
| `GET /unified/positions` | 统一持仓(broker_positions) | ✅ |
| `GET /unified/date-availability` | 有交易数据的日期列表 | ✅ |

**缺失**: 无账户汇总/净值曲线API — 但由scanner/account和scanner/weekly-report补充

### 3.3 非交易时间行为验证

- `/scanner/quote/600036.SH` 非交易时间: ✅ 正确跳过东财/必盈,直接MongoDB回退
- 量脉适配器: 仅用于scanner盘中1min K线,API层不直接调用 ✅
- 东财适配器: 仅在交易时间且scanner/broker缓存miss时使用 ✅

---

## 构建与测试

| 检查项 | 状态 |
|--------|------|
| vite build | ✅ 12.74s |
| pytest (1883 tests) | ✅ 0 failed, 8 skipped |
| API contract snapshot | ✅ 已更新(board_distribution自然变动) |

---

## 需关注项

1. **scanner.ts ScannerPosition接口过时** — avg_cost→cost_price, total_qty→shares 未同步,不影响运行但易混淆
2. **慢端点** — admin/db/stats, factor/batch-view, system/auto-fill-detect >3s, 非关键可优化
3. **by-industry中文编码** — URL中中文需%编码,前端应使用encodeURIComponent
