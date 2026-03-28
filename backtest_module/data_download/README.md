# 数据下载模块 (独立回测模块)

本模块按**数据源分类存放**，每种数据源下载方式独立管理，引导程序可以选择。

## 📁 目录结构

```
data_download/
├── README.md          # 本文件
├── __init__.py
├── tushare/           # ✅ Tushare 数据源 - 按股票获取
│   ├── tushare_daily_by_stock.py         # 按股票下载日线行情
│   ├── tushare_daily_basic_by_stock.py   # 按股票下载每日基本面
│   ├── tushare_fina_indicator.py         # 按股票下载财务指标
│   ├── tushare_limit_list.py             # 下载涨跌停列表
│   ├── tushare_lhb.py                    # 下载龙虎榜
│   └── add_up_down_limit.py             # 补全涨跌停价计算
├── akshare/           # ✅ AKShare 数据源 - 免费无需token
│   ├── download_daily_akshare_by_date.py    # 按日期下载日线
│   └── download_limit_list_akshare.py       # 下载涨跌停列表
└── mongodb/           # ✅ MongoDB 数据迁移/导出
    ├── download_extended_historical.py          # 从 price_history 迁移到 stock_daily
    └── download_extended_historical_from_mongo.py  # 导出指定区间到 local-databases
```

## 🎯 设计原则

| 设计要点 | 说明 |
|---------|------|
| **按数据源分类存放** | 每种数据源一个文件夹，互不干扰 |
| **支持引导程序选择** | `run_backtest_wizard.py` 可以选择数据源，每种都有对应下载功能 |
| **保留所有数据源** | 当前调试 Tushare，但不删除其他数据源，需要时可以切换 |
| **独立可维护** | 每种数据源下载脚本独立，方便修改维护 |

## 🚀 使用方式

### 选择 Tushare（按股票获取）

```bash
# 下载指定区间全部股票日线 (一只一只获取)
python backtest_module/data_download/tushare/tushare_daily_by_stock.py 20260105 20260320
```

### 选择 AKShare（免费按日期获取）

```bash
# 下载指定区间全部股票日线 (每天一次请求)
python backtest_module/data_download/akshare/download_daily_akshare_by_date.py 20260105 20260320
```

### MongoDB 数据迁移

```bash
# 从旧格式 price_history (一只股票一篇文档) 迁移到 stock_daily (一条记录一篇文档)
python backtest_module/data_download/mongodb/download_extended_historical.py
```

## ⚙️ 配置

需要在项目根目录 `.env` 中配置对应数据源：

```
# Tushare 配置
TUSHARE_TOKEN=your_token_here
TUSHARE_RATE_LIMIT=500

# AKShare 不需要配置，直接可用
# MongoDB 不需要额外配置
```

## 📊 数据输出存储

无论哪种数据源，最终都输出到相同的 MongoDB 集合：

| 集合 | 说明 | 格式 |
|------|------|------|
| `stock_daily` | 日线行情 | 每条记录一个交易日一只股票 |
| `daily_basic` | 每日基本面 | 每条记录一个交易日一只股票 |
| `fina_indicator` | 财务指标 | 每条记录一只股票一个报告期 |
| `limit_list` | 涨跌停列表 | 每条记录一只股票一个交易日 |
| `lhb` | 龙虎榜 | 每条记录一只股票一个交易日 |

**重要**: 无论哪种数据源获取，输出格式完全一致 → 回测引擎不用修改，直接读取 ✅
