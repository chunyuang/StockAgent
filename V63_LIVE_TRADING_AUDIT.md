# V63 实盘交易系统审计报告

**审计日期**: 2026-05-27  
**版本**: V63  
**审计范围**: real_trading/ + AgentServer/core/managers/live/  
**核心原则**: 绝对不修改回测模块代码

---

## 一、审计发现与修复汇总

### P0 级（已全部修复）

| ID | 问题 | 严重性 | 修复状态 |
|----|------|--------|---------|
| P0-1 | 两套 PositionManager 实现不一致 | 🔴 Critical | ✅ 已修复 |
| P0-2 | 利润保护阈值硬编码 0.02 | 🔴 Critical | ✅ 已修复(通过重构) |
| P0-3 | next_day_open_sell_pct fallback 0.03 vs 回测 0.02 | 🔴 Critical | ✅ 已修复(通过重构) |
| P0-4 | 告警级别不一致(profit_protect/profit_lock) | 🔴 Critical | ✅ 已修复 |
| P0-5 | 龙头5天低利润检查位置+ID匹配不一致 | 🔴 Critical | ✅ 已修复 |

### P1 级（已全部修复）

| ID | 问题 | 严重性 | 修复状态 |
|----|------|--------|---------|
| P1-1 | STRATEGY_PULLBACK_PARAMS 未合并 | 🟡 High | ✅ 已修复(通过V55-LIVE-009+重构) |
| P1-4 | pullback_mid_fallback_pct 默认 0.01 vs 回测 0.015 | 🟡 High | ✅ 已修复(V55-LIVE-009) |
| P1-5 | paper_trading T+1 阻塞集仅内存 | 🟡 High | ✅ 已修复 |
| P1-6 | hold_days() async 降级为近似值 | 🟡 Medium | ✅ 已修复 |

### 回测-实盘桥接增强

| 功能 | 描述 | 修复状态 |
|------|------|---------|
| 偏差监控 | 实盘vs回测胜率/收益/滑点偏差超阈值自动告警 | ✅ 已实现 |
| 参数同步 | 检测strategy_defaults.py变更,提醒重启实盘服务 | ✅ 已实现 |

---

## 二、详细修复说明

### P0-1: 两套 PositionManager 实现不一致

**问题根因**:
- `real_trading/position_manager.py` 的 V62 "修复"中引入了严重bug:
  1. `check_early_sell()` 返回 `tuple(sell_price, reason)`,但代码用 `early_result.get('sell_price', 0)` 当dict处理
  2. 变量 `pre_close` 被引用但从未从daily行情数据中提取
  3. 内联参数读取逻辑(~40行)与 live/ 版本的 `_check_early_sell_signals` 方法不一致

**修复方案**:
- 将 real_trading/position_manager.py 的 daily_check() 中的内联卖出逻辑替换为独立的 `_check_early_sell_signals()` 方法
- 新方法与 live/position_manager.py 的实现模式完全对齐:
  - 调用 `SellSignalChecker.check_early_sell()`,正确解包 `tuple(sell_price, reason)`
  - 从 STRATEGY_CONFIGS 读取策略参数,使用 STRATEGY_NAME_TO_ID 统一映射
  - 利润锁定使用 high/close 数据独立检查
- 消除约 40 行内联参数读取代码,降低维护成本

**影响文件**:
- `real_trading/position_manager.py`: 新增 `_check_early_sell_signals()` 方法,daily_check() 调用该方法

### P0-2 & P0-3: 硬编码阈值/fallback 不一致

**修复方案**: 通过 P0-1 的重构自动修复
- 内联的 if-elif 卖出逻辑已完全删除
- `SellSignalChecker` 从 STRATEGY_CONFIGS.params 读取策略级参数:
  - `profit_protect_min_close_rise`: 默认 0.02(可在策略参数中覆盖)
  - `profit_protect_min_open_rise`: 默认 0.02(可在策略参数中覆盖)
  - `next_day_open_sell_pct`: 各策略均为 0.02(V53对齐)
