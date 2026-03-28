# Tushare 数据源 - 按获取方式分类存放

本目录按 **官方/代理** 和 **按股票/按日期** 四级分类存放，每种方式独立脚本，方便单独测试运行。

## 📁 最终目录结构

```
tushare/
├── official/                  # 🔥 使用官方 API 直接连接
│   ├── stock/                 # 按股票一只一只获取
│   │   ├── tushare_daily_by_stock.py         # 下载日线行情
│   │   ├── tushare_daily_basic_by_stock.py   # 下载每日基本面
│   │   ├── tushare_fina_indicator.py       # 下载财务指标
│   │   ├── tushare_limit_list.py             # 下载涨跌停列表
│   │   └── tushare_lhb.py                  # 下载龙虎榜
│   ├── date/                  # 按日期每天获取全部股票
│   │   ├── tushare_daily_by_date.py         # 下载日线行情
│   │   ├── tushare_limit_list.py             # 下载涨跌停列表
│   └── add_up_down_limit.py               # 补全 stock_daily 涨跌停价 (工具)
└── proxy/                       # 🔥 使用自定义代理 API
    ├── stock/                 # 按股票一只一只获取 (代理)
    │   ├── tushare_daily_by_stock.py         # 下载日线行情
    │   ├── tushare_daily_basic_by_stock.py   # 下载每日基本面
    │   ├── tushare_fina_indicator.py       # 下载财务指标
    │   ├── tushare_limit_list.py             # 下载涨跌停列表
    │   └── tushare_lhb.py                  # 下载龙虎榜
    ├── date/                  # 按日期每天获取全部股票 (代理)
    │   ├── tushare_daily_by_date.py         # 下载日线行情
    │   ├── tushare_limit_list.py             # 下载涨跌停列表
    └── add_up_down_limit.py               # 补全 stock_daily 涨跌停价 (工具)
```

## 🚀 使用方式

### 官方 API - 按股票获取日线（推荐调试）

```bash
# 下载指定区间全部股票日线，间隔 1s
python backtest_module/data_download/tushare/official/stock/tushare_daily_by_stock.py 20260105 20260320 1.0
```

### 官方 API - 按日期获取日线

```bash
# 下载指定区间日线，间隔 1s
python backtest_module/data_download/tushare/official/date/tushare_daily_by_date.py 20260105 20260320 1.0
```

### 代理 API - 按股票获取日线

需要先在 `.env` 配置代理地址：
```
TUSHARE_HTTP_URL=http://your-proxy-url.com
```

然后运行：
```bash
python backtest_module/data_download/tushare/proxy/stock/tushare_daily_by_stock.py 20260105 20260320 1.0
```

## ⚙️ 配置

在项目根目录 `.env` 中配置：

```
# 必须配置 Token
TUSHARE_TOKEN=your_token_here

# 官方 API - 注释掉这行就是官方
# 代理 API - 去掉注释配置代理地址
# TUSHARE_HTTP_URL=http://119.45.170.23

# 频率限制 (每分钟请求数)
TUSHARE_RATE_LIMIT=500
```

## 📊 输出存储

无论哪种方式，最终都输出到相同 MongoDB 集合：

| 集合 | 说明 |
|------|------|
| `stock_daily` | 日线行情 |
| `daily_basic` | 每日基本面 |
| `fina_indicator` | 财务指标 |
| `limit_list` | 涨跌停列表 |
| `lhb` | 龙虎榜 |

## 🎯 设计原则

1. **官方/代理分开** - 两种方式独立，互不干扰，方便切换测试
2. **按股票/按日期分开** - 两种获取方式分开，满足不同需求
3. **每个功能独立脚本** - 可以单独运行，不需要依赖其他
4. **间隔可配置** - 命令行最后一个参数指定请求间隔，方便调试频率
5. **完全分类** - 不会混用，方便维护
