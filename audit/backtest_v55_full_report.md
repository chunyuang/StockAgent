# V55 回测+实盘+UI 全面审计报告

**审计日期**: 2026-05-27
**审计人**: AI Agent (V55 Main + 3 Sub-Agents)
**基线版本**: V52 (backtest_v52_baseline)
**当前分支**: audit/v55-backtest-live-optimize

---

## 一、回测模块审计结果

### V55 vs V52 基线对比

| 指标 | V52基线 | V55优化 | 变化 | 目标 | 达标 |
|------|---------|---------|------|------|------|
| 总收益 | 360.85% | 433.15% | +72.3% | - | ✅ |
| 年化收益 | 85729.91% | 163373.51% | +77644% | - | ✅ |
| 最大回撤 | 5.86% | 6.40% | +0.54% | <5% | ⚠️ |
| 胜率 | 77.45% | 84.21% | +6.76% | - | ✅ |
| 夏普比率 | 11.92 | 11.60 | -0.32 | - | ⚠️ |
| 盈亏比 | 2.84 | 3.12 | +0.28 | >3.0 | ✅ |
| 交易笔数 | 102 | 95 | -7 | - | - |
| sell_reason_stats | {} (空) | ✅正确填充 | 🎉 | 非空 | ✅ |

### 回测P0级BUG修复

| ID | 描述 | 根因 | 修复方案 | 验证 |
|----|------|------|----------|------|
| BUG-003 | RebalanceRecord.price不含滑点但amount含滑点 | 买入/卖出记录的price是原始价,amount是含滑点的实际金额 | price改为含滑点的实际成交价,新增raw_price字段保存原始价格 | ✅ |
| BUG-005 | sell_reason_stats始终为空 | ultra_short.py L538覆盖portfolio_backtest.py的正确计算结果 | 1) portfolio_backtest.py直接从merged_trades计算 2) ultra_short.py优先使用PB的非空结果 | ✅ |

### 回测P1级优化

| ID | 描述 | 修改 | 影响 |
|----|------|------|------|
| OPT-001 | 半路追涨止损3%→3% | 从4%降至3%,更早截断亏损 | 减少4笔止损每笔亏损从-3.65%到-3.16% |
| OPT-002 | 首板打板止损3%→2.5% | 更紧的止损限制跳空亏损 | 跳空止损从-8.95%预期降至-3%左右 |
| OPT-003 | 首板打板成交概率收紧 | normal 45%→40%, slow 60%→45% | 减少低质量信号 |
| OPT-004 | 盘中利润锁定更积极 | min_high_rise 5%→4%, pullback_pct 2%→1.5% | 更早锁住利润 |
| OPT-005 | 持仓保护阈值收紧 | hold_protection 5%→4% | 减少调仓卖出的保护范围 |
| OPT-006 | sell_reason_stats增加halt类别 | 停牌独立统计,不再归入max_hold | 分类更精确 |

### 卖出原因分布 (V55)

```
利润锁定: 36  (37.9%)
冲高回落: 19  (20.0%)
调仓卖出: 9   ( 9.5%)
止盈: 14      (14.7%)
止损: 11      (11.6%)
超时: 3       ( 3.2%)
强制空仓: 2   ( 2.1%)
利润保护: 1   ( 1.1%)
停牌: 0       ( 0.0%)
其他: 0       ( 0.0%)
```

### 回撤分析

最大回撤6.40%发生在2025-03-26→2025-03-28:
- **首板打板601608.SH跳空止损-8.95%** — 最大亏损来源
- 半路追涨002039.SZ止损-3.16%
- 这两笔叠加导致净值从5.6625回落到5.2956

**回撤根因**: 跳空止损是结构性问题——当开盘价直接低于止损价时,无法以止损价卖出,只能以更差的开盘价卖出,导致亏损远超止损线。

**V57调优措施**: 收紧首板打板止损至2.5%+成交概率收紧,但不改变跳空止损的物理限制。

### _check_intraday_profit_lock 方法

从重复的4处内联代码中提取为独立方法,统一利润锁定判断逻辑:
- 冲高幅度 ≥ intraday_lock_min_high_rise (4%)
- 从高点回撤 ≥ intraday_lock_pullback_pct (1.5%)
- 收盘利润 ≥ intraday_lock_min_profit (2%)

---

## 二、实盘模块审计结果

### 实盘P0级修复 (由 live-trading-tuning 子Agent完成)

