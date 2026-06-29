# 数据采补策略文档

> 2026-06-29 建立。数据总是缺失是因为采补策略不完善，此文档为完整整理。

## 一、数据源概览

| 数据源 | 用途 | 限制 | 盘中可用 | 盘后可用 |
|--------|------|------|----------|----------|
| 东方财富 push2 | 全市场快照(OHLCV+PE/PB) | 无限流 | ✅ | ❌ RemoteDisconnected |
| 东方财富 datacenter | 财务数据 | 需要正确reportName | ✅ | ✅ |
| AKShare | 历史日线下载 | 依赖网络 | ✅ | ✅ |
| 搜狐财经 hisHq | 历史日K线 | 日期格式YYYYMMDD | ✅ | ✅ |
| 必盈API | 涨停池数据 | 200次/天 | ✅ | ✅ |
| Tushare | daily/daily_basic批量 | 5000积分 | ✅ | ✅ |
| 量脉API | 实时盘中/分钟K线 | 120/min, 2IP | ✅ | ❌ DNS不解析 |

## 二、采集时间窗口

### 盘中 (09:00-15:00)
- **行情**: 东方财富 push2 ✅ (主力, 无限流)
- **涨停池**: 必盈API ✅ (200次/天)
- **实时分钟K**: 量脉API ⚠️ (IP限制, 4291不重试)

### 盘后 (15:00-23:59)
- **日K线**: 搜狐 hisHq ✅ (主力备选)
- **PE/PB/市值**: 东方财富 push2 ❌ → 搜狐无PE/PB → **需要Tushare或次日补**
- **涨停池**: 必盈API ✅ / 从日K线pct_chg推算(精度低)

### 盘前 (07:00-09:00)
- **日K线**: 东方财富 push2 ❌ (盘前不服务)
- **PE/PB**: 东方财富 push2 ❌
- **备选**: 搜狐 hisHq ✅ (历史数据)

## 三、字段单位标准 (MongoDB stock_daily_ak_full)

| 字段 | 单位 | 说明 |
|------|------|------|
| vol | 手 | 成交量(1手=100股) |
| amount | 百元 | 成交额(1百元=100元) |
| turnover_rate | 百分数 | 换手率(如25.04表示25.04%) |
| pct_chg | 百分数 | 涨跌幅(如1.31表示1.31%) |
| close/open/high/low | 元 | 价格 |
| pre_close | 元 | 昨收价 |

### 各数据源原始单位 → 标准单位 转换

| 数据源 | vol原始 | vol转换 | amount原始 | amount转换 | turn原始 | turn转换 |
|--------|---------|---------|------------|------------|----------|----------|
| 东方财富/AKShare | 手 | 无需转换 | 百元 | 无需转换 | % | 无需转换 |
| 搜狐 hisHq | 手 | 无需转换 | 万元 | ×100→百元 | 小数 | ×100→百分数 |
| Tushare | 手 | 无需转换 | 千元 | ×10→百元 | % | 无需转换 |

## 四、字段完整性对比

### 东方财富完整字段 (38个)
```
基础: ts_code, trade_date, open, high, low, close, pre_close, pct_chg, vol, amount, 
      turnover_rate, updated_at, change, amplitude
涨跌停: is_limit_up, is_limit_down, limit_up_count, limit_down_count, 
        limit_up_yesterday, limit_down_yesterday, first_limit_up,
        open_above_limit, open_below_limit, open_above_limit_down
技术: ma5, ma10, ma20, ma60, macd, rsi_6, boll_upper, atr
派生: intraday_max_rise_pct, intraday_open_rise_pct, opening_pct_chg,
      pullback_days, pullback_pct, pullback_ma5, volume_increase
其他: hot_sector, market_leader, sentiment_score
```

### 搜狐补采字段 (12个)
```
ts_code, trade_date, open, high, low, close, pre_close, pct_chg, 
vol, amount, turnover_rate, updated_at
```

### 缺失的26个字段 — 影响分析

| 字段 | 策略筛选依赖 | 信号描述依赖 | 实时补算 | 影响 |
|------|-------------|-------------|----------|------|
| is_limit_up | ✅ 首板/跌停 | ✅ | ✅ _classify_limit实时推算 | 无影响 |
| is_limit_down | ✅ 跌停翘板 | ✅ | ✅ 同上 | 无影响 |
| limit_up_count | ✅ 首板 | ✅ | ✅ =is_limit_up | 无影响 |
| intraday_max_rise_pct | ✅ 半路追涨 | ✅ | ✅ (high-pre_close)/pre_close | 无影响 |
| intraday_open_rise_pct | ✅ 半路追涨 | ✅ | ✅ (open-pre_close)/pre_close | 无影响 |
| opening_pct_chg | ✅ | ✅ | ✅ 同上 | 无影响 |
| first_limit_up | ✅ 首板 | ✅ | ✅ is_limit_up & !is_limit_up_prev | 无影响 |
| open_above_limit_down | ✅ 跌停翘板 | ✅ | ✅ opening_pct_chg<=-8.5 | 无影响 |
| open_above_limit | ❌ | ✅ | ❌ | 信号描述缺值,不影响筛选 |
| open_below_limit | ❌ | ✅ | ❌ | 同上 |
| ma5 | ❌ | ✅ 描述MA5偏离 | ❌ | 信号描述缺值 |
| ma10/ma20/ma60 | ❌ | ❌ | ❌ | 无影响(未使用) |
| macd/rsi_6/boll_upper/atr | ❌ | ✅ rsi_6超买超卖 | ❌ | 信号描述缺值 |
| limit_up_yesterday | ✅ 龙头低吸 | ✅ | ✅ 从is_limit_up_prev推算 | 无影响 |
| limit_down_yesterday | ❌ | ✅ | ✅ 同上 | 无影响 |
| pullback_days/pullback_pct | ❌ 策略补0 | ✅ | ❌ 补0 | 策略条件用0,不影响筛选 |
| pullback_ma5 | ❌ | ❌ | ❌ | 无影响 |
| volume_increase | ❌ | ❌ | ❌ | 无影响 |
| hot_sector | ❌ | ❌ | ❌ | 无影响 |
| market_leader | ❌ | ✅ 龙头低吸描述 | ❌ | 信号描述缺值 |
| sentiment_score | ❌ | ✅ | ❌ | 信号描述缺值 |
| amplitude | ❌ | ❌ | ❌ | 无影响 |
| change | ❌ | ❌ | ❌ | 无影响 |
| limit_down_count | ✅ 跌停翘板 | ✅ | ✅ =is_limit_down | 无影响 |

