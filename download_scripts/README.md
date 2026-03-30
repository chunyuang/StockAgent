# 下载脚本目录

本目录存放各种数据源的日线数据下载脚本，**物理隔离**不同数据源不同下载模式。

## 分类说明

### 日线数据下载

| 脚本 | 数据源 | 获取方式 | 适用场景 | 依赖 Token |
|------|--------|---------|----------|-----------|
| `download_daily_tushare_by_stock.py` | Tushare | **按股票** → 获取单只股票全部历史 | 全市场全历史下载 | ✅ 需要 |
| `download_daily_akshare_by_date.py` | AKShare | **按日期** → 获取单日全市场 | 近期增量更新 | ❌ 免费 |
| `download_daily_tushare_full_pure.py` | Tushare | **按日期** → 获取单日全市场 | 增量更新 | ✅ 需要 |
| `download_daily_tushare_full_akcal.py` | Tushare | **按日期**，交易日历从 AKShare 获取 | 增量更新 | ✅ 需要 |
| `download_daily_tushare_full.py` | 旧版 | 保留 | 兼容 | - |

### 情绪周期策略数据下载

| 脚本 | 数据源 | 目标集合 | 获取方式 | 适用场景 | 依赖 Token |
|------|--------|----------|---------|----------|-----------|
| `download_limit_list_tushare.py` | Tushare | `limit_list` | 按日期 → 每日涨跌停列表 | 情绪周期核心数据 ✅ | ✅ 需要 |
| `download_daily_basic_tushare.py` | Tushare | `daily_basic` | 按日期 → 每日基本面 (PE/PB/换手率/市值) | 选股过滤 | ✅ 需要 |
| `download_lhb_tushare.py` | Tushare | `lhb` | 按日期 → 每日龙虎榜 | 情绪周期辅助分析 | ✅ 需要 |

### 补全工具

| 脚本 | 说明 |
|------|------|
| `add_up_down_limit.py` | 补全 `stock_daily` 中 `up_limit` / `down_limit` 涨跌停价 |

## 使用原则

## 使用原则

1. **物理隔离**：每个数据源下载脚本独立，互不干扰
2. **格式统一**：所有下载脚本都输出到同一个 MongoDB `stock_daily` 集合，格式标准化
3. **去重**：`_id = "{ts_code}_{trade_date}"` 确保重复下载不会重复存储
4. **回测只读**：回测因子计算只从 MongoDB 读取，不区分数据源

## 格式标准

所有下载脚本输出必须满足以下字段格式（与 Tushare 对齐）：

```javascript
{
  "_id": "{ts_code}_{trade_date}",
  "trade_date": "YYYYMMDD",        // 字符串
  "ts_code": "000001.SZ",          // 带后缀
  "open": 10.50,                   // 开盘价
  "high": 11.04,                   // 最高价
  "low": 10.91,                    // 最低价
  "close": 10.96,                  // 收盘价
  "pre_close": 11.03,              // 昨日收盘价
  "vol": 791079.4,                // 成交量（手）
  "amount": 86771125.0,           // 成交额（元）
  "pct_chg": -0.63,                // 涨跌幅（百分比）
  "change": -0.07,                 // 涨跌点数
  "up_limit": 12.14,              // 涨停价（补全后）
  "down_limit": 9.93,             // 跌停价（补全后）
}
```

## 补全涨跌停价

下载完成后必须运行一次补全脚本：

```bash
cd /root/.openclaw/workspace
python add_up_down_limit.py
```

这个脚本会为所有缺少 `up_limit` / `down_limit` 的记录计算涨跌停价（正常股票 10%，ST 股票 5%）。

## 本地分级数据库

完整数据分级存储在 `local-databases/` 目录：

```
local-databases/
├── README.md             # 总体说明
├── DATA_SOURCES.md       # 数据源规则/额度/最佳实践
├── CHANGELOG.md          # 变更日志
├── USAGE.md             # 使用说明
├── bin/
│   ├── check-db.py           # 一致性校验
│   └── incremental-update.py  # 增量更新
├── raw/                    # 原始数据（一次下载永久保存）
├── factors/               # 因子计算结果
└── backtests/            # 回测结果
```

## 回测读取

因子计算引擎 `factor_engine.py` 只从 MongoDB `stock_daily` 读取数据，**不区分数据源**，只要格式正确就能正确计算。

这样设计：
- ✅ 物理隔离避免格式混乱
- ✅ 回测统一读取简化代码
- ✅ 支持多个数据源混用（Tushare 下载历史，AKShare 更新近期）
