# 量脉金融数据平台 API 文档

## 概览

- **网关地址**: `http://124.220.44.71/api/gateway`
- **认证方式**: 请求参数 `token=ebacbad6d64444cd037ac5504b63f25d`
- **请求方式**: GET 或 POST，参数以 form-urlencoded 传递
- **频率限制**: 1分钟120次
- **IP限制**: 同一Token最多2个IP
- **响应格式**: `{"code": 0, "msg": "success", "meta": {...}, "data": [...]}`
- **成功码**: `code=0`
- **限流码**: `code=4291` (IP超限)
- **缓存TTL**: 多数接口60秒

## 与StockAgent的映射关系

| StockAgent现有数据源 | 量脉对应接口 | 优势 |
|---------------------|------------|------|
| Tushare pro.daily | `quote_bars_history` (klt=d, fqt=f) | 无需Tushare积分，直接历史K线 |
| Tushare daily_basic | `stock_realtime` (pe/pb/lt/sz) | 实时PE/PB/流通市值/总市值 |
| AKShare涨停池 | `pool_limit_up` | 含封板时间/炸板次数/连板数/封板资金 |
| AKShare跌停池 | `pool_limit_down` | 含开板次数/封单资金 |
| Tushare limit_list | `pool_limit_up`+`pool_limit_down` | 更丰富(封板时间/炸板次数) |
| stock_basic | `hs_list_main`+`company_profile` | 含概念板块字段 |
| 无(新增) | `capital_flow_history` | 主力/大单/中单/小单净流入 |
| 无(新增) | `sector_tree`+`sector_constituents` | 申万行业/概念板块成分股 |
| 无(新增) | `tech_ma/tech_macd/tech_kdj/tech_boll` | 服务端计算技术指标 |
| 无(新增) | `quote_bars_latest` (klt=1/5/15/30/60) | 分钟级K线 |

## 接口清单（76个）

### 列表与检索
| API名 | 说明 | 关键参数 |
|-------|------|---------|
| `hs_list_main` | 沪深A股列表 | 无 |
| `stock_list` | 沪深京合并列表 | 无 |
| `ipo_calendar` | 新股日历 | 无 |
| `index_list_main` | 沪深主要指数 | 无 |
| `bj_list_stocks` | 北交所股票 | 无 |
| `bj_list_indices` | 北交所指数 | 无 |
| `hk_list_stocks` | 港股列表 | 无 |
| `kc_list_stocks` | 科创板股票 | 无 |
| `fund_list_all` | 基金列表 | 无 |
| `fund_list_etf` | ETF列表 | 无 |
| `base_st` | ST股票列表 | 无 |
| `stock_instrument` | 证券信息 | ts_code |

### 板块概念
| API名 | 说明 | 关键参数 |
|-------|------|---------|
| `base_gn` | 概念代码 | 无 |
| `base_bk` | 板块代码 | 无 |
| `sector_tree` | 行业/概念树 | 无 |
| `sector_constituents` | 板块成分股 | sector_code |
| `stock_sectors` | 个股所属板块 | ts_code |
| `base_bk_flow_history` | 板块资金流 | bkCode |
| `base_bk_list` | 板块成分股(分页) | bkCode, pageNo, pageSize |

### 股池与盘面 ⭐ 核心数据
| API名 | 说明 | 关键参数 |
|-------|------|---------|
| `pool_limit_up` | 涨停股池 | trade_date (yyyy-MM-dd) |
| `pool_limit_down` | 跌停股池 | trade_date |
| `pool_strong` | 强势股池 | trade_date |
| `pool_subnew` | 次新股池 | trade_date |
| `pool_broken_board` | 炸板股池 | trade_date |

### 行情数据 ⭐ 核心数据
| API名 | 说明 | 关键参数 |
|-------|------|---------|
| `quote_bars_latest` | 最新K线 | ts_code, klt, fqt, lt |
| `quote_bars_history` | 历史K线 | ts_code, klt, fqt, beg, end, lt |
| `stock_realtime` | 实时行情(网络源) | ts_code |
| `quote_realtime_broker` | 实时行情(券商源) | ts_code |
| `quote_five_broker` | 五档盘口 | ts_code |
| `market_realtime_all_broker` | 全市场行情(券商) | 无(限1次/分) |
| `market_realtime_all_network` | 全市场行情(网络) | 无(限1次/分) |
| `stock_realtime_multi` | 多股行情(≤20) | ts_code(逗号分隔) |
| `stock_ticks_today` | 当天逐笔 | ts_code |
| `quote_stop_prices` | 涨跌停价 | ts_code |
| `quote_market_indicators` | 市场指标 | 无 |

### 技术指标（服务端计算）
| API名 | 说明 | 关键参数 |
|-------|------|---------|
| `tech_ma` | 均线MA | ts_code |
| `tech_macd` | MACD | ts_code |
| `tech_kdj` | KDJ | ts_code |
| `tech_boll` | 布林带 | ts_code |

### 指数行情
| API名 | 说明 | 关键参数 |
|-------|------|---------|
| `index_bars_latest` | 指数最新K线 | ts_code, klt, lt |
| `index_bars_history` | 指数历史K线 | ts_code, klt, beg, end, lt |
| `index_realtime_broker` | 指数实时行情 | ts_code |
| `index_tech_ma/macd/kdj/boll` | 指数技术指标 | ts_code |

