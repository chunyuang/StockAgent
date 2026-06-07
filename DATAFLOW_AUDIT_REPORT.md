# 数据流闭环审查报告

**日期**: 2026-06-08 00:30 Asia/Shanghai  
**分支**: cron/nightly-fixes (58cdfd0c)  
**基线**: pytest 1775 passed ✅ | vite build ✅  

---

## 第一阶段：数据链路端到端验证

### 1. Scanner→Redis ✅
- **通道**: `_publish_scanner_event()` → Redis Stream(signal/position) + Pub/Sub(timeline/status)
- **信号**: `scanner:signal` Stream(maxlen=1000), `scanner:position` Stream(maxlen=5000)
- **状态**: `scanner:status` Pub/Sub, `scanner:timeline` Pub/Sub
- **问题**: ~~信号同时由`_publish_scanner_event`和EventBus subscriber写入scanner:signal，导致重复~~ → **已修复**

### 2. Redis→WS Bridge ✅
- **Stream消费**: `_redis_stream_consumer()` 用XREADGROUP消费signal/position，有ACK机制
- **Pub/Sub消费**: `_redis_listener()` 处理timeline/status
- **重连补发**: `catchup_scanner_stream()` 支持从last_id补发
- **问题**: ~~position增量通知无positions数组，bridge转发positions=[]给前端~~ → **已修复**

### 3. WS→前端Store ✅
- **消息分发**: `useWebSocket.ts` handleMessage() → scannerStore.updateFromWs()
- **类型映射**: scanner_signal→'signal', scanner_position→'position', scanner_timeline→'timeline', scanner_status→'status'
- **问题**: ~~scanner_signal只取signals[0]，丢弃后续信号~~ → **已修复**

### 4. 前端Store→组件渲染 ✅
- **Store→Ref同步**: `setupStoreWatchers()` watch scannerStore.signals/positions/timeline/status → refs
- **REST fallback**: fetchScanner()全量刷新(5s盘中/60s盘后)
- **渲染**: MarketMonitorView通过provide/inject获取refs，模板自动响应

### 5. wsDataStale逻辑 ⚠️→✅ 已修复
- **原始实现**: `computed(() => (Date.now() - lastWsDataTime.value) > 15000)`
- **问题**: `Date.now()`非响应式，computed不重算，WS断流15秒后wsDataStale仍为false
- **修复**: 改用`refs.nowMs.value`(每秒interval更新)，触发computed重算
- **降级行为**: wsDataStale=true时自动走REST轮询(5s/60s)

### 6. WS重连后数据恢复 ✅
- **watch(wsHook.isConnected)**: WS从断开→连接时主动fetchScanner()+fetchHealth()
- **重新订阅**: 自动发送subscribe_scanner
- **Stream补发**: 前端可传last_id从Redis Stream补发

---

## 第二阶段：QuoteManager+行情链路审查

### 7. QuoteManager._get_quote三级行情 ✅
- **Level 0(正常)**: 东方财富全市场5400只快照(免费，3秒)
- **Level 1(东财降级)**: 使用东财缓存或MongoDB日线
- **Level 2(日线缓存)**: 从MongoDB stock_daily_ak_full读取最近日线
- **非交易时间**: 直接用缓存，不阻塞
- **降级触发**: 连续3次失败→level 1，连续6次→level 2

### 8. TieredScanner三级行情 ✅
- **L1(5分钟/5400只)**: 东方财富全市场初筛(涨幅>3%+量比>1.5+非ST+流通市值>10亿)
- **L2(30秒/50-200只)**: 候选池策略筛选(复用回测条件)
- **L3(5秒/持仓+信号股)**: 实时止损止盈检查
- **回调接口**: on_l1_filter / on_l2_strategy / on_l3_check

### 9. 行情降级链路 ✅
- **降级**: Level 0 → Level 1(东财缓存) → Level 2(MongoDB日线)
- **L2→MongoDB**: `_fallback_to_mongo_daily()` 读取stock_daily_ak_full
- **L1→东财缓存**: `_build_realtime_from_cache(eastmoney._cache)`
- **每级fallback正确**: 实时→缓存→MongoDB历史，不会跳级

### 10. 行情陈旧检测 ✅
- **阈值**: 30秒(`get_staleness()`)
- **compute_health_score**: 正确调用`_quote_manager.get_staleness()`
- **health API**: `quote_staleness_seconds`反映真实延迟
- **前端数据新鲜度**: ScannerStore.dataFreshness(3s绿/5s黄/>5s红)

### 11. _try_recover_quote_source ✅
- **should_try_recover()**: 5分钟间隔(`_recover_interval=300.0`)
- **try_recover()**: 尝试重新获取东财数据，验证>100只=正常
- **恢复后**: 重置_quote_degrade_level=0, _quote_fail_count=0
- **事件发射**: quote_recovered事件(含degrade_duration_s)

### 12. scanner_event_bus.py审查 ✅
- **事件类型(8+2)**: signal_generated, position_changed, risk_sell_executed, circuit_breaker, scan_completed, quote_degraded, quote_recovered, param_updated, emotion_changed, daily_settled, scanner_error
- **订阅者**: 10组handler(审计日志/快照/Redis推送/健康度更新)
- **问题**: ~~signal_generated handler向scanner:signal Stream重复写入~~ → **已修复**

### 13. Pinia Store审查 ✅
- **核心state**: isRunning, positions, signals, timeline, health, account, sentiment, status, lastError
- **WS→Store**: updateFromWs() 增量更新(signal逐条/position全量/timeline增量/status覆盖)
- **REST→Store**: refreshFromApi() 全量刷新
- **Store→组件**: setupStoreWatchers() watch deep同步
- **问题**: ~~空数组positions=[]清空已有持仓~~ → **已修复**

