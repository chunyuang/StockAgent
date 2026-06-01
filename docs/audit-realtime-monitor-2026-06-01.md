# 🔍 实时监听WEB功能全面复盘审计报告

**审计时间**: 2026-06-01 21:50 CST  
**审计范围**: 实时监听所有WEB功能（后端WebSocket/Redis桥接/Market API/Scanner API/Trading API/System API + 前端监控视图/Store/Hook）  
**排除范围**: 回测功能模块（不影响）

---

## 一、架构总览

```
[Scanner后台] → Redis Pub/Sub + Stream → [RedisWSBridge] → [WebSocket] → [前端]
                                          ↗ (backtest:*/scheduler:*/scanner:*)
[Market API] ←→ MongoDB ← [ScannerDaemon]
[Scanner API] ←→ Scanner实例
[Trading API] ←→ SimTradingEngine ← MongoDB
[System API] ←→ MongoDB + 子进程

前端:
  MarketMonitorView.vue (主视图, ~1800行)
  ├── useWebSocket.ts (统一WS连接管理)
  ├── useScannerStore (Scanner状态, WS主通道+REST fallback)
  ├── useMarketStore (行情缓存)
  └── 各子组件 (SignalTracePanel, StrategyPerfBoard, PositionRiskMatrix等)
```

---

## 二、发现的问题（按严重程度排序）

### 🔴 P0 — 严重/安全隐患

#### 1. WebSocket Token泄漏到日志/URL
- **文件**: `frontend/src/hooks/useWebSocket.ts` L60-64
- **问题**: `getWsUrl()` 返回 `${baseUrl}/ws?token=***`，token实际拼入了完整URL。虽然代码中显示`***`，但实际`getWsUrl()`的返回值被传入`new WebSocket(getWsUrl())`，token会出现在浏览器DevTools的Network标签和WebSocket连接URL中。
- **代码**:
  ```typescript
  function getWsUrl(): string {
    const token = localStorage.getItem('access_token')
    const baseUrl = ...
    return `${baseUrl}/ws?token=***` // ← 这里实际上token被拼入了URL
  }
  ```
- **影响**: Token可能被浏览器历史、代理日志、DevTools记录
- **建议**: 改用WebSocket子协议或首条消息认证，避免将token放在URL中

#### 2. MarketMonitorView 直接操作WebSocket（绕过useWebSocket）
- **文件**: `frontend/src/views/monitor/MarketMonitorView.vue`
- **问题**: 主视图自己维护了 `let ws: WebSocket | null = null` 和独立的 `connectWs()`/`wsReconnectTimer`，与 `useWebSocket.ts` 的单例管理完全独立。存在两个WebSocket连接管理器并行运行的风险。
- **影响**: 可能建立双重WebSocket连接，造成消息重复消费、资源浪费
- **建议**: Scanner相关WS消息应通过 `useWebSocket` 的subscribe机制统一分发，或将MonitorView的WS逻辑迁移到 `useScannerStore` 的WS handler中

#### 3. Trading API 无权限隔离 — 任意account_id可访问
- **文件**: `AgentServer/nodes/web/api/trading.py` L135-165
- **问题**: `get_trading_signals()` 和 `get_performance_reports()` 不验证 `account_id` 归属。用户可以传入任意 `account_id` 查看其他用户的持仓和交易。
- **代码**:
  ```python
  @router.get("/signals")
  async def get_trading_signals(...):
      query = {}  # ← 没有user_id过滤
  ```
- **影响**: 越权访问其他用户的交易信号和绩效报告
- **建议**: 所有查询必须加 `user_id` 过滤条件

---

### 🟡 P1 — 功能缺陷/数据一致性