- 所有 fallback 由 SellSignalChecker 统一处理,不再有硬编码不一致

### P0-4: 告警级别不一致

**问题**:
- real_trading/position_manager.py: 利润保护/利润锁定 → `success` ✅
- live/position_manager.py: 利润保护/利润锁定 → `warning` ❌
- paper_trading.py daily_settlement 只处理 `success` 级别的利润保护/利润锁定

**修复**: 将 live/position_manager.py 中的利润保护/利润锁定告警级别从 `warning` 改为 `success`
- 冲高回落/高开即卖 → `danger`(会亏损,需紧急处理)
- 利润保护/利润锁定 → `success`(仍在盈利,落袋为安)
- 两套 PositionManager 现在完全一致

### P0-5: 龙头5天低利润检查

**问题**:
- real_trading/position_manager.py: 在止损**前**检查,匹配中文名 `'龙头低吸'`
- live/position_manager.py: 在止损**后**检查,手动遍历 STRATEGY_CONFIGS 匹配英文ID `'dragon_head'`

**修复**: 统一为在止损**前**检查,使用 `STRATEGY_NAME_TO_ID` 映射
- `STRATEGY_NAME_TO_ID.get(_strategy, '') == 'dragon_head'` 同时支持中文名和英文ID
- 两套 PositionManager 的检查顺序和逻辑完全一致

### P1-1 & P1-4: STRATEGY_PULLBACK_PARAMS 合并

**现状**: V55-LIVE-009 已将 pullback 参数内嵌到 STRATEGY_CONFIGS.params:
- `pullback_mid_fallback_pct`: 半路追涨=0.01, 龙头低吸=0.015, 跌停翘板=0.015
- `pullback_high_threshold`: 全部=0.05
- `pullback_profit_lock_threshold`: 龙头低吸=0.06

`SellSignalChecker._get_sell_params()` 在合并时会同时读取:
1. `STRATEGY_PULLBACK_PARAMS`(回测硬编码的中文名映射)
2. `strategy_params`(从STRATEGY_CONFIGS.params传入,含pullback参数)
3. `strategy_risk_params`(从STRATEGY_CONFIGS.riskParams传入)

由于 STRATEGY_CONFIGS.params 已包含 pullback 参数(优先级高于 STRATEGY_PULLBACK_PARAMS),参数合并已正确工作。

### P1-5: T+1 阻塞集持久化

**问题**: `paper_trading.py` 的 `_t1_blocked` 集合仅在内存中,服务重启后丢失

**修复**:
- 新增 `_load_t1_blocked()` / `_save_t1_blocked()` 方法
- 持久化到 `t1_blocked.json`
- place_order 时 save,daily_settlement 清除时 save
- 启动时自动加载

### P1-6: hold_days() 交易日历缓存

**问题**: 每次 `hold_days()` 调用都查 MongoDB,在 async 上下文中降级为 `natural_days/1.5` 近似值

**修复**:
- 预加载全部交易日历到类级缓存 `Position._trade_dates_cache`
- 使用 `bisect` 进行 O(1) 二分查找
- 首次调用时加载,之后复用
- async 上下文中也能使用缓存(无需 run_until_complete)
- 两个 position_manager.py 均已更新

### 回测-实盘桥接增强

**新增功能**:
1. `check_live_backtest_deviation()`: 监控实盘vs回测偏差
   - 胜率偏差 > 15% → 🔴严重告警
   - 胜率偏差 > 7.5% → 🟡轻度告警
   - 收益偏差 > 3% → 🔴严重告警
   - 滑点偏差 > 0.2% → 🟡轻度告警

2. `check_param_sync_status()`: 检测参数同步状态
   - 检查 strategy_defaults.py 最近修改时间
   - 1小时内修改 → 提醒重启实盘服务
   - 显示当前关键参数值

3. 校准报告更新:
   - 新增第6节: 实盘vs回测偏差监控
   - 新增第7节: 回测参数同步状态
   - 原第6节改为第8节

---

