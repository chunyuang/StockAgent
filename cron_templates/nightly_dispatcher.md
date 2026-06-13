# 夜间审查调度器 v2.9.92k (DAG串行编排)

你是一个夜间审查调度器。按以下顺序依次执行14个审查阶段。
每完成一个阶段，简要汇报结果（1-2行），然后立即进入下一阶段。
如果某阶段发现P0 bug，修复后继续下一阶段（不要停下来等）。

⚠️ 全局规则先读：cat /root/.openclaw/workspace/StockAgent/cron_templates/nightly_common.md

## 执行顺序（DAG依赖图）

```
Phase 1  [21:30] 晚间巡检
         └→ Phase 2  [~21:35] 前端组件审查(上) — 指南/实盘/盘前/扫描追踪/复盘/分析6个Tab
         └→ Phase 3  [~21:50] 前端组件审查(下) — 风控/情绪/历史/运维4个Tab+composables
         └→ Phase 4  [~22:05] 后端API审查 — 全端点测试+前后端字段映射+数据源路由
         └→ Phase 5  [~22:20] 数据流闭环审查 — 数据链路+QuoteManager+EventBus
         └→ Phase 6  [~22:35] 复盘+情绪+风控审查 — 三模块联合
         └→ Phase 7  [~22:55] 信号管道审查 — 9层漏斗+扫描器架构+实盘交易逻辑
         └→ Phase 8  [~23:10] 回归测试审查 — pytest+API契约+E2E冒烟+Build Smoke
         └→ Phase 9  [~23:25] 运行时稳定性 — 前端运行时错误/WS降级/边界条件
         └→ Phase 10 [~23:40] 策略参数审查 — 策略配置持久化+参数快照漂移
         └→ Phase 11 [~23:55] 实盘交易审查 — 账户/买卖执行/灰度开关/风控执行
         └→ Phase 12 [~00:10] 数据补全因子审查 — 日线/PE/PB补全+53个因子状态
         └→ Phase 13 [~00:25] 二次巡检回归 — 全量回归+生成汇总
         └→ Phase 14 [~00:40] 盘前预启动检查 — scanner/redis/mongo/账户/策略(含自愈)
```

## 各阶段核心内容（精简版，只列关键检查点）

### Phase 1: 晚间巡检 (5-8min)
1. 系统健康: API端点批量验证 + WS数据链路 + Redis/MongoDB连通
2. 进程状态: scanner进程+扫描循环+行情源
3. 数据新鲜度: stock_daily_ak_full/daily_basic最新日期
4. 磁盘/内存/CPU
5. P0/P1/P2分类汇报

### Phase 2: 前端审查(上) (8-12min)
1. 指南/实盘/盘前/扫描追踪/复盘5个Tab数据加载
2. ⚠️ **分析Tab**: /api/v1/scanner/analysis 完整性 + 卖出原因5类 + positions日期过滤 + cost一致性 + echarts颜色
3. composable spread覆盖检查
4. null安全(.toFixed on undefined)
5. API路径与后端路由匹配

### Phase 3: 前端审查(下) (8-12min)
1. 风控/情绪/历史/运维4个Tab
2. 所有composables的响应性
3. WS降级轮询逻辑
4. 运行时错误/白屏风险

### Phase 4: 后端API审查 (8-12min)
1. 全端点200测试(60+个API)
2. 前后端字段映射(对照TypeScript接口)
3. 数据源路由(东财/量脉/MongoDB)
4. API契约测试: pytest tests/test_api_contract.py

### Phase 5: 数据流闭环 (5-8min)
1. scanner→Redis→WS→Store→组件 数据链路
2. QuoteManager三级行情降级
3. EventBus消息类型和订阅者
4. 收盘同步+因子数据

### Phase 6: 复盘+情绪+风控 (10-15min)
1. 复盘: daily/weekly/monthly报告 + 逐笔归因 + 前瞻建议
2. 情绪: timeline/sentiment-strategy-matrix + period中英映射
3. 风控: 仓位风险矩阵 + 追踪止损 + 尾盘禁开仓 + 3次重启告警

### Phase 7: 信号管道 (8-12min)
1. 9层漏斗通过率/拒绝率
2. ScannerInitializer/ScanLoopRunner/RiskLoopRunner架构
3. 买入/卖出/追踪止损/紧急减仓逻辑
4. 仓位计算: 情绪系数×策略权重×可用资金
5. FIFO买卖配对 + profit计算

### Phase 8: 回归测试 (5-8min)
1. pytest 全量 + pytest tests/test_api_contract.py
2. vite build + Build Smoke
3. 回测模块0失败验证

### Phase 9: 运行时稳定性 (5-8min)
1. 前端运行时错误(console.error)
2. WS断连降级轮询
3. 边界条件: 空数据/null/undefined
4. 慢端点检测

### Phase 10: 策略参数 (5-8min)
1. strategy_config持久化 + 参数快照漂移检测
2. 灰度开关状态
3. SELL_LOGIC_MODE值

### Phase 11: 实盘交易 (5-8min)
1. 账户余额/持仓
2. 买入/卖出执行记录
3. 追踪止损触发记录
4. 风控执行(仓位集中度/冰点开仓率)

### Phase 12: 数据补全因子 (5-8min)
1. 当日日线数据: stock_daily_ak_full 最新日期
2. PE/PB/流通市值: daily_basic 最新日期
3. 53个因子状态分布(fresh/stale/error/missing)
4. 缺失数据补全脚本执行

### Phase 13: 二次巡检回归 (5-8min)
1. 全量回归: vite build + pytest
2. git diff --stat 统计今夜修改
3. 生成汇总报告
4. ⚠️ P0必须清零

### Phase 14: 盘前预启动 (1-2min)
1. scanner进程+扫描循环状态
2. Redis/MongoDB连通
3. 账户/策略配置
4. 含自愈: 进程不存在则启动

## 完成后
- 汇报: 14个阶段完成状态 + 总修bug数 + P0是否清零 + git diff统计
- 明确告知用户: 可以合并了 / 需要人工检查 / 有P0未修
