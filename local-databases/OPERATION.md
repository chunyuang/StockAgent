# 项目6 操作手册 - 本地数据库管理

本文档是自动化操作流程，每次新增/更新数据库按照这个流程走就行。

---

## 📋 完整操作流程

### 1. 新增原始数据库

```bash
# 1. 创建 metadata 文件
# 参考模板: raw/metadata/20251215-20260318-akshare.md
# 按照格式填写: 版本 v1, 起止日期, 股票数, 交易日, 总记录数

# 2. 数据质量检查（必做）
python3 local-databases/bin/validate-data.py --type raw --name 你的数据库名称

# 3. 自动记录变更
python3 local-databases/bin/log-change.py create raw 你的数据库名称 "新增原始数据库，说明"

# 4. 重新生成统计 json（方便程序读取）
python3 local-databases/bin/generate-stats.py

# 5. 自动重新生成 README dashboard
python3 local-databases/bin/regenerate-index.py

# 6. 如果需要备份，备份 MongoDB
python3 local-databases/bin/backup-db.py backup --category raw --name 你的数据库名称 --collection stock_daily
```

---

### 2. 新增因子计算（基于已有原始数据）

```bash
# 1. 创建 metadata 文件
# 参考模板: factors/metadata/20251215-20260318-akshare--21pricefactors.md
# 必须写明依赖哪个原始数据: 依赖原始数据 → raw/xxx

# 2. 数据质量检查（必做）
python3 local-databases/bin/validate-data.py --type factors --name 你的因子名称

# 3. 自动记录变更
python3 local-databases/bin/log-change.py create factors 你的因子名称 "新增因子计算，说明"

# 4. 重新生成统计 json（方便程序读取）
python3 local-databases/bin/generate-stats.py

# 5. 自动重新生成 README dashboard
python3 local-databases/bin/regenerate-index.py

# 6. 如果需要备份，备份 MongoDB
python3 local-databases/bin/backup-db.py backup --category factors --name 你的因子名称 --collection strategy_signals
```

---

### 3. 新增回测（基于已有因子计算）

```bash
# 1. 创建 metadata 文件
# 参考模板: backtests/metadata/20251215-20260318-akshare--21pricefactors-top50-monthly.md
# 必须写明依赖: 依赖原始数据 + 依赖因子组合

# 2. 自动记录变更
python3 local-databases/bin/log-change.py create backtests 你的回测名称 "新增回测，说明配置"

# 3. 重新生成统计 json（方便程序读取）
python3 local-databases/bin/generate-stats.py

# 4. 自动重新生成 README dashboard
python3 local-databases/bin/regenerate-index.py
```

---

### 4. 更新已有数据库

```bash
# 1. 修改 metadata 文件，更新 更新时间

# 2. 数据质量检查
python3 local-databases/bin/validate-data.py --type raw --name 数据库名称

# 3. 自动记录变更
python3 local-databases/bin/log-change.py update category 数据库名称 "更新说明，改了什么"

# 4. 重新生成统计 json（方便程序读取）
python3 local-databases/bin/generate-stats.py

# 5. 自动重新生成 README dashboard
python3 local-databases/bin/regenerate-index.py
```

---

### 5. 归档/删除不用的数据库

```bash
# 1. 先看哪些很久没更新了
python3 local-databases/bin/list-unused.py --days 30

# 2. 记录归档
python3 local-databases/bin/log-change.py archive category 数据库名称 "归档原因，很久不用了"

# 3. （可选）压缩备份
python3 local-databases/bin/backup-db.py backup --category category --name 数据库名称

# 4. 重新生成统计 json
python3 local-databases/bin/generate-stats.py

# 5. 重新生成索引
python3 local-databases/bin/regenerate-index.py
```

---

### 6. 增量更新数据

```bash
# 自动增量更新从上次更新后到今天
python3 local-databases/bin/incremental-update.py --raw 数据库名称

# 指定日期范围
python3 local-databases/bin/incremental-update.py --raw 数据库名称 --start 20260301 --end 20260320

# 更新完会自动:
# - 更新 metadata 最后交易日
# - 更新 README 索引
# - 记录变更日志
# - 重新生成统计 json
```

---

### 7. 校验数据一致性（回测前必做）

```bash
# 校验原始 + 因子
python3 local-databases/bin/check-db.py --raw 原始名称 --factors 因子名称

# 如果校验不通过，会提示你重新计算
# 如果通过，可以放心回测
```

---

### 8. 从备份恢复

```bash
# 从压缩备份恢复
python3 local-databases/bin/backup-db.py restore --archive /path/to/your/archive.tar.gz
```

---

## 🎯 自动化流程总结

每次操作完你的那一步（创建 metadata + 导入数据），只需要跑这三条命令：

```bash
# 记录变更
python3 local-databases/bin/log-change.py create category name "description"

# 重新生成索引
python3 local-databases/bin/regenerate-index.py

# 校验一致性
python3 local-databases/bin/check-db.py --raw xxx --factors yyy
```

Done! ✅

---

## 📚 相关文档

- `README.md` → 自动生成的 dashboard 索引
- `DATA_SOURCES.md` → 数据源规则/额度/擅长时间段
- `SPECIAL_NOTES.md` → 每个数据源的特殊注意事项
- `CHANGELOG.md` → 自动记录的操作变更日志
- `USAGE.md` → 使用说明 + 数据源优先级配置

---

## 💡 最佳实践

1. **永远不要手动修改 README** → 它是自动生成的，修改会被覆盖
2. **所有变更都要记录日志** → 用 `log-change.py`，不用手动改 CHANGELOG
3. **回测前一定要校验** → `check-db.py` 可以避免 90% 的低级错误
4. **过期数据库不要直接删** → 先归档压缩，确认没用了再删，保留历史对比
5. **并行获取大时间段** → Tushare 拿早期，AKShare 拿近期，同时跑，最后合并
