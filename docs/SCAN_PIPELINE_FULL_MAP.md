# 扫描-选股-拦截 全链路全景图

> 从全市场5800+只股票到最终成交买入，一只股票要经过哪些关卡？
> 本文档从代码层面完整梳理整个链路，含所有拦截类型和候选状态。

---

## 一、全局时间线：一个交易日发生了什么

```
时间        阶段              扫描行为                    产出
────────────────────────────────────────────────────────────────
09:00-09:15  PREMARKET(盘前)   仅持仓跳空检查              risk_decisions
09:15-09:25  PREMARKET(竞价)   竞价扫描(每60秒1次)          premarket_snapshots
09:25-09:30  AUCTION(集合竞价)  竞价扫描(每60秒1次)          premarket_snapshots
09:30-11:30  MORNING(早盘)     主扫描(30秒/次)+风控(1秒/次)  scan_traces + orders
11:30-13:00  LUNCH(午休)       仅风控止损检查               risk_decisions
13:00-14:30  AFTERNOON(午盘)   主扫描(30秒/次)+风控(1秒/次)  scan_traces + orders
14:30-15:00  LATE_TRADING(尾盘) 主扫描+风控，禁止新开仓       scan_traces
15:05+       AFTER_CLOSE(盘后)  结算+数据补全               equity_curve
```

---

## 二、两套扫描体系：竞价预选 vs 盘中主扫

### 2.1 竞价预选 (premarket_scan)

| 项目 | 详情 |
|------|------|
| **触发** | scanner启动时如果在09:15-09:30，立即跑1次；之后scan_loop每60秒调1次 |
| **频率** | 竞价窗口内约10次(09:15/09:16/09:17...09:25) |
| **数据源** | 量脉实时行情(force=True)，竞价价格=open=auction_price |
| **经过层** | Step1行情 → Step2补auction_pct → Step3因子合并 → Step4策略筛选 → **Step5 L1-L9全9层管道** |
| **执行交易** | ❌ 不执行！仅生成预览信号，存入premarket_snapshots |
| **存储** | MongoDB premarket_snapshots（每次扫描1条，含market_snapshot + candidates + funnel） |
| **前端** | /scanner/premarket-status API返回最新竞价候选 |

### 2.2 盘中主扫 (scan_once)

| 项目 | 详情 |
|------|------|
| **触发** | scan_loop_trading循环，动态间隔(早盘30秒/尾盘2分钟) |
| **数据源** | 量脉实时行情 |
| **经过层** | Step1行情 → Step2因子 → **Step3持仓检查(先卖后买)** → Step4策略+9层管道 → Step5信号更新 → Step6价格同步 → Step7持久化 |
| **执行交易** | ✅ 通过管道的信号进入execute_signals执行买入 |
| **存储** | scan_traces（每轮1条）+ scanner_timeline（每只股票1条）+ scanner_signals |

### 2.3 关键区别

| 维度 | 竞价预选 | 盘中主扫 |
|------|----------|----------|
| 目的 | 预览今日候选，不交易 | 实际执行交易 |
| 持仓检查 | 无 | ✅ 先卖后买 |
| 异动检测 | 无 | ✅ detect_anomalies |
| 信号过期 | 延长30分钟(翘板) | 默认300秒 |
| 执行下单 | ❌ | ✅ broker.execute_buy |

---

## 三、9层管道(L1-L9)：完整拦截类型

一只候选股从策略筛选到最终成交，要经过9层管道 + 执行层额外检查：

### L1 强制空仓 (force_empty)

| 项目 | 详情 |
|------|------|
| **条件** | 涨停数 ≤ 10 且 跌停数 ≥ 80（即"千股跌停"级灾难） |
| **动作** | 所有候选拒绝 + 清仓所有持仓 |
| **拦截记录** | `t.layer_results["L1_force_empty"] = {passed: False, reason: "强制空仓: 涨停X只≤10且跌停Y只"}` |
| **候选结果** | `final_rejection_layer = "L1_force_empty"` |

### L2 特殊时期 (special_period)

| 项目 | 详情 |
|------|------|
| **条件** | 月末/季末/节前/重大会议 |
| **动作** | 不直接淘汰候选，仅降低仓位比例(30%-70%) |
| **拦截记录** | `layer_details["L2_special_period"] = "📉 月末降仓(仓位×70%)"` |
| **候选结果** | 全部passed（降仓位不拦截具体股票） |

### L3 情绪周期 (sentiment)

