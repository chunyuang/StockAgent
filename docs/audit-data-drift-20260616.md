# 市场监听数据源漂移审计报告 v2.9.97

## 审计范围
全量扫描市场监听系统（后端 11 个 scanner API 文件 + 前端 8 个 composable + 9 个 Tab），识别"同一概念、多份数据源"的漂移隐患。

## 🔴 P0 级：已导致数据错乱的问题（3个已修 + 1个残留）

| # | 问题 | 状态 | 影响 |
|---|------|------|------|
| 1 | 分析每日明细从 `scanner_timeline` 读(含前日残留) | ✅ 已修→unified/trades | 15笔→10笔 |
| 2 | 复盘逐笔归因从 `broker_orders` 只读sell | ✅ 已修→unified/trades | 1笔→10笔 |
| 3 | useScannerMonitor.loadHistory 从 `scanner_timeline` 读 | ✅ 已修→unified/trades | 含幽灵交易 |
| 4 | **useAutoTradeMonitor 净值曲线 fallback 从 `scanner_timeline` 算** | ❌ 未修 | 资产曲线可能含幽灵交易 |

## 🟡 P1 级：scanner_timeline 仍是 4 个后端端点的数据源

| 端点 | 文件 | 读 scanner_timeline 原因 | 漂移风险 |
|------|------|--------------------------|----------|
| `/analysis` KPI计算 | scanner_analysis.py:171 | 卖出记录+profit → 算胜率/盈亏比 | **高** — timeline 可能含幽灵sell |
| `/analysis/stock/{code}` | scanner_analysis.py:455 | 个股全量交易记录 | **中** — 买入价可能不准 |
| `/trade-detail/{code}` | scanner_trading.py:395 | 买入决策链+卖出归因 | **中** — 先查timeline再查orders |
| `/export-trade-log` | scanner_trading.py:581 | 导出CSV合并timeline+orders | **低** — 导出用途, 不影响实时显示 |
| `/timeline/history` | scanner_core.py:446 | 历史时间线(已加对账过滤) | **中** — 前端已切换,但后端仍服务 |

## 🟡 P1 级：scanner_timeline 仍在写入

| 写入点 | 文件 | 行号 | 写入内容 |
|--------|------|------|----------|
| signal_manager._build_buy_timeline_entry | signal_manager.py | 681 | buy记录(含decision_detail) |
| RuntimePersistence.after_sell_success | runtime_persistence.py | 503 | sell记录(含profit) |
| RuntimePersistence._load_timeline | runtime_persistence.py | 332 | 启动时从MongoDB恢复 → insert_many |
| signal_manager._add_timeline_log | signal_manager.py | 多处 | blocked记录(信号被拒) |
| position_checker (降级路径) | position_checker.py | 711 | sell记录(无RuntimePersistence时) |

**核心矛盾**：scanner_timeline 同时承载两个职责：
1. **交易记录**（buy/sell）→ 应走 broker_orders
2. **决策日志**（blocked/信号被拒）→ 只有 timeline 有

## 🟡 P1 级：持仓数据 3 条路径可能不一致

| 路径 | 数据源 | 现价来源 | 问题 |
|------|--------|----------|------|
| scanner.get_positions() | 内存 `broker.positions` | scanner 定期刷 | scanner 未运行时 current_price=0 |
| broker_positions (MongoDB) | 持久化 | save_state 时写入 | 可能过时(非实时) |
| _compute_positions_from_broker() | 从 broker_positions 重建 | stock_daily_ak_full.close | 历史价,非盘中价 |

**现状**：/all 端点做了交叉校验(scanner vs broker)，但 /status 和 /account 各自走不同路径。

## 🟢 P2 级：前端 composable 数据重叠

| 数据 | 获取位置 | 问题 |
|------|----------|------|
| 持仓列表 | useCoreMethods(/all) + useUnifiedData(/unified/positions) | 两份独立数据 |
| 今日交易 | useAutoTradeMonitor(已切unified) + useReviewMonitor(已切unified) | 已修,但 useUnifiedData 的 currentDate 未与 useScannerMonitor 联动 |
| 账户信息 | /all 的 account 字段 + /status 的 account 字段 | 两个端点返回结构略有不同 |
| 信号列表 | /all 的 signals + /signals 独立端点 | /all 包含,但 /signals 不含 positions |

## 🟢 P2 级：已废弃但未清理的端点

| 端点 | 状态 | 建议 |
|------|------|------|
| `/positions` | 前端不再调用 | 保留(不影响) |
| `/signals` | 前端不再调用 | 保留 |
| `/account` | 仅 status 用 | 保留 |
| `/trade-attribution` | 前端已切 unified | 保留为只读回退 |
| `/auto-trades` | 前端已切 unified | 保留为只读回退 |
| `/reconcile-timeline` | 对账用 | 保留(运维需要) |

## 📋 修复优先级建议

### 立即修 (本次 follow-up)
1. **useAutoTradeMonitor 净值曲线 fallback** — `scanner/timeline/history` → `unified/trades`
2. **scanner_analysis.py KPI 计算** — `scanner_timeline` → `broker_orders` (只读 sell)
3. **scanner_analysis.py 个股详情** — `scanner_timeline` → `broker_orders`

### 下一步 (架构优化)
4. **scanner_timeline 职责拆分**：
   - 保留 `blocked` 记录写入（决策日志，只有 timeline 有）
   - `buy/sell` 记录停止写入 scanner_timeline，统一走 broker_orders
   - 旧 `/timeline/history` API 改为从 broker_orders 实时计算
5. **持仓数据统一**：所有持仓查询走 unified/positions，不再有 scanner 内存 vs MongoDB 两条路
6. **前端 composable 合并**：useCoreMethods 的 positions/timeline 数据改为从 useUnifiedData 读取

### 长期
7. **scanner_timeline 集合重命名**为 `scanner_decision_log`，彻底断开"交易记录"的语义
8. **统一实时价格源**：持仓的 current_price 统一从实时行情获取，不再依赖 save_state 时的快照