**结论**: 搜狐补采的12个字段 + _merge_factors实时补算 → **策略筛选完全不受影响**。
信号描述中 ma5/rsi_6/market_leader 等显示为0,但不影响候选股生成。

## 五、采补流程 (每日)

### A. 盘后自动采补 (15:30 cron)

```
15:30  东方财富 push2 (如果可用) → stock_daily_ak_full + daily_basic
       ↓ 失败则
       搜狐 hisHq 批量拉取 → stock_daily_ak_full
       必盈API → limit_list
       ↓
15:35  数据完整性检查
       - 条数 > 4000?
       - 字段单位一致性?
       - 与前日数据交叉验证
       ↓
15:40  daily_basic 补充
       - PE/PB: 用最近东方财富完整日基准近似
       - total_mv: 用pct_chg调整
       ↓
15:45  技术指标补算 (ma5/ma10/ma20/ma60/macd/rsi_6)
       - 需要前20日数据,从MongoDB批量读取计算
```

### B. 盘前补采 (07:00 cron)

```
07:00  检查昨日数据完整性
       - stock_daily_ak_full 条数 > 4000?
       - daily_basic 条数 > 4000?
       - limit_list 条数 > 0?
       ↓ 缺失则
       搜狐 hisHq 补采昨日日K线
       必盈API 补采昨日涨停池
       ↓
07:15  东方财富 push2 (盘前可能可用) 补PE/PB
       ↓
07:30  数据质量报告
```

### C. 盘中实时 (09:00-15:00)

```
每轮扫描: 东方财富 push2 实时行情 → _merge_factors 实时补算
无需DB日级数据,实时数据自包含策略所需字段
```

## 六、数据质量检查清单

### 写入前检查
1. **单位转换**: 确认数据源原始单位 → MongoDB标准单位
2. **字段名映射**: turn→turnover_rate, chg→change 等
3. **空值处理**: None/NaN/0 的语义区分

### 写入后检查
1. **条数**: stock_daily_ak_full > 4000 (排除停牌)
2. **单位交叉验证**: 同一股票 vol/amount/turnover_rate 与前日比值在 0.3x~3x 范围内
3. **字段完整性**: 东方财富来源应有38字段,搜狐来源至少12字段
4. **pct_chg一致性**: (close-pre_close)/pre_close*100 ≈ pct_chg (容差0.01%)

### 定期审计 (每周)
1. 跑 `scripts/data_integrity_check.py`
2. 对比 MongoDB vs 东方财富原始数据抽样10只
3. 检查 limit_list 的 open_times 字段(必盈API有,推算为0)

## 七、已知问题

### 7.1 东方财富 push2 盘后不服务
- **现象**: `RemoteDisconnected('Remote end closed connection without response')`
- **原因**: push2是行情推送接口,非交易时段不返回数据
- **影响**: 盘后无法用东方财富补采日K线和PE/PB
- **对策**: 搜狐 hisHq 作为备选(日K线),PE/PB用基准近似或次日补

### 7.2 量脉API DNS不解析
- **现象**: `Failed to resolve 'api.liangmai8.com'`
- **原因**: DNS配置问题或服务下线
- **影响**: 盘中实时分钟K线不可用
- **对策**: 东方财富 push2 替代(无限流)

### 7.3 搜狐补采缺失技术指标
- **现象**: ma5/rsi_6/macd 等为空
- **原因**: 搜狐只提供OHLCV基础数据
- **影响**: 信号描述中MA5偏离/RSI超买超卖显示为0
- **对策**: 盘后用历史数据补算技术指标(待实现),或接受描述缺值(不影响筛选)

### 7.4 limit_list open_times 从日K线推算为0
- **现象**: 推算的limit_list中open_times全为0
- **原因**: 日K线只有收盘数据,无法判断盘中是否炸板
- **影响**: 炸板率统计偏低(但emotion_cycle已修复从limit_list的open_times>0统计)
- **对策**: 必盈API补采(有open_times字段),或盘中实时记录

## 八、采补脚本

| 脚本 | 用途 | 数据源 | 触发 |
|------|------|--------|------|
| eastmoney_daily_bar.py | 全市场OHLCV | 东方财富push2 | 盘后cron |
| eastmoney_daily_basic.py | PE/PB/流通市值 | 东方财富push2 | 盘后cron |
| sohu_fill_daily.py | 日K线补采 | 搜狐hisHq | 东方财富失败时 |
| fill_limit_list.py | 涨停池补采 | 必盈API | 盘后cron |
| tushare_fill_v2.py | daily/daily_basic批量 | Tushare | 手动/周补 |
| data_integrity_check.py | 数据质量检查 | MongoDB | 每日盘前 |

## 九、版本历史

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-29 | v1.0 | 初始建立。发现并修复搜狐补采vol/amount/turnover_rate单位不一致(3个bug) |
