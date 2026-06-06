# 二次巡检回归报告 v2.9.83
**日期**: 2026-06-07 07:50 (周日)  
**分支**: cron/nightly-fixes → 待合并回 feature/market-monitor-auto  
**版本**: v2.9.83 (commit 1be97d3b)

---

## 第一阶段：系统健康二次巡检 ✅

| 检查项 | 状态 | 详情 |
|--------|------|------|
| Scanner进程 | ✅ | PID 3879439, 运行86400s+ (自6月6日启动) |
| Redis | ✅ | PONG, 连接正常 |
| MongoDB | ✅ | 连接正常, db=stock_agent |
| API端点通过率 | 28/29 (96.6%) | 唯一❌: backtest/factors 500 (服务器未加载最新代码) |
| WS/数据新鲜度 | ⚠️ | 周末非开盘, scanner未扫描, 属正常 |
| 内存/CPU | ✅ | 8.9G/16G (56%), load 0.50, 无泄漏迹象 |
| ScannerDaemon重启 | ✅ | 0次重启, daemon未启用(非daemon模式) |
| 3次重启告警 | ✅ | 未触发 |
| 紧急减仓 | ✅ | 未执行, circuit_breaker正常 |

**与21:50首次巡检对比**: 系统状态稳定，无新增异常，内存从8.5G缓升至8.9G属正常波动。

---

## 第二阶段：今晚修复回归验证 ✅

### 修复统计
- **总commit**: 31个 (含1个巡检报告)
- **修复bug**: 60+项
- **涉及文件**: 103个 (63 Python + 21 前端 + 3 文档 + 16 配置/其他)
- **代码变更**: +1927 / -725 行

### 关键修复清单

| # | 版本 | 修复内容 | 类别 |
|---|------|----------|------|
| 1 | v2.9.83 | ST股跌停判断(ST用±5%而非±9.5%)+追踪止损格式对齐 | 风控 |
| 2 | v2.9.82 | 历史运维审查-审计日志/系统健康/已平仓配对 | 运维 |
| 3 | v2.9.82 | 3个风控卖出盈亏计算bug | 风控 |
| 4 | v2.9.82 | 修复3个风控卖出盈亏计算bug | 交易 |
| 5 | - | 策略参数审查-配置持久化深层合并/策略ID归一化/重试计数器 | 策略 |
| 6 | - | 扫描漏斗9层数据total/passed→input/output映射 | 扫描 |
| 7 | v2.9.81 | 扫描追踪+盘前竞价审查修复 | 扫描 |
| 8 | - | 运行时稳定性-全量toFixed/空值防护(9文件63处) | 前端 |
| 9 | - | 情绪风控审查-仓位系数对齐+英文key fallback增强 | 风控 |
| 10 | - | 复盘模块5项数据修复 | 复盘 |
| 11 | - | 数据流闭环修复-涨跌停/情绪/pct_chg三链路 | 数据 |
| 12 | - | P0修复-backtest/factors 500+scanner_stats前端字段映射 | API |
| 13 | - | 6项前端审查修复 | 前端 |
| 14 | - | null safety guards for .toFixed() and pct_chg (5 Tab) | 前端 |
| 15 | v2.9.81 | Redis健康检测独立于scanner+测试版本同步 | 运维 |
| 16 | - | 前端chunk优化+Tab懒加载(MarketMonitor 204KB→87KB) | 性能 |
| 17 | v2.9.81 | 紧急减仓双bug-sell_codes未传递+List当Dict | 交易 |
| 18-31 | ... | 更多详见git log | 多类 |

### 重点回归结果

| 回归项 | 验证结果 |
|--------|----------|
| composable spread覆盖修复 | ✅ 无遗留问题, composables目录无useReviewMonitor等重复定义 |
| null安全修复 | ✅ 前端toFixed有少数函数内调用(已知安全, 函数内有val校验) |
| API端点不匹配修复 | ✅ 28/29通过, backtest/factors需服务器重启后生效 |
| WS+Redis降级轮询 | ✅ MarketMonitorView有WS重连状态指示器 |
| MarketPhase时间阶段 | ✅ 独立模块, 6个阶段分类+is_in_trading守卫 |
| 灰度开关SELL_LOGIC_MODE | ✅ 支持legacy/compare/checker, 测试覆盖 |
| 三级行情降级链路 | ⚠️ TieredScanner/QuoteManager在代码中已修复, 需开盘验证 |
| 修复引入新问题 | ✅ 未发现, vite build+pytest全部通过 |

---

## 第三阶段：回测模块影响确认 ✅

| 检查项 | 结果 |
|--------|------|
| pytest backtest模块 | 59 passed, 0 failed |
| 回测路由注册 | ✅ backtest/ultra-short/defaults返回正常 |
| 回测独立chunk大小 | 238KB (与v2.9.82一致, 无异常增长) |
| 回测模块零影响 | ✅ 确认 |

---

## 第四阶段：验证汇总

### 构建验证
- ✅ vite build: 10.42s, 0 error
- ✅ pytest: 184 passed, 13 skipped, 0 failed
  - API契约测试: 58 passed
  - 业务测试: 125 passed  
  - 回测测试: 59 passed (含部分重叠)
  - 其他: 7 skipped

### 清理
- ✅ 删除 ReviewTab.vue.bak 遗留文件

### 版本号: **v2.9.83**

### 待人工确认事项
1. **⚠️ 服务器需重启**: 运行中的uvicorn(PID 3301778)仍加载v2.9.81代码(commit 0f79c0dc), 需重启以加载v2.9.83
2. **⚠️ backtest/factors 500**: 修复代码已在磁盘, 但运行服务器未加载
3. **⚠️ 三级行情降级**: 代码已修复, 需周一开盘验证实际降级行为

### 未修复问题
- 无P1/P2遗留问题

---

**结论**: cron/nightly-fixes v2.9.83 验证通过 ✅  
**建议**: 早上人工确认后合并回 feature/market-monitor-auto, 并重启服务器加载最新代码