### 资金流向
| API名 | 说明 | 关键参数 |
|-------|------|---------|
| `capital_flow_history` | 个股资金流向 | ts_code, beg, end, lt |

### 公司资料
| API名 | 说明 | 关键参数 |
|-------|------|---------|
| `company_profile` | 公司简介 | ts_code |
| `company_index_membership` | 所属指数 | ts_code |
| `company_dividend` | 分红 | ts_code |
| `company_seo` | 增发 | ts_code |
| `company_unlock` | 解禁限售 | ts_code |
| `company_quarter_profit` | 季度利润 | ts_code |
| `company_quarter_cashflow` | 季度现金流 | ts_code |
| `company_forecast` | 业绩预告 | ts_code |
| `company_finance_metrics` | 财务指标 | ts_code |
| `company_holders_top10` | 十大股东 | ts_code |
| `company_float_holders_top10` | 十大流通股东 | ts_code |
| `company_holder_trend` | 股东变化趋势 | ts_code |
| `company_fund_holdings` | 基金持股 | ts_code |

### 财务报表
| API名 | 说明 | 关键参数 |
|-------|------|---------|
| `fin_balance_sheet` | 资产负债表 | ts_code |
| `fin_income_statement` | 利润表 | ts_code |
| `fin_cashflow_statement` | 现金流量表 | ts_code |
| `fin_capital_structure` | 资本结构 | ts_code |
| `fin_per_share_index` | 每股指标 | ts_code |
| `fin_holder_counts` | 股东户数 | ts_code |
| `fin_top10_holders` | 前十大股东 | ts_code |
| `fin_top10_float_holders` | 前十大流通股东 | ts_code |

### 北交所/港股/科创板
| API名 | 说明 | 关键参数 |
|-------|------|---------|
| `bj_quote_realtime` | 北交所实时 | ts_code |
| `bj_quote_five` | 北交所五档 | ts_code |
| `bj_index_realtime` | 北交所指数实时 | ts_code |
| `hk_quote_realtime` | 港股实时 | ts_code |
| `hk_quote_five` | 港股五档 | ts_code |
| `kc_quote_realtime` | 科创板实时 | ts_code |
| `kc_quote_five` | 科创板五档 | ts_code |

## K线参数说明

### klt（K线类型）
| 值 | 说明 |
|----|------|
| 1 | 1分钟 |
| 5 | 5分钟 |
| 15 | 15分钟 |
| 30 | 30分钟 |
| 60 | 60分钟 |
| d | 日线 |
| w | 周线 |
| m | 月线 |
| y | 年线 |

### fqt（复权类型，日线以上有效）
| 值 | 说明 |
|----|------|
| n | 不复权 |
| f | 前复权 |
| b | 后复权 |
| fr | 等比前复权 |
| br | 等比后复权 |

### 其他参数
- `lt`: 返回条数（如 lt=10 取最新10条）
- `beg`: 开始日期 YYYYMMDD
- `end`: 结束日期 YYYYMMDD
- `ts_code`: 6位股票代码（如 000001）

## K线返回字段

| 字段 | 类型 | 说明 |
|------|------|------|
| t | string | 交易时间 |
| o | float | 开盘价 |
| h | float | 最高价 |
| l | float | 最低价 |
| c | float | 收盘价 |
| v | float | 成交量(手) |
| a | float | 成交额(元) |
| pc | float | 前收盘价 |
| sf | int | 停牌标记(1停牌,0正常) |

## 涨停股池返回字段

| 字段 | 类型 | 说明 |
|------|------|------|
| dm | string | 代码 |
| Mc | string | 名称 |
| p | number | 价格(元) |
| zf | number | 涨幅(%) |
| cje | number | 成交额(元) |
| lt | number | 流通市值(元) |
| zsz | number | 总市值(元) |
| hs | number | 换手率(%) |
| Lbc | number | 连板数 |
| fbt | string | 首次封板时间(HH:mm:ss) |
| lbt | string | 最后封板时间(HH:mm:ss) |
| zj | number | 封板资金(元) |
| zbc | number | 炸板次数 |
| tj | string | 涨停统计(x天/y板) |
| hy | string | 所属行业 |

## 对StockAgent的价值

### 1. 替代Tushare daily_basic的精确数据
- `stock_realtime` 返回 pe/lt/sz/sjl(市净率) — 实时PE/PB/流通市值/总市值
- `quote_bars_history` 日线含 pc(前收盘价) — 解决pre_close缺失问题

### 2. 新增涨停池高质量数据
- `pool_limit_up` 含封板时间/炸板次数/连板数 — 比Tushare limit_list更丰富
- `pool_broken_board` 炸板股 — 之前没有数据源

### 3. 新增资金流向数据
- `capital_flow_history` 含主力/大单/中单/小单净流入 — 全新维度

### 4. 新增分钟级K线
- `quote_bars_latest` klt=1/5/15 — 高频策略基础

### 5. 技术指标服务端计算
- `tech_ma/macd/kdj/boll` — 无需本地talib

### 6. 板块成分股
- `sector_tree`+`sector_constituents` — 解决板块集中度过滤的行业数据问题
