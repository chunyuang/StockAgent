# 数据补充操作手册

> 最后更新: 2026-05-06 20:30 | 分支: fix/data-quality-and-docs
> 基于完整实测整理，包含成功方案和失败教训，避免重复踩坑

---

## 一、MongoDB数据现状（2026-05-06）

| 集合 | 文档数 | 日期范围 | 说明 |
|------|--------|----------|------|
| `stock_daily_ak_full` | 699K | 20251008~20260506 (143天) | 主回测数据源，含价量/因子 |
| `daily_basic` | 8,711 | 20260105~20260506 (57天) | PE/PB/流通市值，今日8161只 |
| `index_daily` | 464 | 5大指数 | 沪深300/上证/深证/创业板/北证 |
| `stock_basic` | 5,511 | 全市场(SH+SZ) | 股票名称/ST标记 |
| `limit_list` | 216 | 20260105~20260320 | 涨停池数据 |

---

## 二、数据源全景（实测结果）

### 2.1 成功的数据源

| 数据源 | 接口 | 用途 | 速度 | 限制 | 实测状态 |
|--------|------|------|------|------|----------|
| **通达信(AKShare)** | `ak.stock_zh_a_daily()` | 日线K线+换手率 | 0.4s/只 | 单线程,无BJ,无PE/PB | ✅ 稳定可用 |
| **新浪(AKShare)** | `ak.stock_zh_a_spot()` | stock_basic股票列表 | 15秒/全市场 | 无PE/PB | ✅ 稳定可用 |
| **量脉broker** | `market_realtime_all_broker` | **全市场PE/PB** | 1次请求 | 1次/分,IP绑定 | ✅ 间歇可用 |
| **量脉network** | `market_realtime_all_network` | 流通市值/换手率/量比 | 1次请求 | 1次/分,仅300只SH | ⚠️ 间歇可用 |
| **量脉realtime** | `stock_realtime` | 单只全字段 | 120次/分 | IP绑定 | ⚠️ 间歇可用 |
| **量脉涨停池** | `get_pool_limit_up` | 涨停股票列表 | 1次/分 | 日期格式yyyy-MM-dd | ✅ 可用 |

### 2.2 失败的数据源（不要重试！）

| 数据源 | 接口 | 失败原因 | 失败时间 | 最后确认 |
|--------|------|----------|----------|----------|
| **东方财富** | `ak.stock_zh_a_spot_em()` | IP被拒, Connection aborted | 2026-05-06 | HTTP 000 |
| **Tushare官方** | `tushare.pro_api()` | Token失效(积分不足) | 2026-05-06 | 无数据返回 |
| **Tushare代理** | 代理token | 代理Token也失效 | 2026-05-06 | 无数据返回 |
| **腾讯(AKShare)** | `ak.stock_zh_a_hist_tx()` | 接口bug,返回异常 | 2026-04 | 数据不完整 |
| **通达信并发** | `stock_zh_a_daily` 4线程 | 99%错误率 | 2026-05-06 | 必须单线程 |

### 2.3 数据源选择决策树

```
需要什么数据？
├── 日线K线(开高低收量+换手率) → 通达信 stock_zh_a_daily（唯一选择）
├── PE/PB → 量脉 all_broker（最快,1次8479只）
├── 流通市值/换手率/量比 → 量脉 all_network（仅300只SH）或 stock_realtime逐只
├── 股票列表+名称 → 新浪 stock_zh_a_spot
├── 涨停池 → 量脉 get_pool_limit_up
├── 指数日线 → 通达信 stock_zh_index_daily
└── 历史PE/PB → ⚠️ 无可用数据源！东财被封+Tushare失效+量脉无历史接口
```

---

## 三、日线数据补充

### 3.1 通达信源完整步骤

