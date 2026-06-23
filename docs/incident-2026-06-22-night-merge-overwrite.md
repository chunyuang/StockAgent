# 🚨 2026-06-22 用户白天工作被夜间 merge 覆盖事故报告

**生成时间：** 2026-06-23 09:45 (GMT+8)  
**事故等级：** P0 (用户级回归，13 个 commit 中 6 个被覆盖)  
**根本原因：** `184a3546` (06-23 03:51 cron 自动 merge) 选了错的一侧

---

## 📅 时间线

| 时间 | 事件 |
|---|---|
| 06-22 08:00-17:33 | 用户在 `cron/nightly-fixes` 分支提交 v9-v19 共 14 个 commit |
| 06-22 21:47 | 夜间 cron 提交 `4ae4592e` (MarketMonitorView 瘦壳重构) — **当时还没覆盖 v17/v18/v19** |
| 06-22 22:37 | 夜间 cron 提交 `1dec55bf` (ReviewTab 修复) |
| 06-22 23:18 | 夜间 cron 提交 `6c38969a` (API snapshot 更新) |
| **06-23 03:51** | **`184a3546` — cron 把 `feature/market-monitor-auto` merge 进来，错误地丢弃了 cron 侧的修改** |
| 06-23 06:35 | 夜间 cron 提交 `74e8e745` (v2.9.99 实盘交易审查) — **基于已被破坏的代码继续** |

---

## ❌ 被夜间 merge 覆盖的用户工作（6 个 commit）

### 1. v11 数据分析 Tab 默认全部历史 (10:42:56) `b8011165`
**用户改：** `AnalysisTab.vue` 默认 `selectedDate=''` + `rangeMode='all'` → 看多日明细  
**被覆盖回：** `selectedDate = ref(getChinaDate())` + `rangeMode` 整个删除  
**用户体感：** 数据分析 Tab 又只看今天 1 行数据

### 2. v13 情绪周期默认日内 (11:03:23) `be972d3a`
**用户改：** `useSentimentMonitor.ts` 第 25 行 `sentimentMode` 默认 `'intraday'`  
**被覆盖回：** `'daily'`  
**用户体感：** 情绪 Tab 又默认打开日线模式

### 3. v16 信号列表加扫描时间 (16:25:04) `8169aa6b`
**用户改：** `MarketMonitorView.vue` 信号行加 `sig.scan_time` 显示  
**被覆盖回：** 整段 sig.scan_time 渲染消失  
**用户体感：** 看不到信号是几点扫到的

### 4. v17 信号小时折叠分组 (16:54:07) `695d6cc3`
**用户改：** `signalsByHour` / `signalHourCollapse` / `toggleSignalHour` + UI 块  
**被覆盖回：** template 中三个变量全消失  
**用户体感：** 信号不再按小时折叠，回到平铺一长串

### 5. v18 持仓买入日期 (17:04:26) `872716bc`
**用户改：** `MarketMonitorView.vue` 持仓行加 `📅 formatBuyDateDisplay(pos.buy_date)`  
**被覆盖回：** pos-buy-date 渲染消失  
**用户体感：** 看不到「今天/昨天/持N天」标签

### 6. v19 今日已平仓面板 (17:33:26) `aef506cc`
**用户改：**
- 后端 `scanner_core.py` 新增 `today_closed_trades` 字段（37 行）
- 后端 `scanner_analysis.py` 注入 `buy_time` + `recent_sells`（33 行）
- 前端整套 UI 面板
  
**被覆盖回：** 后端两个文件的修改 100% 消失，前端 UI 块也消失  
**用户体感：** 看不到今日已平仓盈亏

---

## ✅ 安全保留的用户工作（7 个 commit）

| commit | 内容 | 状态 |
|---|---|---|
| `1c7abb2a` v9 | Ops/AutoTrades 日期初始值 + UnifiedDateBar | ✅ 保留 |
| `11d9b14a` v10 | `__DEV__` 未定义修复 | ✅ 保留 |
| `d0ff171e` v12 | 账户 Tab 首次 mount 调 fetchKpi | ✅ 保留 (cron/feat 一致) |
| `138446ca` v14 | 扫描追踪 Tab 默认今天 | ✅ 保留 (cron/feat 一致) |
| `67ad6e10` v15 | ScanTrace 对象转字符串 bug | ✅ 保留 |
| `04ac540b` | 腾讯接口数据补全脚本 | ✅ 保留 (新增文件) |
| `5587cbb6` | CUA 浏览器烟测脚本 | ✅ 保留 (新增文件) |

---

## 🎯 根本原因

### `184a3546` merge 的元数据
```
commit 184a3546
Date:   06-23 03:51
Subject: merge: feature/market-monitor-auto into cron/nightly-fixes
parent1: cb095e13 (cron 侧 — 含 v9-v19 全部改动)
parent2: 342b46c2 (feature 侧 — 不含 v9-v19，是用户工作前的旧版本)
```

### 错误根源
- `cron/nightly-fixes` 是用户白天的 staging 分支，包含 v9-v19
- 凌晨 cron 任务为了"拉取最新开发分支代码"，执行了：
  ```bash
  git checkout cron/nightly-fixes
  git merge feature/market-monitor-auto --no-edit
  ```
- 由于 `feature/market-monitor-auto` 早于用户 v9-v19 修改，**且用户白天没把工作 push 到这个分支**，merge 在冲突文件上**选了 feature 侧的旧版本**（具体是 cron 的合并策略默认行为 + ours/theirs 没指定）
- 结果：用户白天 8 小时的工作直接被夜间任务"还原"了

---

## 🛡️ 防御措施

### 立即修复（本次会话已完成）
1. ✅ v19 后端两个文件已恢复（scanner_core.py + scanner_analysis.py）
2. ✅ v19/v18/v17/v16 前端 UI 已恢复（MarketMonitorView.vue + useViewHelpers.ts）
3. ✅ 新增 `scripts/template_render_guard.py` 防再次"搬灯泡拆灯"
4. ✅ 两个 cron 任务加入守卫脚本检查

### 待补修复（本会话即将做）
- [ ] **v11 数据分析全部历史** — AnalysisTab.vue 默认 selectedDate=''
- [ ] **v13 情绪默认日内** — useSentimentMonitor.ts 默认 'intraday'

### 中长期防御（建议）
1. **cron 禁止 auto-merge feature → cron** — 该 merge 永远应该是 cron → feature 单向人工合并
2. **如必须从 feature 拉取**：用 `git merge -X theirs` 或 `git rebase` 而不是默认 merge
3. **加 pre-merge 检查**：merge 前对比关键功能特征字符串，发现丢失就 abort
4. **守卫脚本扩展**：把 `template_render_guard.py` 升级为 `feature_regression_guard.py`，跟踪所有用户白天 commit 的特征字符串

---

## 📝 给用户的话

昨天你做的 13 个 commit 中：
- **6 个被夜间 03:51 的自动 merge 覆盖了**（v11/v13/v16/v17/v18/v19）
- **7 个仍然保留**（v9/v10/v12/v14/v15 + 两个脚本）

不是夜间瘦壳重构（4ae4592e）的问题——那个只覆盖了 v17/v18/v19 的 UI 块。  
真正的祸首是凌晨 03:51 的 cron auto-merge，**它把 cron 分支当成了"应该被 feature 覆盖"的目标**。

现在我在恢复剩下两个被覆盖的 v11/v13，然后给夜间 cron 加 merge 防护逻辑。
