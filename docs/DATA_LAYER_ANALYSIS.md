# StockAgent 数据层专项分析

> 整理时间: 2026-05-04
> 基于30轮代码审查 + 源码结构分析

---

## 一、数据层架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                     数据消费方 (Consumers)                     │
│  backtest_engine / real_trading / web_api / inference / agents│
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   数据管理器层 (Managers)                      │
│  DataSourceManager → TushareManager / AKShareManager          │
│  LocalMongoManager (三级降级末端)                               │
│  StockDataManager (缓存+API)                                   │
│  MongoManager (CRUD + BulkWrite + 索引)                        │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   数据源适配器层 (Adapters)                     │
│  TushareAdapter (优先级100) ── 需Token，500次/分钟限流          │
│  AKShareAdapter (优先级50)  ── 免费，实时行情好                  │
│  BaoStockAdapter (优先级10) ── 免费，历史数据全，无实时           │
│  统一接口: AsyncDataSourceAdapter (base.py)                    │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   数据采集层 (Collectors)                       │
│  DataSyncNode → 12个Collector实例                              │
│  StockBasic / StockDaily / DailyBasic / IndexBasic /           │
│  IndexDaily / MoneyflowIndustry / MoneyflowConcept /           │
│  LimitList / DailyStats / News / FinaIndicator / HotNews       │
│  特性: 分布式锁 + BulkWrite + 增量同步                           │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   存储层 (MongoDB)                             │
│  核心集合: stock_daily_ak_full / stock_basic / index_daily /   │
│  daily_basic / fina_indicator / limit_list / moneyflow_*       │
│  缓存集合: stock_daily_ak_full_cache                           │
│  因子集合: 因子数据存储在 stock_daily_ak_full 文档字段中           │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、数据源对比

| 维度 | Tushare | AKShare | BaoStock |
|------|---------|---------|----------|
| **费用** | 需Token(付费) | 完全免费 | 完全免费 |
| **优先级** | 100 (最高) | 50 | 10 (最低) |
| **限流** | 500次/分钟(TokenBucket) | 无官方限制 | 无 |
| **日线行情** | ✅ 按股票/按日期 | ✅ 按日期(全A股) | ✅ 按股票 |
| **实时行情** | ✅ | ✅ (东方财富/新浪) | ❌ |
| **每日指标** | ✅ (PE/PB/换手率等) | ✅ (较慢) | ✅ |
| **财务数据** | ✅ (最全) | ❌ | ❌ |
| **资金流向** | ✅ | ✅ | ❌ |
| **涨跌停** | ✅ | ✅ | ❌ |
| **指数数据** | ✅ | ✅ | ✅ |
| **新闻** | ❌ | ✅ (多源) | ❌ |
| **前复权** | ✅ (qfq) | ❌ | ✅ |
| **pre_close** | ✅ (前复权不含) | ❌ | ✅ |

---

## 三、MongoDB 核心集合 & 字段映射

### 3.1 集合清单

| 集合名 | 数据源 | 主要内容 | 关键字段 |
|--------|--------|----------|----------|
| `stock_daily_ak_full` | AKShare | A股日线行情(主表) | ts_code, trade_date, open/high/low/close, pct_chg, vol, amount, turnover_rate, circ_mv + 52个因子字段 |
| `stock_basic` | Tushare | 股票基础信息 | ts_code, name, industry, market, list_date, list_status |
| `daily_basic` | Tushare | 每日指标 | ts_code, trade_date, pe, pb, turnover_rate, circ_mv |
| `index_daily` | Tushare | 指数日线 | ts_code(000001.SH等), trade_date, close |
| `fina_indicator` | Tushare | 财务指标 | ts_code, end_date, roe, eps, bps, debt_to_assets等 |
| `limit_list` | Tushare | 涨跌停列表 | ts_code, trade_date, limit_up/down, open_times |
| `moneyflow_industry` | Tushare | 行业资金流 | industry, trade_date, buy_sm_amount等 |
| `moneyflow_concept` | Tushare | 概念资金流 | concept, trade_date, buy_sm_amount等 |
| `stock_1min` | AKShare | 1分钟线(超短) | ts_code, datetime, close |

### 3.2 关键字段缺失问题

