# 本地数据库管理 - 模板

这是一个通用的本地股票数据库管理框架，分级存储原始数据/因子计算/回测结果，支持：
- 一次下载永久复用
- 自动一致性校验
- 自动增量更新
- 自动索引生成
- 自动备份恢复
- 完整变更日志

## 快速开始

见 `OPERATION.md` 完整操作手册

## 目录结构

```
local-databases/
├── README.md             # 本文件 - 自动生成的 dashboard
├── DATA_SOURCES.md       # 数据源规则/额度/擅长时间段
├── SPECIAL_NOTES.md      # 数据源特殊注意事项
├── CHANGELOG.md          # 操作变更日志
├── USAGE.md              # 使用说明 + 数据源优先级配置
├── OPERATION.md           # 完整自动化操作手册
├── bin/
│   ├── check-db.py             # 一致性校验
│   ├── incremental-update.py  # 自动增量更新
│   ├── regenerate-index.py    # 自动生成 README 索引
│   ├── log-change.py          # 自动记录变更日志
│   ├── list-unused.py         # 列出过期数据库提示归档
│   └── backup-db.py          # 备份/恢复 MongoDB
├── raw/
│   ├── metadata/             # 每个原始数据库描述
│   └── data/                 # 原始数据备份（压缩）
├── factors/
│   ├── metadata/             # 每个因子组合描述
│   └── data/                 # 因子数据备份（压缩）
└── backtests/
    ├── metadata/             # 每个回测描述
    └── results/              # 回测结果输出
```

## 使用说明

每次新增/更新数据库，只需要：

```bash
# 1. 创建 metadata 文件（参考已有模板）
# 2. 记录变更
python3 local-databases/bin/log-change.py create category name "description"

# 3. 重新生成索引
python3 local-databases/bin/regenerate-index.py

# 4. 备份（可选）
python3 local-databases/bin/backup-db.py backup --category raw --name database-name
```

完整说明见 `OPERATION.md`

---

## 原始数据源列表

*自动生成，不要手动修改*

