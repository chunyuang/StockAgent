# 夜间审查公共规则 v2.9.92k

## 分支策略
⚠️ 所有修改必须在 cron/nightly-fixes 分支上进行，禁止直接修改 feature/market-monitor-auto！
1. 任务开始: git checkout cron/nightly-fixes && git merge feature/market-monitor-auto --no-edit
2. 所有代码修改在 cron/nightly-fixes 上进行
3. 修复后验证: vite build + pytest + pytest tests/test_api_contract.py
4. ⚠️绝不自动合并！早上人工验证确认后才合并回 feature/market-monitor-auto
5. 如果 cron/nightly-fixes 不存在: git checkout -b cron/nightly-fixes feature/market-monitor-auto

## 通用注意事项
1. 别影响策略回测模块功能！改动前后都要跑 pytest 确认回测测试通过
2. 不要改变WEB页面布局！只修逻辑和数据，不动CSS布局
3. Vue3 composable 合并陷阱：...spread 展开后，后面单独列出的同名属性会覆盖！已踩坑3次
4. 数据源规则：历史数据读 MongoDB(无限)，盘中用东财 API(无限)或量脉(120次/分钟限)
5. 非开盘时间才读历史数据，开盘时间必须用实时数据
6. scoped CSS 不穿透子组件——提取组件时样式必须跟到子组件的 scoped 中
7. Vue 生产模式静默吞错误——所有 null ref 的属性访问必须加 ?. 可选链
8. commit 前必须验证：vite build + pytest，确认0失败
9. 每次修复后简要汇报改了什么、验证结果如何
10. 如果前面有任务没完成请先完成，再继续本任务内容

## AnalysisTab 检查项（所有前端审查任务必查）
- /api/v1/scanner/analysis 返回 kpi/sell_reasons/monthly/daily_detail/positions 字段完整
- KPI: total_trades/win_count/loss_count/profit_loss_ratio 非空且合理
- 卖出原因分类: 止损/跳空止损/追踪止损/冲高回落/利润保护 ≥5类
- positions 的 cost_price 与 get_stock_detail 的 avg_cost 一致
- positions 受日期过滤（选单日时持仓数应减少）
- 盈亏比用 profit_amount 均值比（非 pct 比例）
- 月度收益 monthly 的 cum_profit 累计正确

## Issue 闭环
任务开始前先读队列，P0 必须全部修完才继续本任务常规审查:

bash /root/.openclaw/workspace/StockAgent/scripts/cron_issues.sh list_open_for_fix

修完标 resolved:
bash /root/.openclaw/workspace/StockAgent/scripts/cron_issues.sh resolve <id> "<本cron名>" <commit_sha>

汇报含: 开始时待修数 / 本次修了几个(列id+commit) / 剩几个