#### 4. Scanner Store的WS事件类型与Bridge推送类型不匹配
- **文件**: `frontend/src/stores/scanner.ts` `updateFromWs()` vs `redis_ws_bridge.py`
- **问题**: Store期望事件类型 `signal`/`position`/`timeline`/`status`，但Bridge推送的type是 `scanner_signal`/`scanner_position`/`scanner_timeline`/`scanner_status`。
- **代码对比**:
  ```typescript
  // scanner.ts updateFromWs()
  case 'signal': ...     // ← 期望 'signal'
  case 'position': ...   // ← 期望 'position'
  ```
  ```python
  # redis_ws_bridge.py
  msg = {"type": "scanner_signal", ...}  // ← 实际发送 'scanner_signal'
  ```
- **影响**: WS推送的Scanner事件无法被Store正确处理，`updateFromWs()` 永远走不到signal/position/timeline分支，导致前端只能依赖REST fallback刷新
- **建议**: 统一事件类型命名，或在前端消息分发层做映射

#### 5. MarketMonitorView的本地ws与Store的WS未协同
- **文件**: `MarketMonitorView.vue` L750-830（connectWs函数）
- **问题**: View组件自建WS连接后，消息更新的是组件本地的 `signals`/`positions`/`timeline` ref，而非 `useScannerStore`。Store的 `updateFromWs()` 从未被调用，Store的 `dataFreshness` 永远基于REST更新时间。
- **影响**: 
  - 数据新鲜度指示器不准（永远显示黄色/红色，因为WS更新时间不被Store记录）
  - 其他组件从Store读不到WS最新数据
- **建议**: View的WS handler应调用 `scannerStore.updateFromWs()` 而非直接修改本地ref

#### 6. Trading API 的 `get_positions` 每次查询都从MongoDB获取最新价
- **文件**: `trading.py` L135-165
- **问题**: 对每个持仓都执行 `db.stock_daily_ak_full.find_one({'ts_code': ts_code}, sort=[('trade_date', -1)])` 查最新收盘价。10个持仓 = 10次独立MongoDB查询，无索引优化。
- **影响**: 当持仓数量多时，API响应变慢；盘中实时价格用收盘价代替也不准确
- **建议**: 批量查询最新价格，或使用Scanner的QuoteManager获取盘中实时价

#### 7. RedisWSBridge的Stream消费者硬编码consumer_name
- **文件**: `redis_ws_bridge.py` `_redis_stream_consumer()`
- **问题**: `consumer_name = "web-node-1"` 硬编码。如果部署多个Web节点实例，所有实例用同一个consumer_name竞争消费，导致消息被随机分配到不同节点，部分客户端收不到消息。
- **影响**: 多实例部署时消息丢失
- **建议**: 使用主机名或UUID作为consumer_name

#### 8. realtime_monitor.py 直接依赖akshare获取大盘行情
- **文件**: `real_trading/realtime_monitor.py` L110-130
- **问题**: `_check_market_risk()` 用 `ak.stock_zh_index_spot_em()` 获取实时指数，但底层走东方财富，IP被封时同步不可用（TOOLS.md已记录此问题）。且获取全市场行情再筛选，数据量极大。
- **影响**: 监控模块在东方财富IP被封时完全失效
- **建议**: 优先使用已有的量脉/必盈API获取指数行情，akshare作为fallback

---

### 🟢 P2 — 代码质量/健壮性

#### 9. MarketMonitorView.vue 过于庞大（~1800行）
- **问题**: 单一组件包含策略编辑、手动交易、信号追踪、持仓管理、涨停池、情绪周期、系统健康等所有逻辑。难以维护和测试。
- **建议**: 拆分为更细粒度的子组件，业务逻辑抽取到composables

#### 10. System API的health_check在数据完整性检查中创建同步MongoDB连接
- **文件**: `system.py` health_check → data完整性检查
- **问题**: 使用 `pymongo.MongoClient` 创建同步连接，在async handler中同步阻塞事件循环。data-status接口也有同样问题。
- **影响**: 阻塞事件循环，影响其他并发请求
- **建议**: 改用motor（异步MongoDB驱动），或将同步操作放到线程池

