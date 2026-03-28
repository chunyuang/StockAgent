# 独立回测模块

这个目录存放完整的回测引擎，可以单独提取出来放到其他系统使用。

## 📁 目录结构

```
backtest_module/
├── backtest_engine/            # 回测引擎核心代码
│   ├── backtester.py          # 单股票回测
│   ├── performance.py         # 绩效计算 (夏普/卡玛/胜率/盈亏比)
│   ├── factors.py            # 因子数据封装
│   ├── node.py              # RPC 节点入口
│   ├── incremental_backtest.py # 增量回测
│   ├── walk_forward.py       # 滚动窗口回测
│   └── factor_selection/      # 因子选股回测
│       ├── portfolio_backtest.py  # 组合回测主引擎
│       ├── factor_engine.py     # 因子计算引擎
│       ├── factor_library.py   # 因子库 (内置 33+ 因子)
│       └── universe.py        # 股票池管理器
├── data_download/              # 数据下载模块
│   ├── README.md              # 本模块说明
│   ├── __init__.py
│   ├── tushare_daily_by_stock.py         # Tushare 按股票下载日线
│   └── tushare_daily_basic_by_stock.py  # Tushare 按股票下载每日基本面
└── README.md
```

## 🎯 核心功能

| 功能 | 说明 |
|------|------|
| 单股票向量回测 | 支持 T+1、涨跌停、佣金印花税、滑点 |
| 组合因子选股回测 | 支持日/周/月调仓，等权/因子加权 |
| 绩效统计 | 夏普比率、卡玛比率、胜率、盈亏比、最大回撤 |
| 滚动窗口回测 | 支持 walk forward analysis |
| 增量回测 | 支持增量更新 |
| 因子库 | 内置 33+ 因子，支持扩展 |

## 📋 依赖

```
- pandas
- numpy
- pymongo
- pydantic
```

## 🔧 数据依赖

回测引擎只从 MongoDB 读取数据，需要以下集合:

| 集合 | 必须字段 | 说明 | 获取方式 |
|------|---------|------|----------|
| `stock_daily` | `trade_date`, `ts_code`, `open`, `high`, `low`, `close`, `pre_close`, `vol`, `amount`, `up_limit`, `down_limit` | 日线行情 | `data_download/tushare_daily_by_stock.py` |
| `daily_basic` | `trade_date`, `ts_code`, `pe`, `pe_ttm`, `pb`, `total_mv`, `turnover_rate` | 每日基本面 | `data_download/tushare_daily_basic_by_stock.py` |
| `fina_indicator` | `ts_code`, `end_date`, `roe`, `revenue_yoy`, `netprofit_yoy` | 财务指标 | Tushare API |
| `limit_list` | `trade_date`, `ts_code`, `limit` | 涨跌停列表 (情绪周期需要) | Tushare API |
| `lhb` | `trade_date`, `ts_code`, `net_buy` | 龙虎榜 (情绪周期需要) | Tushare API |

数据下载模块已集成在本模块中，可以直接使用。

## 📦 打包提取

如果需要放到其他系统使用，直接打包整个 `backtest_module/` 目录拷贝即可:

```bash
tar -czf backtest_module.tar.gz backtest_module/
```

## 🎯 设计原则

- **独立**: 不依赖项目其他模块，可以单独使用
- **清晰**: 每个文件职责单一，方便修改
- **可扩展**: 因子库容易添加新因子
- **标准**: 输入输出格式标准，容易集成

---

## 🏷️ 版本

- 版本: 1.0
- 日期: 2026-03-27
- 兼容: Python 3.10+
