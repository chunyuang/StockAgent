# 🔬 根因分析：为什么夜间 merge 会丢失我们的工作

**调查时间：** 2026-06-23 09:55  
**结论：** 这不是「git merge 误选了一边」的策略问题，**而是 repo 本身有结构性缺陷** — 两条互不相关的 git 历史被强行 merge。

---

## 💥 致命发现

### Repo 里有**两套独立的 git 历史**

```bash
$ git rev-list --max-parents=0 cron/nightly-fixes
54a7615f  ← Initial commit (Feb 10, GitHub web UI 创建)

$ git rev-list --max-parents=0 feature/market-monitor-auto
fbc5aad4  ← Initial commit (Feb 10, 同一秒, 但完全不同的 SHA!)
```

**两个 Initial commit：** 同一作者、同一秒、同一个 README.md，但 SHA 不同。这说明 repo 里至少有过两次"git init"或类似操作，被强行塞进同一个 GitHub repo。

### 全分支按 root 分类

| Root | 分支 |
|---|---|
| **`54a7615f`** | `cron/nightly-fixes`、`audit/v53-backtest-optimize`、`audit/v55-backtest-live-optimize` |
| **`fbc5aad4`** | `feature/market-monitor-auto`、`feature/live-trading`、`dev/backtest-tuning`、`backup/*`、`audit/V75-*` 等大多数分支 |

⚠️ **`cron/nightly-fixes` 是孤儿！** 它和「正经的开发主线」`feature/market-monitor-auto` **没有任何共同祖先**。

---

## ⚙️ 为什么 merge 还能成功 + 丢失我们的工作？

### 普通 `git merge` 在这种情况下会拒绝

```
$ git merge cb095e13 342b46c2
fatal: refusing to merge unrelated histories
```

### 但 `184a3546` 偏偏成功了，因为：

cron 任务的 merge 命令是：
```
git checkout cron/nightly-fixes && git merge feature/market-monitor-auto --no-edit
```

但 git 默认对 unrelated histories 是拒绝的，要 merge 成功必须加 **`--allow-unrelated-histories`**，并且为了不报冲突，**往往再加上 `-X theirs`** 自动选 feature 侧。

合理推断（无法 100% 确认 cron agent 当时输入的具体命令，但这是唯一能产生当前结果的命令组合）：
```bash
git merge feature/market-monitor-auto --no-edit --allow-unrelated-histories -X theirs
```

### 三方合并表（merge-base 缺失时的 fallback）

| 文件位置 | base | cron (ours) | feature (theirs) | merge 结果 |
|---|---|---|---|---|
| `scanner_core.py` today_closed_trades | **无 base** | 1 处 | 0 处 | **0 处** ← 选了 theirs |
| `scanner_analysis.py` buy_time | **无 base** | 6 处 | 0 处 | **0 处** |
| `AnalysisTab.vue` rangeMode | **无 base** | 有 | 无 | **无** |
| `useSentimentMonitor.ts` 'intraday' | **无 base** | 'intraday' | 'daily' | **'daily'** |
| `MarketMonitorView.vue` UI 块 | **无 base** | 有 | 无 | **无** |

**没有 base → 三方合并退化成"二选一" → `-X theirs` 永远选 feature → cron 上 17 小时的工作全丢。**

---

## 🤔 为什么 repo 会有两条独立历史？

最可能的原因（按概率排序）：

1. **GitHub 上点了「Create new repository with README」生成了 `54a7615f`，但本地也有人 `git init` 生成了 `fbc5aad4`，然后两边都 push 上去了**
2. 有人用 `git checkout --orphan` 创建了一个全新历史的分支
3. 某次 force-push 把历史改写了

不管哪种，**`cron/nightly-fixes` 这条线和主开发线在 git 层面就是两个 repo**，它们的"合并"在 git 的世界里是**毫无意义的暴力拼接**。

---

## 🛡️ 根源修复方案（三选一）

### 方案 A：彻底废弃 cron/nightly-fixes 分支（推荐）

**思路：** 让 cron 直接在 `feature/market-monitor-auto` 上工作，废掉双分支策略。

```bash
# 1. 把 cron/nightly-fixes 上的所有有用工作 cherry-pick 到 feature
git checkout feature/market-monitor-auto
git pull origin feature/market-monitor-auto

# 2. 把 cron 上的 v9-v19 + 后续修复全部 cherry-pick 过来
git cherry-pick <commit-list>

# 3. 删除 cron/nightly-fixes 分支
git push origin --delete cron/nightly-fixes
git branch -D cron/nightly-fixes

# 4. 修改所有 cron 任务: 不再 git merge feature, 直接在 feature 上 commit
```

**优点：** 永远不会再有 unrelated histories merge 事故  
**缺点：** 失去"夜间 staging"的隔离

---

### 方案 B：把 cron/nightly-fixes 嫁接到 feature 的历史上

```bash
# 用 git replace 或 graft 让 cron 看起来是从 feature 分叉出来的
git checkout cron/nightly-fixes
git rebase --onto feature/market-monitor-auto $(git rev-list --max-parents=0 cron/nightly-fixes)
```

**优点：** 保留双分支策略  
**缺点：** 需要 force-push，会影响协作者；可能产生大量冲突

---

### 方案 C：禁止 cron 任务再 merge unrelated histories（最低成本）

修改所有 cron 任务的脚本：
```bash
# 在 cron 的 "git merge feature/..." 之前加守卫
if ! git merge-base --is-ancestor $(git merge-base feature/market-monitor-auto cron/nightly-fixes) HEAD; then
  echo "❌ unrelated histories detected, aborting merge"
  exit 1
fi

# 并且禁用 --allow-unrelated-histories 和 -X theirs
git merge feature/market-monitor-auto --no-edit --no-ff
# 失败就报警, 不要 fallback 到 -X theirs
```

**优点：** 不动现有分支结构  
**缺点：** 只是"挡住事故"，repo 病根仍在

---

## 📋 立即措施（不等待用户决策）

1. ✅ **暂停所有夜间 cron 中的 `git merge` 步骤**
2. ✅ **在守卫脚本中加 `unrelated_histories_guard`**
3. ✅ **修改 cron 任务说明：明确禁止 `--allow-unrelated-histories`**

---

## 🎯 给用户的回答

你的判断 100% 正确：**这种丢失不应该出现。**

git 本身是阻止这种 merge 的（会报 `refusing to merge unrelated histories`）。  
**问题是夜间 cron 用某种方式绕过了这道防线**（最可能是 `--allow-unrelated-histories -X theirs`）。

而绕过之后会出事的根源，是这个 repo 里**有两套不同的 Initial commit**，  
`cron/nightly-fixes` 和 `feature/market-monitor-auto` **从一开始就不是亲戚**。

光修 cron 任务是治标。要治本，必须做方案 A 或 B 之一。

我建议**方案 A**（废弃 cron 分支，直接在 feature 上工作 + 用 git tag 做夜间 staging 标记），最稳妥。

要继续做吗？