```python
import akshare as ak
import pymongo
from pymongo import UpdateOne
import time

client = pymongo.MongoClient('localhost', 27017)
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 1. 获取股票列表（从stock_daily_ak_full取，不用stock_basic）
codes = coll.distinct('ts_code', {'ts_code': {'$regex': '\\.(SH|SZ)$'}})
# ⚠️ BJ股票(8/4开头)不支持!

# 2. 逐只下载
for ts_code in codes:
    code, suffix = ts_code.split('.')
    daily_code = f"{'sh' if suffix == 'SH' else 'sz'}{code}"
    
    try:
        df = ak.stock_zh_a_daily(
            symbol=daily_code,
            start_date="20260323",
            end_date="20260506",
            adjust="qfq"
        )
        if len(df) == 0:
            continue  # 退市/停牌
        
        prev_close = None
        batch = []
        for _, row in df.iterrows():
            trade_date = int(str(row['date']).replace('-', ''))
            open_p = float(row['open'])
            close_p = float(row['close'])
            
            doc = {
                'ts_code': ts_code,
                'trade_date': trade_date,
                'open': open_p,
                'high': float(row['high']),
                'low': float(row['low']),
                'close': close_p,
                'vol': float(row['volume']),
                'amount': float(row['amount']),
                'turnover_rate': float(row['turnover']) * 100,
                'pre_close': prev_close,
            }
            if prev_close and prev_close > 0:
                doc['pct_chg'] = round((close_p - prev_close) / prev_close * 100, 2)
            
            batch.append(UpdateOne(
                {'ts_code': ts_code, 'trade_date': trade_date},
                {'$set': doc},
                upsert=True
            ))
            prev_close = close_p
        
        if len(batch) >= 3000:
            coll.bulk_write(batch, ordered=False)
            batch = []
        
        time.sleep(0.15)  # ⚠️ 必须限速!
    except Exception as e:
        pass  # "No value to decode" = 退市/停牌

if batch:
    coll.bulk_write(batch, ordered=False)
```

### 3.2 踩坑清单

| # | 踩坑 | 详情 | 解决 |
|---|------|------|------|
| 1 | **trade_date必须是int** | 数据库存int64，string会导致查询不匹配 | `int(str(row['date']).replace('-',''))` |
| 2 | **turnover_rate单位** | 通达信返回小数(0.027)，数据库存百分比(2.7) | `×100` |
| 3 | **pre_close不存在** | 通达信不返回此字段 | 用前日close填充，缺失用open |
| 4 | **pct_chg也不返回** | 新增数据的pct_chg=None会导致回测崩溃 | `(close-pre_close)/pre_close*100` |
| 5 | **symbol前缀** | 必须是sh600000格式，不是600000 | `f"{'sh' if SH else 'sz'}{code}"` |
| 6 | **BJ不支持** | 北交所报"No value to decode" | 跳过BJ |
| 7 | **不能并发！** | 4线程99%错误率 | 单线程+0.15s间隔 |
| 8 | **volume列名** | DataFrame列名是`volume`不是`vol` | 注意映射 |
| 9 | **stock_basic代码错** | 新浪源代码带sh/sz/bj前缀 | 直接从stock_daily_ak_full取ts_code |
| 10 | **amount单位不一致** | 旧数据(通达信)=千元, 新数据(AKShare)=元 | 不可混用反算circ_mv! |
| 11 | **vol单位不一致** | 旧数据=手, 新数据=股 | 不可混用! |
| 12 | **close复权差异** | 旧数据=前复权, 新数据=真实价 | 反算circ_mv会偏差1.7倍 |

### 3.3 ⚠️ 新增数据后必做的修复步骤

通达信源只返回OHLCV+换手率，以下字段需要额外处理：

```python
# 1. 补全pct_chg（新增数据可能为None）
coll.update_many(
    {'pct_chg': None, 'close': {'$exists': True}, 'pre_close': {'$exists': True, '$gt': 0}},
    [{'$set': {'pct_chg': {'$round': [{'$multiply': [
        {'$divide': [{'$subtract': ['$close', '$pre_close']}, '$pre_complete']}, 100]}, 2]}}}]
)

# 2. 补全pre_close缺失（用open近似）
coll.update_many(
    {'pre_close': None, 'open': {'$gt': 0}},
    [{'$set': {'pre_close': '$open'}}]
)

# 3. circ_mv/turnover_rate/volume_ratio：通达信不提供
#    circ_mv: 需要量脉或东财补充
#    volume_ratio: 需要量脉补充
#    turnover_rate: 通达信提供，但只覆盖部分股票
```

