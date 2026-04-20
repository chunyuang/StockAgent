
# 使用说明

## 数据源选择优先级

### 回测场景

默认优先级（优先本地，不存在则在线获取）：

```
local > tushare > akshare > biying > baostock
```

- ✅ 优先使用本地已经下载好的数据，不用重复请求，节省时间避免限流
- ✅ 本地不存在自动fallback到在线数据源获取

### 实盘场景

默认优先级（优先在线获取最新，本地作为fallback）：

```
biying > akshare > baostock > local
```

- ✅ 优先在线获取最新价格，保证实时性
- ✅ 在线失败自动切本地fallback

## 回测执行流程

1. **校验数据一致性** → `python bin/check-db.py --raw {raw_name} --factors {factors_name}`
2. **如果校验通过，直接回测**
3. **如果校验不通过，按照优先级重新获取数据**，更新数据库
4. **更新metadata和dashboard索引**

## 增量更新流程

```
# 自动从上次更新后到今天增量更新
python bin/incremental-update.py --raw {raw_name}
```

- 自动更新metadata
- 自动更新dashboard索引

## 目录结构回顾

```
local-databases/
├── README.md             # 总体说明 + dashboard 索引
├── DATA_SOURCES.md       # 数据源规则/额度/最佳实践记录
├── CHANGELOG.md            # 操作变更日志
├── USAGE.md              # 使用说明 - 包含数据源优先级配置
├── bin/
│   ├── check-db.py             # 一致性校验工具
│   └── incremental-update.py  # 自动增量更新工具
├── raw/                  # 原始数据存储
│   ├── metadata/           # 每个原始数据库描述
│   └── data/               # 备份存储
├── factors/              # 因子计算结果存储
│   ├── metadata/           # 每个因子组合描述
│   └── data/               # 备份存储
└── backtests/             # 回测结果存储
    ├── metadata/           # 每个回测描述
    └── results/            # 回测结果输出
```

## 示例 - 完成一个完整回测

```
# 1. 校验数据
python local-databases/bin/check-db.py --raw 20251215-20260318-akshare --factors 20251215-20260318-akshare--21pricefactors

# 2. 如果通过，直接运行回测代码
... 回测完成 ...

# 3. 自动更新 metadata 和 dashboard
```