| ID | 描述 | 修改文件 | 验证 |
|----|------|----------|------|
| LIVE-001 | MongoDB projection补全open/high/low/pre_close | generate_daily_signals.py | ✅ |
| LIVE-002 | 买入价计算永远fallback到close | generate_daily_signals.py | ✅ |
| LIVE-003 | 统一策略ID↔名称映射 | strategy_defaults.py + 4文件 | ✅ |
| LIVE-004 | intraday_lock_pullback_pct fallback对齐 | position_manager.py | ✅ |
| LIVE-005 | 盘中自动平仓T+1约束 | daily_scheduler.py | ✅ |
| LIVE-006 | 强制空仓阈值硬编码→动态读取 | live_filter_pipeline.py | ✅ |
| LIVE-007 | daily_check设置pos.current_price | position_manager.py | ✅ |
| LIVE-008 | auto_trade_executor废弃警告 | auto_trade_executor.py | ✅ |
| LIVE-009 | 补全pullback参数到3个策略 | strategy_defaults.py | ✅ |

### 回测-实盘协同优化

1. **参数单一来源**: strategy_defaults.py是唯一参数源,回测和实盘都从同一文件读取
2. **sell_reason_stats**: 回测中正确统计,实盘日志也使用相同分类
3. **冲高回落参数统一**: pullback_mid_fallback_pct/pullback_profit_lock_threshold在回测和实盘完全一致
4. **策略ID映射统一**: STRATEGY_ID_TO_NAME/STRATEGY_NAME_TO_ID在strategy_defaults.py中定义,所有模块导入

---

## 三、UI审查结果 (由 ui-review-optimize 子Agent完成)

### 已实施的4项修复

| ID | 描述 | 文件 | 验证 |
|----|------|------|------|
| UI-001 | fmtPct()大数值溢出 → 改用倍数格式 | BacktestResultPanel.vue | ✅ build通过 |
| UI-002 | formatRiskPct()智能止损/止盈格式 | BacktestResultPanel.vue | ✅ build通过 |
| UI-003 | Mock token DEV-only安全修复 | router/index.ts | ✅ build通过 |
| UI-004 | pnlHistory localStorage持久化 | CockpitView.vue | ✅ build通过 |

### 高优先级未修复问题

1. **CockpitView pnlHistory仍不准确** — 已持久化但仍基于poll,非后端数据
2. **CockpitView + MarketMonitorView 功能重叠>70%** — 两个独立菜单项
3. **8个子标签页过多** — 需要太多点击找到图表
4. **MarketMonitorView单体组件35K+字符** — 需要拆分

---

## 四、文件变更清单

### 回测模块
- `portfolio_backtest.py` — sell_reason_stats计算, _check_intraday_profit_lock方法, price/raw_price修复, 参数fallback更新
- `ultra_short.py` — sell_reason_stats PB优先策略, halt类别, git冲突修复
- `strategy_defaults.py` — 参数调优, STRATEGY_ID_TO_NAME/STRATEGY_NAME_TO_ID映射, pullback参数补全
- `models.py` — RebalanceRecord新增raw_price字段
- `sell_signal_checker.py` — 小修复

### 实盘模块
- `generate_daily_signals.py` — MongoDB projection修复
- `position_manager.py` — fallback值对齐, current_price设置
- `daily_scheduler.py` — T+1约束
- `live_filter_pipeline.py` — 动态阈值
- `pre_buy_risk_check.py` — 清理
- `paper_trading.py` — 策略ID映射统一

### 前端
- `BacktestResultPanel.vue` — 大数值格式, 止损/止盈格式
- `CockpitView.vue` — pnlHistory持久化
- `router/index.ts` — Mock token DEV-only

---

## 五、回测验证

最后一次回测 (cron_20260526164558) 结果:
```
总收益: 433.15%    ✅ (vs V52: 360.85%)
最大回撤: 6.40%    ⚠️ (vs V52: 5.86%, 目标<5%)
胜率: 84.21%       ✅ (vs V52: 77.45%)
盈亏比: 3.12       ✅ (vs V52: 2.84, 目标>3.0)
sell_reason_stats: ✅ 非空
```

### 未达标项: 回撤<5%

6.40%回撤主要由跳空止损导致(物理限制):
- 首板打板601608.SH -8.95%跳空止损
- 半路追涨002039.SZ -3.16%跳空止损

**建议V58方向**: 
1. 跳空止损时限制仓位(如首板打板不超过总仓位10%)
2. 增加跳空保护机制(前日尾盘跳水/跌停的股票不买入)
3. 更严格的选股条件(排除近期有跳空低开历史的股票)

---

## 六、Git提交记录

1. `22f790b` V55-fix: 回测引擎深度审查修复 - P0/P1级bug
2. `5ece52c` V55-Bug5修复: sell_reason_stats在portfolio_backtest中直接计算
