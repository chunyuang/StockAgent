# V60 实盘交易审查报告

**日期**: 2026-05-27
**审查范围**: position_manager.py(686行), generate_daily_signals.py(572行), daily_scheduler.py(972行), paper_trading.py(631行)

---

## 回测-实盘对齐状态

### ✅ 已对齐
1. **止损止盈参数**: position_manager.add_position_by_signal() 从 STRATEGY_CONFIGS 读取策略级 SL/TP/hold_days
2. **冲高回落参数**: daily_check() 从 STRATEGY_CONFIGS 读取 pullback 阈值,与回测 SellSignalChecker 一致
3. **利润锁定参数**: 从 GLOBAL_RISK 读取 intraday_lock_* 参数,与回测 _check_intraday_profit_lock 一致
4. **跳空止损区分**: V50已修复, open<=stop_price → 跳空止损,与回测对齐
5. **持仓天数计算**: V35已修复,使用交易日而非自然日

### 🔧 V60新增对齐
1. **龙头5天低利润退出**: 实盘 daily_check() 新增告警,与回测 _check_and_execute_forced_sells 对齐
2. **STRATEGY_NAME_TO_ID**: 消除硬编码策略名映射,统一使用 strategy_defaults 中的映射

### ⚠️ 已知差异(可接受)
1. **pct_chg未来函数**: 回测中半路追涨用pct_chg≥5%作为收盘确认,实盘中9:25竞价后无法确认,需14:50人工判断
2. **成交概率模拟**: 回测中首板打板有hit_probability模拟,实盘中直接下单(实盘成交率由市场决定)
3. **滑点**: 回测统一扣0.2%-0.5%滑点,实盘滑点因盘口流动性而异

### 💡 回测-实盘相互助力建议
1. **实盘→回测**: 实盘交易记录可导入回测系统,验证回测模型与实盘的偏差
2. **回测→实盘**: 回测新参数(如跌停翘板pct_chg≥-1%)先在回测验证,再推送到实盘
3. **参数同步机制**: 建议增加配置校验接口,定期检查实盘参数是否与strategy_defaults一致

## 代码质量
- position_manager.py: 整体良好,错误处理完善
- daily_check(): 告警级别分类清晰(danger/warning/success)
- 交易历史持久化: JSON文件存储,简单可靠但不适合高频场景
- hold_days()异步问题: 在async上下文中用自然日/1.5近似,可能导致1天偏差

## 风险建议
1. 添加持仓集中度检查(同行业/同板块持仓上限)
2. 添加单日亏损上限检查(当日总亏损>2%时暂停交易)
3. 添加流动性检查(持仓股成交量骤降时告警)