| 字段 | 缺失集合 | 影响 | 当前解决方案 |
|------|----------|------|-------------|
| `pre_close` | stock_daily_ak_full | 涨停价计算不精确 | 运行时从`_prev_day_close`字典补充(第20轮) |
| `industry` | stock_daily_ak_full | 板块集中度过滤无法执行 | 需查stock_basic获取(第9轮) |
| 指数数据 | stock_daily_ak_full | 基准收益率始终0% | 改查index_daily(第8轮) |

---

## 四、遇到过的问题分类 (30轮审查汇总)

### 4.1 数据获取问题

| # | 问题 | 严重度 | 轮次 | 根因 |
|---|------|--------|------|------|
| 1 | `_load_all_data`逐天查MongoDB | P1 | 第5轮 | 用for循环逐天find，应改$gte/$lte范围查询 |
| 2 | `_load_benchmark_data`查错集合(stock_daily_ak_full无指数) | P1 | 第8轮 | 集合职责不清，个股集合不存指数 |
| 3 | `_load_daily_data`/`_load_daily_basic_data`死代码128行 | P1 | 第5轮 | 遗留代码未清理 |
| 4 | TokenBucket限流创建了但从未使用 | P1 | 第25轮 | _bucket在initialize()创建但_call_api未调用 |
| 5 | get_stk_limit重复try/except块 | P1 | 第25轮 | AKShare fallback路径代码质量差 |
| 6 | 股票代码后缀逻辑错误(5开头≠股票) | P1 | 第25轮 | 缺少北交所.BJ判断 |
| 7 | 涨跌停阈值不完整 | P1 | 第25轮 | 缺301(创业板)+北交所(30%) |
| 8 | SimulatedGateway返回硬编码假数据(price=10.0) | P1 | 第26/30轮 | 模拟网关未从MongoDB获取真实行情 |
| 9 | `_get_latest_price`硬编码10.0 | P1 | 第27轮 | sim_trading_engine同上 |
| 10 | 6个download脚本v1~v6并存 | 架构 | 源码 | 下载脚本迭代未清理旧版本 |

### 4.2 数据使用问题 (因子/字段/单位)

| # | 问题 | 严重度 | 轮次 | 根因 |
|---|------|--------|------|------|
| 1 | `pullback_pct`存负数但过滤用`>=0.15` | P0 | 第15轮 | 因子符号不一致，策略永远0候选不报错 |
| 2 | `circ_mv`亿→万元转换遗漏 | P0 | 第12轮 | 前端传亿，后端存万元，缺少×10000 |
| 3 | `rise_after_limit_down`百分比vs小数 | P0 | 第15轮 | 0.03(小数) vs 3.0(百分比) |
| 4 | `force_empty_position` vs `enable_force_empty` | P0 | 多轮 | 跨文件字段名不一致，API必崩 |
| 5 | factor_engine.py 24个因子重复注册 | P0 | 第5轮 | 跨文件注册覆盖factor_library |
| 6 | 板块集中度有开关无执行逻辑 | P0 | 第9轮 | 配置+日志到位，唯独缺核心过滤 |
| 7 | `benchmark_return_pct`硬编码0.0 | P0 | 第9轮 | 数据加载了但从未计算 |
| 8 | 强制空仓时close=0以0元卖出 | P0 | 第8轮 | 停牌股未做有效价检查 |
| 9 | PnL用buy_price代替current_price | P1 | 第26轮 | 成本价≠市价，PnL恒为0 |
| 10 | `_calc_hold_days`用日历天数 | P2 | 第27轮 | 应×0.67近似交易日 |

### 4.3 数据架构问题

| # | 问题 | 类型 | 说明 |
|---|------|------|------|
| 1 | stock_daily_ak_full承担过多职责 | 设计 | 既是行情表又是因子表，字段膨胀 |
| 2 | pre_close缺失是数据管道问题 | 管道 | Tushare前复权不返回，AKShare也不提供 |
| 3 | 6个下载脚本v1~v6并存 | 历史 | 每次修bug新建版本，旧版未删 |
| 4 | 3个deprecated collector(674行×3) | 存根 | theme/milvus/analysis_manager内容相同 |
| 5 | 因子存储在主表文档中 | 扩展性 | 52个因子字段→document膨胀，查询效率下降 |
| 6 | 全项目用sys.path.insert | 反模式 | real_trading所有模块都用，影响可维护性 |

---

## 五、数据流关键链路