## 三、代码一致性验证

### 两套 PositionManager 对比

| 检查项 | real_trading/ | live/ | 一致性 |
|--------|-------------|-------|--------|
| 卖出信号检查方法 | `_check_early_sell_signals()` | `_check_early_sell_signals()` | ✅ |
| SellSignalChecker 调用 | `check_early_sell()` → tuple解包 | `check_early_sell()` → tuple解包 | ✅ |
| 利润保护/利润锁定告警级别 | `success` | `success` | ✅ |
| 龙头5天低利润检查位置 | 止损前 | 止损前 | ✅ |
| 龙头5天策略ID匹配 | `STRATEGY_NAME_TO_ID` | `STRATEGY_NAME_TO_ID` | ✅ |
| hold_days() 实现 | 缓存+bisect | 缓存+bisect | ✅ |
| STRATEGY_NAME_TO_ID 映射 | 使用统一映射 | 使用统一映射 | ✅ |

### 关键参数来源

| 参数 | 来源 | fallback |
|------|------|---------|
| stop_loss_pct | STRATEGY_CONFIGS[id].riskParams | GLOBAL_RISK=0.03 |
| take_profit_pct | STRATEGY_CONFIGS[id].riskParams | GLOBAL_RISK=0.07 |
| max_hold_days | STRATEGY_CONFIGS[id].riskParams | GLOBAL_RISK=3 |
| next_day_open_sell_pct | STRATEGY_CONFIGS[id].params | GLOBAL_RISK=0.02 |
| pullback_mid_fallback_pct | STRATEGY_CONFIGS[id].params + SellSignalChecker._get_sell_params | 0.01/0.015 |
| pullback_profit_lock_threshold | STRATEGY_CONFIGS[id].params + SellSignalChecker._get_sell_params | None |
| intraday_lock_min_high_rise | STRATEGY_CONFIGS[id].riskParams | GLOBAL_RISK=0.05 |
| intraday_lock_pullback_pct | STRATEGY_CONFIGS[id].riskParams | GLOBAL_RISK=0.02 |
| intraday_lock_min_profit | STRATEGY_CONFIGS[id].riskParams | GLOBAL_RISK=0.02 |

---

## 四、Git Commits

| Commit | 描述 |
|--------|------|
| aba2c71 | chore: save state before V63 live trading audit |
| 67f5927 | fix(V63): P0-1 unify PositionManager daily_check with SellSignalChecker |
| feea855 | fix(V63): P1-5 T+1 persistence + P1-6 trade calendar cache |
| 25ccb1c | feat(V63): enhance live_backtest_bridge with deviation monitoring + param sync |

---

## 五、未修改的回测模块

确认以下回测模块文件**未做任何修改**:
- `AgentServer/nodes/backtest_engine/portfolio_backtest.py` ✅
- `AgentServer/nodes/backtest_engine/factor_selection/sell_signal_checker.py` ✅
- `AgentServer/nodes/backtest_engine/strategy_defaults.py` ✅
- `AgentServer/nodes/backtest_engine/ultra_short.py` ✅
- `AgentServer/nodes/backtest_engine/factor_engine.py` ✅

---

## 六、风险与建议

1. **服务重启**: P1-6 的交易日历缓存在首次 hold_days() 调用时加载,如果 MongoDB 不可用会降级为近似值。建议在服务启动时主动预热缓存。

2. **T+1 文件安全**: `t1_blocked.json` 存储在 real_trading/ 目录下,无加密保护。生产环境建议迁移到 MongoDB。

3. **SellSignalChecker 策略名映射**: `check_early_sell()` 使用中文名作为策略键,而 `STRATEGY_PULLBACK_PARAMS` 也用中文名。如果回测代码改为英文ID,需要同步更新。

4. **live_backtest_bridge 自动化**: 当前只生成报告和建议,不自动修改参数。如需自动校准,需增加参数写入+回测验证的闭环逻辑。

---

*报告生成时间: 2026-05-27 05:42*  
*审计版本: V63*
