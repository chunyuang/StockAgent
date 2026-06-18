# 市场监控系统安全审查报告 (2026-06-18)

## 🔴 P0: 已发生的事故

### 18:07盘后止损卖出 (已修复 v2.9.98)
- **根因**: API触发scan_once → _check_positions → _execute_sell_list，无交易时间检查
- **影响**: 6笔卖出在18:07执行(市场已关闭)，6只持仓被错误清空
- **修复**: _execute_sell_list + _check_stop_loss_only + execute_sell_list_from_risk 三层加MarketPhase检查

---

## 🔴 P1: 严重风险(未发生但随时可能触发)

### P1-1: daemon紧急减仓无时间检查
- **文件**: `daemon_watchdog_mixin.py:183`
- **问题**: `_emergency_reduce_positions` 直接调 `broker.place_order(side="sell")`
- **场景**: scanner多次重启 → daemon在盘后触发紧急减仓 → 盘后清仓
- **风险等级**: 高(daemon重启常发生在非交易时间)

### P1-2: risk_watchdog紧急平仓无时间检查
- **文件**: `risk_watchdog.py:664`
- **问题**: `_liquidate_positions` 直接调 `broker.place_order(side="sell")`
- **场景**: 风控检查触发紧急平仓 → 盘后执行
- **风险等级**: 高

### P1-3: position_manager.execute_risk_sell无时间检查
- **文件**: `position_manager.py:902`
- **问题**: risk_thread路径的execute_risk_sell直接调broker.place_order
- **场景**: 虽然risk_loop有非交易时间sleep，但如有bug导致risk_thread在盘后运行
- **风险等级**: 中(已有_risk_non_trading_sleep保护，但缺独立检查)

### P1-4: position_manager.liquidate_positions无时间检查
- **文件**: `position_manager.py:948`
- **问题**: 强制空仓/清仓的公共方法，直接调broker.place_order
- **场景**: 被_execute_force_empty或_sell_all_positions调用时
- **风险等级**: 中(调用方_can_execute_force_empty_now有检查，但liquidate_positions本身没有)

### P1-5: scan_once被API触发时无交易时间门控
- **文件**: `scanner_trading.py:264`
- **问题**: API `/scanner/scan-once` 可以在任何时间触发scan_once(force=True)
- **场景**: 用户在盘后点击扫描 → 触发scan_once → _check_positions → 卖出
- **风险等级**: 高(今天事故的直接触发点)

### P1-6: 行情缓存过期导致决策错误
- **文件**: `risk_loop_runner.py`
- **问题**: 非交易时间realtime_cache不会更新，但cache中仍有3小时前的旧数据
- **场景**: 盘后risk_loop如果被唤醒，用旧数据做止损判断 → 基于错误价格卖出
- **风险等级**: 中(已通过v2.9.98修复的交易时间检查间接防护)

---

## 🟡 P2: 中等风险

### P2-1: 情绪调仓卖出无时间检查
- **文件**: `emotion_cycle.py:617`
- **问题**: `_execute_emotion_batch_sell` 委托给 `execute_sell_list` → 现已有时间检查(v2.9.98修复)
- **状态**: 已通过v2.9.98间接修复 ✅

### P2-2: broker.place_order的保护是最后防线(但非100%可靠)
- **文件**: `broker.py:734`
- **问题**: `is_continuous_auction()` 检查是今天14:06才加的(v2.9.97h-v9)
- **风险**: 如果scanner进程没重启，旧代码仍在运行，无此保护
- **建议**: 确保scanner进程重启

### P2-3: scanner.py:1298 直接调broker.place_order
- **文件**: `scanner.py:1298`
- **问题**: _execute_force_empty内部直接调broker.place_order
- **状态**: 调用方_can_execute_force_empty_now有is_continuous_auction检查 ✅

### P2-4: signal_manager买入有时间检查 ✅
- **文件**: `signal_manager.py:527`
- **状态**: _execute_signals有非交易时间检查，正确跳过 ✅

---

## 🟢 P3: 已有保护(安全)

### P3-1: broker.place_order is_continuous_auction 硬保护
- 最终防线，所有place_order调用都经过此检查
- 但仅限v2.9.97h-v9+版本

### P3-2: risk_loop _risk_non_trading_sleep
- 非交易时间sleep 30-300秒，不执行检查
- 但scan_once路径不受此控制

### P3-3: 强制空仓 _can_execute_force_empty_now
- 只有连续竞价时段才执行
- 安全 ✅

---

## 📋 修复计划

### 立即修复(今天)
1. ✅ _execute_sell_list 加时间检查 (v2.9.98已完成)
2. ✅ _check_stop_loss_only 加时间检查 (v2.9.98已完成)  
3. ✅ execute_sell_list_from_risk 加时间检查 (v2.9.98已完成)

### 本周修复
4. daemon_watchdog_mixin._emergency_reduce_positions 加时间检查
5. risk_watchdog._liquidate_positions 加时间检查
6. position_manager.execute_risk_sell 加时间检查
7. position_manager.liquidate_positions 加时间检查
8. API /scanner/scan-once 加非交易时间警告/限制

### 架构改进
9. 将broker.place_order的时间检查提升为"拒单+日志告警"双重机制
10. 所有卖出路径统一经过_execute_sell_list(单一出口+时间检查)
11. scan_once增加_force参数的审批机制(非交易时间force=True需确认)