### 5.1 回测数据流

```
MongoDB → backtester._load_all_data()
    ├── stock_daily_ak_full (日线行情 + 52因子)
    ├── index_daily (基准指数)
    ├── stock_basic (行业/上市状态)
    └── daily_basic (PE/PB/换手率)

→ factor_engine.compute() (补算缺失因子)
→ universe.filter() (可交易股票筛选)
→ strategy.generate_signals() (买卖信号)
→ portfolio_backtest.run() (组合回测)
```

### 5.2 实时交易数据流

```
DataSourceManager (自动降级)
    ├── TushareAdapter → TokenBucket限流 → API调用
    ├── AKShareAdapter → 免费接口
    └── BaoStockAdapter → 最低优先级

→ TradeGateway.get_realtime_quote() (实时行情)
→ SimulatedGateway (模拟→MongoDB回退)
→ AutoTradeExecutor.execute() (调仓执行)
```

### 5.3 数据同步流

```
DataSyncNode (APScheduler定时任务)
    └── 12个Collector
        ├── 首次同步: HISTORY_START_DATE(20030127)逐股获取
        ├── 增量同步: 从上次日期→今天，批量获取
        └── 已同步: 跳过

    → 分布式锁(Redis)防重复
    → BulkWrite批量写入MongoDB
    → 数据完整性校验 + 缺失补全
```

---

## 六、当前设计的所有数据模块

### AgentServer/core/managers/ (核心管理器)

| 文件 | 职责 | 状态 |
|------|------|------|
| `mongo_manager.py` | MongoDB连接池、CRUD、BulkWrite、索引管理 | ✅活跃 |
| `local_mongo_manager.py` | 三级降级末端，纯本地读取 | ✅活跃 |
| `tushare_manager.py` | Tushare API封装+TokenBucket限流+AKShare回退 | ✅活跃(第25轮修bug) |
| `akshare_manager.py` | AKShare API封装 | ✅活跃 |
| `akshare_daily_manager.py` | AKShare日线数据专用 | ✅活跃 |
| `data_manager.py` | 数据缓存+API获取+完整性校验 | ✅活跃 |
| `data_source_manager.py` | 多数据源管理+自动降级+优先级调度 | ✅活跃 |

### AgentServer/src/data_sources/ (数据源适配器)

| 文件 | 职责 | 状态 |
|------|------|------|
| `base.py` | 统一接口定义+TypedDict+TokenBucket+能力声明 | ✅活跃 |
| `tushare_adapter.py` | Tushare Pro异步适配器 | ✅活跃 |
| `akshare_adapter.py` | AKShare异步适配器 | ✅活跃 |
| `baostock_adapter.py` | BaoStock异步适配器 | ✅活跃 |

### AgentServer/nodes/data_sync/ (数据同步节点)

| 文件 | 职责 | 状态 |
|------|------|------|
| `node.py` | DataSyncNode入口，调度12个Collector | ✅活跃 |
| `collectors/stock_basic.py` | 股票基础信息采集 | ✅活跃 |
| `collectors/stock_daily_ak_full.py` | 日线行情采集(主力) | ✅活跃 |
| `collectors/daily_basic.py` | 每日指标采集 | ✅活跃 |
| `collectors/index_basic.py` | 指数基础信息 | ✅活跃 |
| `collectors/index_daily.py` | 指数日线 | ✅活跃 |
| `collectors/moneyflow_industry.py` | 行业资金流 | ✅活跃 |
| `collectors/moneyflow_concept.py` | 概念资金流 | ✅活跃 |
| `collectors/limit_list.py` | 涨跌停列表 | ✅活跃 |
| `collectors/daily_stats.py` | 每日统计 | ✅活跃 |
| `collectors/news.py` | 股票新闻 | ✅活跃 |
| `collectors/fina_indicator.py` | 财务指标 | ✅活跃(第25轮修bug) |
| `collectors/hot_news.py` | 热点新闻(多源) | ✅活跃 |
| `collectors/_deprecated/` | 旧版collector(7个文件) | ⚠️废弃 |
| `generators/morning_report.py` | 早报生成 | ✅活跃 |
| `generators/noon_report.py` | 午报生成 | ✅活跃 |
| `tasks/daily_stats.py` | 每日统计任务 | ✅活跃 |
| `tasks/event_clustering.py` | 事件聚类 | ✅活跃 |
| `tasks/news_lifecycle.py` | 新闻生命周期 | ✅活跃 |