### 3.4 性能数据

| 指标 | 值 |
|------|------|
| 单只耗时 | 0.4秒 |
| 5510只总耗时 | 34分钟 |
| 成功率 | ~44% (其余退市/停牌) |
| 5510只×29天 | 71K条新数据 |

---

## 四、PE/PB数据补充

### 4.1 ⭐ 最佳方案：量脉 market_realtime_all_broker

**实测结果：1次请求获取8479只股票的PE/PB，SH+SZ全覆盖！**

```python
import urllib.request, json, pymongo, time
from pymongo import UpdateOne

token = 'ebacbad6d64444cd037ac5504b63f25d'
base = 'http://124.220.44.71/api/gateway'
client = pymongo.MongoClient('localhost', 27017)
db = client['stock_agent']
coll = db['daily_basic']
today = int(time.strftime('%Y%m%d'))

url = f'{base}?token={token}&api=market_realtime_all_broker'
with urllib.request.urlopen(url, timeout=30) as resp:
    data = json.loads(resp.read())
    if isinstance(data, dict) and 'data' in data:
        data = data['data']

batch = []
for r in data:
    dm = str(r.get('dm', '')).zfill(6)
    if len(dm) != 6 or not dm.isdigit():
        continue
    if dm.startswith(('6', '9')):
        ts_code = f"{dm}.SH"
    elif dm.startswith(('8', '4')):
        ts_code = f"{dm}.BJ"
    else:
        ts_code = f"{dm}.SZ"
    
    doc = {
        'ts_code': ts_code,
        'trade_date': today,
        'pe': r.get('pe'),              # 市盈率
        'pb': r.get('pb_ratio'),        # ⚠️ 字段名是pb_ratio, 不是sjl!
        'close': r.get('p'),
        'pct_chg': r.get('zf'),
    }
    batch.append(UpdateOne(
        {'ts_code': ts_code, 'trade_date': today},
        {'$set': doc},
        upsert=True
    ))

coll.bulk_write(batch, ordered=False)
```

**broker源字段：**

| 字段 | 含义 | 备注 |
|------|------|------|
| `pe` | 市盈率 | ✅ 直接用 |
| `pb_ratio` | 市净率(PB) | ⚠️ 不是`sjl`! |
| `p` | 现价 | |
| `zf` | 涨幅(%) | |
| `cje` | 成交额(元) | |

**broker源缺：** hs(换手率)、lt(流通市值)、sz(总市值)、lb(量比)、BJ股票

### 4.2 补充流通市值：量脉 market_realtime_all_network

```python
# 仅返回300只SH股票，但有完整的流通市值/换手率
url = f'{base}?token={token}&api=market_realtime_all_network'
```

**network源字段：**

| 字段 | 含义 | 单位转换 |
|------|------|----------|
| `pe` | 市盈率 | 直接用 |
| `sjl` | 市净率(PB) | ⚠️ 字段名是`sjl`, 不是`pb_ratio`! |
| `lt` | 流通市值 | 元→万元: ÷10000 |
| `sz` | 总市值 | 元→万元: ÷10000 |
| `hs` | 换手率(%) | 直接用(已是百分比) |
| `lb` | 量比 | 直接用 |

### 4.3 三个量脉接口对比

| | all_broker | all_network | stock_realtime |
|---|-----------|-------------|----------------|
| **覆盖** | **8479只(SH+SZ)** | 300只(SH only) | 逐只 |
| **PE** | ✅ `pe` | ✅ `pe` | ✅ `pe` |
| **PB** | ✅ `pb_ratio` | ✅ `sjl` | ✅ `sjl` |
| **流通市值** | ❌ | ✅ `lt`(元) | ✅ `lt`(元) |
| **换手率** | ❌ | ✅ `hs` | ✅ `hs` |
| **量比** | ❌ | ✅ `lb` | ✅ `lb` |
| **总市值** | ❌ | ✅ `sz` | ✅ `sz` |
| **频率** | 1次/分 | 1次/分 | 120次/分 |
| **推荐用途** | 全市场PE/PB | 补SH流通市值 | 逐只补全字段 |

### 4.4 推荐操作顺序

