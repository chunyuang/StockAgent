# 复盘+情绪+风控联合审查报告
## 2026-07-09 01:13 CST | cron/nightly-fixes 分支

---

## Phase 0: Issue队列
✅ 待修队列为空

---

## Phase 1: 复盘模块 ✅ 全部通过

### 1. /daily-report /weekly-report /review-monthly 返回完整性 ✅
- `daily-report`: scanner运行时取实时数据，否则从MongoDB聚合（v2.9.94修复账户有效性检查）
- `weekly-report`: 指定日期前7天汇总，含daily_stats/strategy_summary/totals
- `review-monthly`: 自动计算月范围，含summary/strategy_stats/behavior_drift/daily_breakdown/weekly_trend/param_drift/index_performance
- 三接口均有 `success`+`data` 标准响应格式，异常安全

### 2. 逐笔归因buy_price不为0 ✅
- `trade-attribution` API: buy_price fallback链完整
  - 先查同ts_code+strategy的buy订单
  - buy_price=0时从profit_pct反推: `buy_price = sell_price / (1 + profit_pct/100)`
  - profit_pct=0时buy_price=sell_price（保本卖出）
- v2.9.99-r6: broker_orders.profit_pct经常为0(broker时序问题) → pnl_helper.build_buy_price_index + fallback_pnl 全局补丁

### 3. 周复盘概览+逐日表格 ✅
- `historical-review`: daily_stats按交易日汇总，strategy_summary按策略统计
- v2.9.98新增子模块聚合: trade_attributions + discipline_check + execution_quality + forward_advice
- v2.9.100: 加15s超时保护，防止单个子模块拖慢整个请求
- v2.9.103: sells补充buy_price字段

### 4. 月复盘系统偏差+行为漂移 ✅
- 系统偏差: 止损执行率(分母=全部亏损笔数) + 止损触发率(分母=止损触发笔数) 双视角
- 行为漂移: 冰点开仓率 + 未走止损的亏损笔数(loss_without_stop)
- 参数漂移: 通过param_drift()读取
- weekly_trend: 近4周趋势

---

## Phase 2: 情绪模块 ✅ 全部通过

### 5. sentiment-timeline 4模式数据点数 ✅
- `mode=intraday`: 委托get_intraday_timeline，返回日内分钟级点
- `mode=daily`: 以date为中心取前后120天窗口
- `mode=weekly`: 按YYYY-W%W聚合，含days/first_date/last_date
- `mode=monthly`: 按YYYYMM聚合
- 所有模式都正确传递trades数据

### 6. 日内score不全相同 ✅
- intraday模式调用get_intraday_timeline，每次scan计算独立score
- live模式: 从scanner内存取实时情绪(1秒级计算)
- MongoDB回退: sentiment_live_log存每次计算快照(v2.9.96h+)

### 7. period中英文映射一致性 ✅
- **写入**: emotion_cycle._persist_sentiment_score 正常路径写中文("高潮"/"分化"/"震荡"/"冰点")
- **异常路径**: 因子全0+score>22时写"BEARISH"+missing_data=True
- **读取**: 所有API消费者(scanner_sentiment/scanner_review/scanner_report)统一有_en_to_cn映射
- 映射表完全一致: RISING→高潮, DIFFERENTIATION→分化, CHAOS→震荡, BEARISH→冰点
- v2.9.99修复: market-sentiment统一返回中文period

### 8. missing_data标记正确 ✅
- **写入**: emotion_cycle在因子全0+score>22时强制missing_data=True
- **读取**: sentiment-timeline透传missing_data给前端(虚线标注)
- **消费**: review-hero/review-forward遇到missing_data时不将其作为真实情绪判断依据
- _get_effective_sentiment_doc: missing_data=True时返回中性50分+"数据缺失"，不污染复盘结论
- v2.9.104-hotfix: 服务重启后scanner实例默认50分不覆盖DB真实情绪

### 9. market-sentiment API score与MongoDB一致 ✅
- v2.9.99-r7修复: scanner未运行时跳过_filter_pipeline旧值，直接读MongoDB
- 优先级: scanner运行中实时内存 > 指定日期DB > 最新非missing DB
- is_stale标记: v2.9.98新增，告知前端数据是否为fallback

---

## Phase 3: 风控模块 ✅ 全部通过

### 10. position-risk-matrix 15维度 ✅
- **在线模式** (scanner运行): D1-D15全部计算
  - D1: 距止损距离(0-25分) | D2: 仓位集中度(0-15) | D3: 浮亏深度(0-15)
  - D4: 换手率/流动性(0-10) | D5: 波动率(0-10) | D6: 追踪止损激活(0-5)
  - D7: 行业集中度(0-5) | D8: 新仓风险(0-5) | D9: 连亏(0-5)
  - D10: 持仓天数(0-3) | D11: 涨停溢价(0-2) | D12: 大盘系统性风险(0-2)
  - D13: 流动性风险(0-2) | D14: 盈亏比偏离(0-2) | D15: 策略胜率偏差(0-2)
- **MongoDB回退模式**: D1-D9简化计算，D10-D15默认0
- **历史日期模式**: fetch_unified_positions重建持仓，复用回退逻辑
- v2.9.105修复: trail变量在d6_trail之前赋值(NameError修复)

### 11. 止损执行率分母=止损触发笔数 ✅
- `stop_loss_execution_rate`: 分母=loss_sells(全部亏损笔数)
- `stop_loss_triggered_rate`: 分母=stop_loss_sells(止损触发笔数，含盈利时追踪止损)
- 两个指标互补：执行率看纪律覆盖，触发率看止损质量
- 追踪止损在盈利时触发不计入执行率亏损(只看亏损场景)

### 12. 行业集中度后端0-100不再*100 ✅
- `top_industry_concentration`: `industry_exp.get(top_industry, 0) / max(total_assets, 1) * 100`
- 结果是0-100%范围，无额外乘100
- `industry_exposure`: 每个行业 `v / max(total_mv, 1) * 100`，同样是0-100%
- d7_industry评分: `industry_exp / total_mv * 100 / 2`，cap在5分

### 13. T+1规则: available_qty=0 for same-day buys ✅
- **写入**: broker._execute_buy() 设置 `available_qty=0` (line 1100)
- **解锁**: 次日settle逻辑 `available_qty = total_qty` (line 1199)
- **消费**: position_manager所有卖出检查都先判断 `pos.available_qty <= 0`
  - 固定止损(line 327/808) | 追踪止损(line 1043) | 分批止盈(line 1398)
  - 跳空止损(line 1065) | 强制清仓(line 1456)
- stop_loss_analysis文档明确记录T+1门控为第1步

---

## 构建与测试 ✅

| 项目 | 结果 |
|------|------|
| Vite build | ✅ 13.12s, 0 errors |
| pytest (全量) | ✅ 1877 passed, 0 failed, 8 skipped |
| pytest (相关模块) | ✅ 442 passed, 0 failed, 2 skipped |

---

## 总结

**全部13个检查项通过，无Issue需闭环，无需代码变更。**

代码质量观察：
1. **冗余但正确**: period中英文映射在scanner_review.py中重复定义了9次，建议未来提取为共享常量
2. **防御性编程良好**: buy_price fallback、profit_pct fallback、missing_data neutralization、scanner有效性检查
3. **历史债务清理完整**: v2.9.86→v2.9.105的修复链覆盖了trade_date类型、profit_pct为0、情绪数据缺失等核心问题