| 项目 | 详情 |
|------|------|
| **计算** | 7维情绪模型(涨停/跌停/大盘/炸板/连板/首封/成交额) → score 0-100 |
| **周期** | euphoria(≥85) / rising(60-85) / differentiation(40-60) / bearish(20-40) / chaos/frozen(<20) |
| **动作1** | 冰点期(<40分): 过滤半路追涨+首板打板候选 |
| **动作2** | 非冰点: 不拦截具体股票，只影响仓位系数 |
| **拦截记录** | `layer_results["L3_sentiment"] = {passed: False, reason: "冰点期，过滤半路追涨X只"}` |
| **仓位系数** | euphoria=0.9, rising=0.7, differentiation=0.5, bearish=0.3, chaos/frozen=0.15 |

### L4 盘前预选 (premarket_filter)

| 项目 | 详情 |
|------|------|
| **排除条件** | ① ST/退市 ② 次新(上市<60天) ③ 低流动性(日成交<500万) ④ 北交所无list_date |
| **拦截记录** | 无明细(直接从候选列表移除) |
| **前端展示** | funnel中L4层: input=N, output=M |

### L5 竞价过滤 (auction_filter)

| 项目 | 详情 |
|------|------|
| **数据** | 从实时行情取开盘价/昨收 → 计算opening_pct_chg |
| **首板打板** | 竞价<2% → "首板竞价弱势" 拦截；竞价>7% → "一字板追不上" 拦截 |
| **其他策略** | 高开>7% → 拦截(追高)；低开<-5% → 拦截(有风险) |
| **拦截记录** | 无明细(直接从候选列表移除) |

### L6 策略量能 (strategy_filter)

| 项目 | 详情 |
|------|------|
| **说明** | 策略筛选在Phase0(strategy_scorer)已完成，此层仅标记 |
| **拦截** | 无(已在前置步骤筛选) |

### L7 综合排序 (ranking)

| 项目 | 详情 |
|------|------|
| **去重** | 同一只股票被多策略选中 → 取优先级最高的策略 |
| **优先级** | 龙头低吸(1) > 跌停翘板(2) > 首板打板(3) > 半路追涨(4) > 涨停开板(5) |
| **截断** | 最多保留10个候选(max_candidates_per_scan) |
| **拦截记录** | 排名靠后+超10 → 被截断 |

### L8 仓位控制 (position)

| 项目 | 详情 |
|------|------|
| **冷却期** | 该股票刚卖出N天内禁止再买(cooldown) → "🧊 冷却期(X天/Y交易日)" |
| **MA60** | 大盘跌破MA60 → 仓位×0.5 |
| **动态上限** | 按情绪周期调整MAX_POSITIONS: euphoria=10, differentiation=8, bearish=4, frozen=2 |
| **大盘风险** | buy_paused=True → 禁止新开仓 |
| **拦截记录** | `t.final_rejection_layer = "L8_cooldown"` / `"L8_ma60"` / `"L8_market_risk"` |

### L9 买入执行 (execute) — 管道外

| 项目 | 详情 |
|------|------|
| **说明** | L9由MarketScanner的execute_signals实现，不在pipeline内 |
| **默认状态** | 管道内标记 `L9_execute = {passed: True, reason: "管道筛选通过, 待执行"}` |
| **实际执行** | 见下方"执行层拦截" |

---

## 四、执行层拦截 (signal_manager.execute_signals)

管道通过后，信号进入execute_signals，还有以下拦截：

### E1 交易时间闸锁

| 条件 | 动作 |
|------|------|
| 非连续竞价时段 | signal_status=blocked, "非交易时间(XX), 不下单" |
| 尾盘(14:30-15:00) | buy信号blocked, "尾盘禁止新开仓" |
| 例外: 跌停翘板信号 | 竞价/午休阶段延退到交易时段，不blocked |

### E2 异动信号只观察

| 条件 | 动作 |
|------|------|
| strategy含"anomaly" | signal_status=skipped, "异动信号, 仅观察不自动交易" |

### E3 重复持仓

| 条件 | 动作 |
|------|------|
| 该股票已有持仓 | signal_status=skipped, "已有持仓, 跳过" |

### E4 风控熔断

| 条件 | 动作 |
|------|------|
| circuit_breaker.trading_paused=True | 所有后续信号blocked, "风控熔断·连亏N笔" |

### E5 持仓已满

| 条件 | 动作 |
|------|------|
| 当前持仓数 ≥ MAX_POSITIONS(动态上限) | signal_status=blocked + 移除信号(下轮可重试) |

### E6 价格异常

| 条件 | 动作 |
|------|------|
| sig.price ≤ 0 | blocked |

### E7 策略级选股过滤 (_check_strategy_params_filter)