1. **`all_broker`** → 8479只PE/PB，1次请求 ✅
2. **`all_network`** → 补300只SH流通市值/换手率/量比
3. **`stock_realtime`** → 逐只补SZ流通市值/换手率（需IP修复后稳定使用）

### 4.5 失败经验汇总

#### 4.5.1 all_network 误用教训

**踩坑**：最初用`all_network`获取PE/PB，以为文档说的"全市场"是全市场5200+只，实际只有300只SH。浪费了大量时间在间歇窗口策略上。

**正确做法**：应该先测试`all_broker`接口，它才是真正的全市场行情源。`all_network`只适合补充broker源缺失的流通市值/换手率字段。

#### 4.5.2 amount/turnover_rate反算circ_mv失败

**尝试**：用 `circ_mv = amount / (turnover_rate/100) / 10000` 反算SZ的流通市值。

**失败原因**：stock_daily_ak_full的amount单位在20260323前后不一致：

| 字段 | 旧数据(通达信, ≤20260320) | 新数据(AKShare, ≥20260323) |
|------|---------------------------|---------------------------|
| `amount` | **千元** | **元** |
| `vol` | **手**(×100=股) | **股** |
| `close` | **前复权价**(56元 vs 真实1400元) | **真实价** |
| `turnover_rate` | 基于前复权计算 | 基于真实价计算 |

**结果**：反算circ_mv偏差1.7倍(宁德时代反算19500亿 vs 实际11200亿)。

**教训**：
1. **不同数据源的字段单位不同！** 通达信和AKShare的amount/vol/close含义完全不同
2. **前复权价格导致成交额/换手率失真**，不能用来反算流通市值
3. **circ_mv必须从量脉实时接口获取**，不能从日线数据反算
4. 已清除26526条错误的SZ circ_mv反算数据

#### 4.5.3 量脉stock_realtime获取SZ失败(429)

**尝试**：IP间歇窗口期用stock_realtime逐只补2510只SZ的circ_mv。

**失败**：HTTP 429连续被拒，IP槽位被其他IP持续占用。

**结论**：间歇窗口只能获取1-2次请求（每次1只），不适合批量操作。2510只SZ需等IP白名单修复。

---

## 五、量脉使用规则

### 5.1 限流规则

| 规则 | 详情 |
|------|------|
| 频率限制 | 120次/分钟 |
| IP限制 | Token绑定2个IP（当前服务器IP 118.196.127.163 不在白名单） |
| 特殊接口 | all_broker/all_network 限1次/分钟 |
| 缓存TTL | 60秒（相同请求不重计） |
| 涨停池日期 | 格式必须yyyy-MM-dd（不是yyyyMMdd） |

### 5.2 4291 IP槽位竞争

**根因**：Token绑定2个IP槽位，当前服务器IP不在白名单，与另一个IP竞争使用。

**实测（10秒间隔6次请求）：**
```
0s:  ❌ 4291
10s: ❌ 4291
20s: ✅ 成功
30s: ❌ 4291
40s: ❌ 4291
51s: ✅ 成功
```

**间歇窗口策略：**
- 约20-30秒能抢到1个IP槽位
- 成功后等65秒（特殊接口1次/分）
- 失败后等25秒重试
- ⚠️ 不要连续快速请求（触发10分钟+封锁）

### 5.3 HTTP 429 vs JSON 4291

| 类型 | 返回格式 | 原因 | 处理 |
|------|----------|------|------|
| HTTP 429 | HTML/JSON body | nginx层频率超限 | 重建session+等5s |
| JSON code=4291 | 正常JSON | 业务层IP超限 | 等20-30秒再试 |

**踩坑**：之前aiohttp代码只处理4291，没处理HTTP 429，导致JSON解析失败→异常→重试循环→IP被长期封禁。

### 5.4 ⚠️ 量脉使用红线

1. **不要连续快速测试** — 2次/5秒内可能触发10分钟封锁
2. **成功后不立即再请求** — 至少等60秒
3. **一天最多间歇获取几十次** — 不要贪心
4. **根本解决：更新IP白名单为 118.196.127.163**

---

## 六、stock_basic 补充

### 6.1 新浪源修复步骤