### AgentServer/nodes/backtest_engine/ (回测引擎数据相关)

| 文件 | 职责 | 状态 |
|------|------|------|
| `backtester.py` | 数据加载+回测执行 | ✅活跃 |
| `ultra_short.py` | 超短回测(1min/daily) | ✅活跃 |
| `factor_selection/factor_engine.py` | 因子计算引擎 | ✅活跃(第5轮修bug) |
| `factor_selection/factor_library.py` | 因子注册库(唯一) | ✅活跃 |
| `factor_selection/factor_auto_compute.py` | 52因子自动补算 | ✅活跃 |
| `factor_selection/FACTOR_UNITS.md` | 因子单位参考文档 | ✅活跃 |

### AgentServer/real_trading/ (实盘交易数据相关)

| 文件 | 职责 | 状态 |
|------|------|------|
| `trade_gateway.py` | 交易网关(模拟/实盘) | ✅活跃(第26/30轮修bug) |
| `auto_trade_executor.py` | 自动调仓执行 | ✅活跃(第30轮修bug) |
| `paper_trading.py` | 模拟交易 | ✅活跃(第26轮修bug) |
| `data_maintainer.py` | 数据维护 | ✅活跃 |

### AgentServer/download_daily_*.py (下载脚本)

| 文件 | 版本 | 状态 |
|------|------|------|
| `download_daily_akshare.py` | v1 | ⚠️旧版 |
| `download_daily_akshare_v2.py` | v2 | ⚠️旧版 |
| `download_daily_akshare_v3.py` | v3 | ⚠️旧版 |
| `download_daily_akshare_v4.py` | v4 | ⚠️旧版 |
| `download_daily_akshare_v5.py` | v5 | ⚠️旧版 |
| `download_daily_akshare_v6.py` | v6 (当前) | ✅使用中 |
| `download_daily_tushare_shared.py` | Tushare版 | ✅使用中 |

### AgentServer/scripts/ (运维脚本)

| 文件 | 职责 |
|------|------|
| `sync_stock_daily.py` | 同步日线 |
| `sync_stock_daily_akshare.py` | AKShare日线同步 |
| `sync_stock_basic.py` | 同步基础信息 |
| `sync_daily_basic.py` | 同步每日指标 |
| `sync_fina_indicator.py` | 同步财务指标 |
| `sync_limit_list.py` | 同步涨跌停 |
| `sync_moneyflow.py` | 同步资金流 |
| `check_sync_status.py` | 检查同步状态 |
| `fix_mongo_indexes.py` | 修复索引 |
| `fix_sync_date.py` | 修复同步日期 |
| `clear_database.py` | 清空数据库 |

---

## 七、系统性教训

### 7.1 最危险的类型："配置了但不执行"

代码有开关、有参数、有日志，唯独缺核心逻辑。运行不报错，看起来正常，实际功能完全缺失。

- **案例**: 板块集中度过滤(第9轮)、TokenBucket限流(第25轮)
- **检测方法**: 端到端追踪，不能只看单文件

### 7.2 最隐蔽的类型："因子单位不一致"

代码不报错、回测正常运行，只是策略永远0候选。不追踪数据链路根本发现不了。

- **案例**: pullback_pct存负数但过滤用正数(第15轮)、circ_mv亿→万元(第12轮)
- **检测方法**: 必须端到端追踪 数据计算→存储→筛选 的完整链路
- **防护措施**: FACTOR_UNITS.md 文档化所有因子单位

### 7.3 最频繁的类型："跨文件不一致"

字段名、函数签名、数据格式在不同文件中不统一。

- **案例**: force_empty_position vs enable_force_empty(多轮)、因子跨文件重复注册(第5轮)
- **检测方法**: 全局搜索字段名，检查models.py定义与所有使用点

### 7.4 数据层特有："硬编码假数据"

模拟/回测场景中用硬编码值代替真实数据，导致PnL恒为0、基准收益率恒为0%。

- **案例**: SimulatedGateway price=10.0(第26/30轮)、benchmark_return_pct=0.0(第9轮)、sell_price=10.0(第26轮)
- **根本原因**: 开发时为了快速验证硬编码，后续忘记替换