| 编号 | 策略 | 条件 | 拦截原因 |
|------|------|------|----------|
| A4 | 首板打板 | 换手率<下限或>上限 | "换手X%<下限Y%" / "换手X%>上限Y%" |
| A4 | 首板打板 | 流通市值<下限或>上限 | "流通市值X亿<Y亿" / "流通市值X亿>Y亿" |
| A4 | 跌停翘板 | 换手率<下限 | "换手率X%<Y%" |
| A5a | 半路追涨 | 09:35前 | "半路追涨09:35前禁止" |
| A5b | 半路追涨 | 10:00后 | "半路追涨10点后禁止" |
| A6 | 龙头低吸 | 回调幅度<下限或>上限 | "回调X%<Y%" / "回调X%>Y%" |
| A7 | 全部 | 成交额<500万 | "流动性不足(成交额X万<500万)" |
| A10 | 高价股(>100元) | 偏离MA5>5% | "MA5超涨·高价股偏离+X%>+5%" |
| A10 | 低价股 | 低于MA5超2% | "MA5弱势·偏离-X%<-2%" |
| A11 | 涨停开板/翘板 | 周五 | "周五高风险策略不建仓" |
| A11 | 半路追涨 | 周五 | 减仓(25%→15%) |

---

## 五、数据存储：每个阶段的数据在哪

### 5.1 竞价阶段

| 集合 | 内容 | 时间 |
|------|------|------|
| `premarket_snapshots` | 每次竞价扫描的完整快照 | 09:15-09:30，约10条/天 |
| ↳ market_snapshot | 全市场涨跌/涨跌停统计 | |
| ↳ candidates | 通过L1-L9的竞价候选(最多20只) | |
| ↳ funnel | 漏斗: total_scanned → strategy_candidates → after_pipeline | |
| ↳ force_empty_confirm | 竞价风控状态机 | |

### 5.2 盘中阶段

| 集合 | 内容 | 时间 |
|------|------|------|
| `scan_traces` | 每轮扫描的9层管道详情 | 每30秒1次，约800条/天 |
| ↳ summary | total_stocks/candidates/passed + strategy_funnel | |
| ↳ layer_details | 每层的结果描述 | |
| ↳ candidates[] | 每只候选股的逐层结果 | |
| ↳ ↳ layer_results | {L1: {passed/reason}, L2: ..., L9: ...} | |
| ↳ ↳ final_rejection_layer | 最终被拒的层名(如"L3_sentiment") | |
| ↳ ↳ final_rejection_reason | 最终被拒的原因 | |
| `scanner_timeline` | 每只股票的action记录 | |
| ↳ action类型 | signal/blocked/skip/circuit/filtered/limit | |
| ↳ reason | 人类可读的拦截原因 | |
| ↳ layer_trace | 逐层trace(含execution层) | |
| `scanner_signals` | 当前活跃信号池 | |

### 5.3 交易阶段

| 集合 | 内容 |
|------|------|
| `broker_orders` | 买入/卖出订单(含reason/filled_price) |
| `risk_decisions` | 止损/止盈/跳空止损决策 |
| `broker_positions` | 当前持仓 |
| `broker_accounts` | 账户资金 |

---

## 六、候选状态流转

```
                ┌─────────────────────┐
                │  Phase0: 策略筛选    │  5800+只 → 10-50只候选
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │  L1-L8: 9层管道      │  10-50只 → 0-10只通过
                │  (每层可拦截)         │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │  L9: 管道标记通过     │  "管道筛选通过, 待执行"
                └──────────┬──────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
    ┌─────────▼──┐  ┌──────▼─────┐  ┌──▼──────────┐
    │ 竞价预选    │  │ 盘中执行    │  │ 异动信号     │
    │ 不执行交易  │  │ execute_    │  │ 仅观察       │
    │ 存snapshot │  │ signals()  │  │ skipped     │
    └────────────┘  └──────┬─────┘  └─────────────┘
                           │
                    ┌──────▼──────┐
                    │ E1-E7 拦截  │  交易时间/重复/熔断/
                    │             │  满仓/策略过滤/MA5/周五
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼─────┐ ┌───▼────┐ ┌─────▼──────┐
        │  blocked   │ │  skip  │ │  filled    │
        │  拦截/拒绝  │ │  跳过   │ │  成交买入   │
        └────────────┘ └────────┘ └────────────┘
```

---

## 七、当前可视化现状 vs 目标

### 现状
- **前端 ScanTraceTab.vue** 展示scan_traces，可看9层漏斗和候选通过/拒绝
- **前端 SignalTracePanel.vue** 展示scanner_timeline，可看每只股票的action
- **premarket-status API** 返回竞价候选，但前端未独立展示竞价时间线

### 目标
- 按时间线看所有候选的完整生命周期
- 竞价候选→盘中主扫候选→执行拦截→成交 的完整trace
- 每只候选都能看到在哪个阶段被拦截、拦截原因
- 竞价阶段的变化趋势(9:15的候选 vs 9:25的候选)