#### 11. System API的sync-all使用subprocess.run + threading
- **文件**: `system.py` sync-daily-bar/sync-daily-basic/sync-factors/sync-all
- **问题**: 
  1. `subprocess.run(capture_output=True)` 在子线程中运行，但没有streaming输出，前端无法实时看到进度
  2. `_sync_tasks` 用线程锁保护但在线程和async间共享，存在竞态
  3. 脚本路径用 `os.path.dirname(__file__)` 向上3级找scripts目录，部署环境可能不匹配
- **建议**: 使用asyncio.create_subprocess_exec实现流式输出；统一用asyncio锁

#### 12. useWebSocket.ts 单例管理但不断开连接
- **文件**: `useWebSocket.ts` onUnmounted
- **问题**: `onUnmounted` 中注释"不断开连接，因为其他组件可能还在使用"，但没有引用计数或注册机制。如果最后一个使用者卸载，连接仍然保持。
- **建议**: 添加引用计数机制，最后一个subscriber卸载时断开连接

#### 13. MarketMonitorView 的 fetchScanner 没有并发控制
- **文件**: `MarketMonitorView.vue` fetchScanner()
- **问题**: autoRefresh定时器3秒调用一次fetchScanner，但如果上一次请求未返回，会叠加请求。无loading防重复机制（`loading` ref在fetchScanner中未使用）。
- **影响**: 网络慢时请求堆积，可能导致数据闪烁
- **建议**: 加AbortController或请求锁

#### 14. live_backtest_bridge.py 用asyncio.run()在同步函数中
- **文件**: `live_backtest_bridge.py` L47 `return asyncio.run(_load())`
- **问题**: 如果在已有事件循环的环境（如Jupyter/IPython）中调用，会抛出 "cannot be called from a running event loop" 错误。
- **建议**: 检测事件循环是否已运行，若是则用 `await` 而非 `asyncio.run()`

#### 15. Scanner Store timeline增量上限100条无配置
- **文件**: `scanner.ts` updateFromWs() timeline分支
- **问题**: `if (timeline.value.length > 100) timeline.value = timeline.value.slice(0, 100)`，硬编码100条上限。日内频繁交易场景可能丢失早期记录。
- **建议**: 将上限提升到200或可配置

---

### 🔵 P3 — 改进建议

#### 16. WebSocket消息格式不统一
- **问题**: 后端推送的消息格式有3种风格：
  - Backtest: `{"type": "log", "task_id": "...", "log": "..."}`
  - Scanner: `{"type": "scanner_signal", "signals": [...], "timestamp": "..."}`
  - Task: `{"type": "task_progress", "task_id": "...", "progress": 0.5}`
- **建议**: 定义统一的WS消息schema（含channel/type/version字段）

#### 17. 前端Scanner信号去重逻辑依赖ts_code+strategy组合
- **文件**: `scanner.ts` updateFromWs()
- **问题**: 同一只股票同策略的信号会被覆盖，无法追踪信号状态变化（如pending→executed）
- **建议**: 增加 `signal_id` 或 `created_at` 作为去重键

#### 18. realtime_monitor.py 使用sys.path.insert做模块查找
- **文件**: `realtime_monitor.py` L14
- **问题**: `sys.path.insert(0, ...)` 是反模式，已在代码中标注FIXME
- **建议**: 改用pyproject.toml将项目安装到venv中

#### 19. System API推送配置中包含敏感字段
- **文件**: `system.py` push-config相关接口
- **问题**: `feishu_app_secret` 等敏感信息通过API明文传输和存储在MongoDB中
- **建议**: 敏感字段加密存储，API返回时脱敏

#### 20. MarketMonitorView的emergencyLiquidate无二次确认保护
- **文件**: `MarketMonitorView.vue` quickSell/emergencyLiquidate
- **问题**: 虽然有 `showConfirm`，但一键清仓等高危操作缺乏风控后端校验。前端确认后直接调API，后端无延迟/审批机制。
- **建议**: 后端增加高危操作冷却期或审批机制