```python
import akshare as ak
import pymongo

client = pymongo.MongoClient('localhost', 27017)
db = client['stock_agent']
sb = db['stock_basic']

df = ak.stock_zh_a_spot()  # 获取全市场列表

records = []
for _, row in df.iterrows():
    raw_code = str(row.get('代码', ''))
    name = str(row.get('名称', ''))
    
    # 去掉sh/sz/bj前缀
    clean = raw_code.replace('sh', '').replace('sz', '').replace('bj', '')
    if not clean.isdigit() or len(clean) != 6:
        continue
    
    if clean.startswith(('6', '9')):
        ts_code = f"{clean}.SH"
    elif clean.startswith(('8', '4')):
        ts_code = f"{clean}.BJ"
    else:
        ts_code = f"{clean}.SZ"
    
    records.append({
        'ts_code': ts_code,
        'name': name,
        'is_st': 'ST' in name or '*ST' in name,
    })

sb.delete_many({})
sb.insert_many(records)
```

### 6.2 踩坑

| 问题 | 原因 | 解决 |
|------|------|------|
| 代码列带前缀 | 新浪返回`sh600000`不是`600000` | 去掉sh/sz/bj前缀 |
| `isdigit()`过滤全部 | `"sh600000".isdigit()` = False | 先去前缀再判断 |
| BJ股票 | 新浪不含北交所 | stock_basic中BJ=0，但回测也不用BJ数据 |

---

## 七、因子数据修复

### 7.1 pct_chg缺失（通达信不返回）

```python
# 新增数据的pct_chg=None，回测计算index_change时NoneType崩溃
coll.update_many(
    {'pct_chg': None, 'close': {'$exists': True}, 'pre_close': {'$exists': True, '$gt': 0}},
    [{'$set': {'pct_chg': {'$round': [{'$multiply': [
        {'$divide': [{'$subtract': ['$close', '$pre_close']}, '$pre_close']}, 100]}, 2]}}}]
)
```

**实测**：2449条None→全部补全，回测不再崩溃。

### 7.2 pullback_pct（龙头低吸因子）

```python
# 正确公式: (10日最高价 - 收盘价) / 10日最高价 = 回调幅度(正数)
# ⚠️ 存为正数! 0.15 = 回调15%
high_peak = group['high'].rolling(10).max()
group['pullback_pct'] = (high_peak - group['close']) / high_peak
```

**踩坑**：factor_auto_compute原代码是`(close - high_peak) / high_peak`产生负数，但MongoDB中实际存的是正数（被其他进程用不同公式覆盖）。策略筛选条件写的是`pullback_pct >= min_correction`（正数比较），所以必须存正数。

### 7.3 limit_up_count（龙头低吸因子）

```python
# factor_auto_compute原代码: 连续涨停天数(3连板=3)
# 龙头低吸需要: 近5日涨停次数(5日内3个涨停=3，不管是否连续)
is_lu_int = group['is_limit_up'].astype(int)
group['limit_up_count'] = is_lu_int.rolling(5, min_periods=1).sum().astype(int)
```

**踩坑**：factor_auto_compute原来存的是连续涨停天数，但策略用"近5日至少N板"语义，需要5日滚动求和。

### 7.4 turnover_rate=100.0 恒等bug

**根因**：`compute_all_factors.py`中`circ_mv=amount*100`, `turnover_rate=amount/circ_mv*10000`恒等于100。

**修复方案**：用AKShare `stock_zh_a_spot_em`一次拉全市场流通市值，反算历史换手率 `amount/circ_mv*100`。

**踩坑**：修复后被data_sync进程(PID 2833575, 5月1日起运行)覆盖回100.0。需确保data_sync进程已停止或修改其计算逻辑。

---

## 八、回测引擎数据相关bug

### 8.1 index_change NoneType崩溃

**现象**：`'>=' not supported between instances of 'NoneType' and 'int'`

**根因**：新增数据的pct_chg=None，MongoDB `$avg: "$pct_chg"` 返回None。

**修复**：
```python
# portfolio_backtest.py
if index_change is None:
    index_change = 0.0
```

### 8.2 回测参数格式