---

## 第三阶段：收盘同步+因子数据审查

### 14. limit_pools→limit_list ✅
- **sync_close_data_to_mongo()**: 收盘后同步
- **_build_limit_ops()**: limit_up/limit_down/broken分别构建UpdateOne
- **数据**: 20260605有7634条(unique ts_code), 无重复
- **格式**: trade_date(int) + ts_code + limit(U/D) + limit_times + first_time/last_time

### 15. pct_chg→daily_basic ✅
- **_sync_pct_chg_to_daily_basic()**: 两步回填
  1. realtime_cache的pct_chg写入daily_basic
  2. stock_daily_ak_full回填未覆盖的(data_source标记来源)
- **数据**: 20260605有5514条daily_basic，全部有pct_chg
- **匹配条件**: `{"trade_date": td, "pct_chg": None}` — 只回填缺失的

### 16. broker._execute_sell盈亏计算 ✅
- **broker._execute_sell()**: `profit = (fill_price - pos.avg_cost) * qty - total_cost`
- **position_checker**: 优先用`order.filled_price`(实际成交价)而非`pos.current_price`(决策价)
- **post_sell_cleanup()**: 统一清理(timeline+统计+EventBus+持久化)
- **trace_id**: 贯穿timeline/EventBus/MongoDB，可追踪

### 17. 情绪预计算sentiment_scores ✅
- **precompute_sentiment.py**: 从limit_list+daily_basic计算每日情绪得分
- **数据**: 515条(20240506~20260605), 最新=20260605(周五)
- **周末缺失正常**: 6/6周六+6/7周日无数据
- **API**: scanner_report/review/debug均从sentiment_scores读取

### 18. FIFO买卖配对 ✅ (实际为加权平均法)
- **实现**: `avg_cost = (旧均价*旧数量 + 新价*新数量 + 佣金) / 新总数量`
- **非FIFO**: 模拟盘用加权平均法(avg_cost)更合理，FIFO适用于税务
- **加仓**: 正确重算均价含佣金
- **部分卖出**: 不改变avg_cost，盈亏计入total_profit

### 19. 53个因子状态分布 ✅
- **FactorLibrary.list_factors()**: 确认53个因子
- **分类**: momentum/value/quality/growth/volatility/liquidity/technical 7大类
- **daily因子**: stock_daily_ak_full中20个字段(pct_chg/ma5/macd/rsi_6/boll_upper/atr等)
- **basic因子**: daily_basic中PE/PB/流通市值/换手率等
- **数据完整性**: 20260605全部19/19因子字段有值

### 20. 因子更新引擎 ✅
- **FactorUpdateEngine**: 盘中增量/盘后全量/凌晨兜底
- **触发方式**: API `/scanner/factor-update` (scope=single/pool/market)
- **盘中**: is_trading_hours() → intraday
- **盘后**: is_postmarket_hours() → postmarket
- **凌晨兜底**: 预计算脚本precompute_sentiment.py可cron执行
- **局限**: market模式限制500只避免超时，需分批

### 21. 因子metadata映射和batch-view ✅
- **metadata API**: `/scanner/factor-metadata` — 分类/名称/描述/方向/数据源/更新类型
- **batch-view API**: `/scanner/factor/batch-view` — 批量查询因子值+状态
- **状态判定**: _determine_factor_status() — fresh(当日)/stale(非当日)/error/missing
- **分类中文标签**: 7类(momentum=动量/value=价值/quality=质量等)

---

## 第四阶段：修复+汇报

### 修复清单

| # | 严重度 | 问题 | 修复 | 文件 |
|---|--------|------|------|------|
| 1 | **P0** | scanner_signal WS消息含signals数组，前端只取[0]丢弃后续信号 | 遍历signals数组逐条updateFromWs | useWebSocket.ts |
| 2 | **P0** | signal_manager和EventBus subscriber同时向scanner:signal Stream写入，前端收到重复信号 | EventBus改推scanner:status Pub/Sub | scanner_event_subscribers.py |
| 3 | **P0** | position增量通知(position_changed)经WS bridge转发时positions=[]，Store赋值空数组清空已有持仓 | bridge区分全量/增量，Store空数组不覆盖 | redis_ws_bridge.py + scanner.ts |
| 4 | **P1** | wsDataStale computed用Date.now()(非响应式)，15秒后仍返回false | 改用refs.nowMs.value(每秒更新) | useCoreMethods.ts |

### 验证结果
- ✅ vite build: 成功(10.5s)
- ✅ pytest: 1775 passed, 0 failed
- ✅ test_v2914_redis_stream: 20 passed(适配新行为)

### 未修复但记录的问题

| # | 严重度 | 描述 | 建议 |
|---|--------|------|------|
| A | P2 | FactorUpdateEngine market模式限制500只 | 增加分批全市场更新 |
| B | P2 | scanner:position Stream只有增量通知，无全量推送 | 扫描循环应周期性推送全量positions |
| C | P3 | 前端dataFreshness基于lastWsUpdate，但WS连接初期可能一直red | 连接成功后首次fetchScanner也应更新lastWsUpdate |
| D | P3 | health API fallback路径quote_staleness_seconds硬编码999 | 虽不影响正常路径但应清理 |

### 数据完整性评估
- **stock_daily_ak_full**: 最新20260605, 全市场5400+只
- **daily_basic**: 最新20260605, 5514只, 全部有pct_chg
- **limit_list**: 最新20260605, 7634条(含涨跌停)
- **sentiment_scores**: 515条(20240506~20260605)
- **53因子**: 19/19 daily因子 + daily_basic因子，最新数据完整