---

## 三、关键数据流问题总结

| 数据流 | 问题 | 严重程度 |
|--------|------|----------|
| Scanner→Redis Stream→Bridge→WS→前端Store | 事件类型名不匹配(scanner_signal vs signal) | 🔴 P1 |
| Scanner→Redis Stream→Bridge→WS→MonitorView | View自建WS绕过Store，数据不共享 | 🟡 P1 |
| WS Token认证 | Token暴露在URL中 | 🔴 P0 |
| Trading API查询 | 越权访问风险 | 🔴 P0 |
| 双WS连接管理 | View + useWebSocket并行 | 🟡 P1 |
| Stream消费者 | 多实例部署consumer_name冲突 | 🟡 P1 |

---

## 四、与回测模块的隔离确认

✅ **回测功能未被影响**:
1. Redis频道分离: 回测用 `backtest:*`，Scanner用 `scanner:*`，互不干扰
2. MongoDB集合分离: 回测读写 `backtest_tasks`，实盘读写 `sim_accounts`/`positions`/`trade_records`
3. API路由分离: 回测 `/backtest/*`，实盘 `/scanner/*`、`/trading/*`
4. Bridge的日志缓存已删除(方案C)，不影响回测日志推送
5. System API的health_check会检查回测引擎，但只读不写

⚠️ **潜在交叉点**:
1. `strategy_defaults.py` 是回测和实盘共用的参数配置文件，修改需同时验证两方
2. `live_backtest_bridge.py` 读取回测结果做校准，但只读不写回测数据
3. System API的sync-all补数据同时服务回测和实盘

---

## 五、修复优先级建议

| 优先级 | 问题编号 | 修复工作量 | 说明 |
|--------|---------|-----------|------|
| **立即** | #3 越权访问 | 小 | 加user_id过滤 |
| **立即** | #4 事件类型不匹配 | 小 | 统一命名或前端加映射 |
| **本周** | #1 Token泄漏 | 中 | 改用首条消息认证 |
| **本周** | #2 双WS管理 | 中 | View的WS逻辑迁入Store |
| **本周** | #5 Store未记录WS更新 | 小 | WS handler调用Store |
| **本周** | #7 Stream consumer_name | 小 | 改用动态标识 |
| **本月** | #6 持仓查询性能 | 中 | 批量查价 |
| **本月** | #9 组件拆分 | 大 | 技术债务 |
| **本月** | #10 同步MongoDB | 中 | 改用motor |
| **后续** | #11-20 | 各异 | 代码质量改进 |

---

## 六、审计覆盖文件清单

### 后端
- ✅ `nodes/web/websocket.py` — WebSocket连接管理
- ✅ `nodes/web/redis_ws_bridge.py` — Redis→WS桥接
- ✅ `nodes/web/api/market.py` — 市场行情API
- ✅ `nodes/web/api/scanner.py` — Scanner控制API
- ✅ `nodes/web/api/trading.py` — 实盘交易API
- ✅ `nodes/web/api/system.py` — 系统配置/健康/数据同步API
- ✅ `nodes/market_monitor/__init__.py` — Scanner模块入口
- ✅ `nodes/market_monitor/scanner_event_bus.py` — 事件总线
- ✅ `real_trading/realtime_monitor.py` — 盘中实时监控
- ✅ `real_trading/live_backtest_bridge.py` — 实盘回测校准

### 前端
- ✅ `views/monitor/MarketMonitorView.vue` — 主监控视图
- ✅ `hooks/useWebSocket.ts` — WS连接管理
- ✅ `stores/scanner.ts` — Scanner状态管理
- ✅ `stores/market.ts` — 行情缓存
- ✅ `api/modules/stock.ts` — 行情API
- ✅ `api/modules/trading.ts` — 交易API