**踩坑**：ultra_short读取`params.params`子对象，脚本直接传顶层参数会使用默认值。

```python
# ❌ 错误：参数在顶层
params = {"start_date": "20260301", "enable_force_empty": False, ...}

# ✅ 正确：三层嵌套
params = {
    "params": {
        "start_date": "20260301",
        "enable_force_empty": False,  # 默认是True! 必须显式设False
        "selected_strategies": [...],
        "params": {"stop_loss_pct": 0.02, ...},
    }
}
```

**关键默认值**：
- `start_date` 默认 `"20260105"`（不是你要的日期！）
- `end_date` 默认 `"20260320"`
- `enable_force_empty` 默认 `True`（频繁触发强制空仓！）

---

## 九、量脉每日数据更新流程（IP修复后）

```python
#!/usr/bin/env python3
"""每日数据更新 - 17:00后执行"""
import urllib.request, json, pymongo, time
from pymongo import UpdateOne

token = 'ebacbad6d64444cd037ac5504b63f25d'
base = 'http://124.220.44.71/api/gateway'
client = pymongo.MongoClient('localhost', 27017)
db = client['stock_agent']
coll = db['daily_basic']
today = int(time.strftime('%Y%m%d'))

# Step 1: all_broker → 全市场PE/PB (1次请求)
url = f'{base}?token={token}&api=market_realtime_all_broker'
with urllib.request.urlopen(url, timeout=30) as resp:
    data = json.loads(resp.read())
    if isinstance(data, dict) and 'data' in data:
        data = data['data']

batch = []
for r in data:
    dm = str(r.get('dm', '')).zfill(6)
    if len(dm) != 6 or not dm.isdigit(): continue
    ts_code = f"{dm}.SH" if dm.startswith(('6','9')) else f"{dm}.SZ"
    batch.append(UpdateOne(
        {'ts_code': ts_code, 'trade_date': today},
        {'$set': {
            'pe': r.get('pe'),
            'pb': r.get('pb_ratio'),
            'close': r.get('p'),
            'pct_chg': r.get('zf'),
        }},
        upsert=True
    ))
coll.bulk_write(batch, ordered=False)
print(f"Step1: {len(batch)}只PE/PB写入")

time.sleep(65)  # 等1分钟(特殊接口限制)

# Step 2: all_network → 补SH的流通市值/换手率 (1次请求)
url = f'{base}?token={token}&api=market_realtime_all_network'
with urllib.request.urlopen(url, timeout=15) as resp:
    data = json.loads(resp.read())
    if isinstance(data, dict) and 'data' in data:
        data = data['data']

batch = []
for r in data:
    dm = str(r.get('dm', '')).zfill(6)
    if len(dm) != 6 or not dm.isdigit(): continue
    ts_code = f"{dm}.SH" if dm.startswith(('6','9')) else f"{dm}.SZ"
    batch.append(UpdateOne(
        {'ts_code': ts_code, 'trade_date': today},
        {'$set': {
            'circ_mv': r.get('lt', 0) / 10000 if r.get('lt') else None,
            'total_mv': r.get('sz', 0) / 10000 if r.get('sz') else None,
            'turnover_rate': r.get('hs'),
            'volume_ratio': r.get('lb'),
        }},
        upsert=True
    ))
coll.bulk_write(batch, ordered=False)
print(f"Step2: {len(batch)}只流通市值/换手率补充")
print(f"完成: daily_basic今日 {coll.count_documents({'trade_date': today})}只")
```

---

## 十、待解决事项

| 优先级 | 事项 | 依赖 | 备注 |
|--------|------|------|------|
| **P0** | 量脉IP白名单更新 | 用户操作 | IP: 118.196.127.163 |
| **P1** | SZ流通市值/换手率/量比 | IP修复后stock_realtime | broker源缺这些字段 |
| **P1** | 历史PE/PB(143天) | 东财API恢复 | 量脉无历史PE/PB接口 |
| **P2** | BJ股票数据 | 无可用数据源 | 通达信/量脉都不含BJ |
| **P2** | limit_list扩展(216→143天) | 量脉 | 需逐日获取 |
| **P2** | 新增29天数据的circ_mv | 量脉或反算 | 通达信不提供 |
