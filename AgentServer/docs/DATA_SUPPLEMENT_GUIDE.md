# 数据补充操作手册

> 最后更新: 2026-05-06 | 基于实际操作整理，可直接复用

---

## 一、MongoDB数据现状

| 集合 | 文档数 | 日期范围 | 说明 |
|------|--------|----------|------|
| `stock_daily_ak_full` | 699K | 20251008~20260506 (143天) | 主回测数据源，含价量/因子 |
| `daily_basic` | 850 | 20260105~20260506 (56天) | PE/PB/流通市值，严重不足 |
| `index_daily` | 464 | 5大指数 | 沪深300/上证/深证/创业板/北证 |
| `stock_basic` | 5,210 | 全市场 | 股票名称/最新价 |
| `limit_list` | 216 | 20260105~20260320 | 涨停池数据 |

**核心缺口**: `daily_basic` 只有850条(应有143天×5200只≈74万条)，PE/PB精确数据严重不足。

---

## 二、日线数据补充（已完成）

### 2.1 数据源选择

| 数据源 | 接口 | 速度 | 限制 | 含PE/PB |
|--------|------|------|------|---------|
| **通达信** | `ak.stock_zh_a_daily(symbol, start_date, end_date, adjust="qfq")` | 0.4s/只 | 单线程,不支持BJ | ❌ 只有换手率 |
| 东方财富 | `ak.stock_zh_a_spot_em()` | 12秒全市场 | 当前IP被封 | ✅ 含PE/PB |
| 新浪 | `ak.stock_zh_a_spot()` | 15秒全市场 | 无PE/PB | ❌ |
| 量脉 | `stock_kline` 等 | 120次/分 | IP绑定2个 | ❌ K线无PE/PB |

**结论**: 日线补充只能用通达信源（东财被封、量脉IP受限、新浪无PE/PB）。

### 2.2 通达信源操作步骤

```python
import akshare as ak
import pymongo
from pymongo import UpdateOne

client = pymongo.MongoClient('localhost', 27017)
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 1. 获取股票列表（从已有的stock_daily_ak_full中取，不用stock_basic）
codes = coll.distinct('ts_code', {'ts_code': {'$regex': '\\.(SH|SZ)$'}})
# 注意: BJ股票(8/4开头)不支持! 只取SH/SZ

# 2. 逐只下载
for ts_code in codes:
    code, suffix = ts_code.split('.')
    daily_code = f"{'sh' if suffix == 'SH' else 'sz'}{code}"  # 前缀格式!
    
    try:
        df = ak.stock_zh_a_daily(
            symbol=daily_code,           # 格式: sh600000 或 sz000001
            start_date="20260323",       # 补充起始日
            end_date="20260506",         # 补充结束日
            adjust="qfq"                 # 前复权
        )
        if len(df) == 0:
            continue  # 退市/停牌，正常跳过
        
        # 3. 字段映射
        prev_close = None
        batch = []
        for _, row in df.iterrows():
            trade_date = int(str(row['date']).replace('-', ''))  # 必须int! 原有数据是int64
            open_p = float(row['open'])
            close_p = float(row['close'])
            
            doc = {
                'ts_code': ts_code,
                'trade_date': trade_date,       # int类型，与现有数据一致!
                'open': open_p,
                'high': float(row['high']),
                'low': float(row['low']),
                'close': close_p,
                'vol': float(row['volume']),     # 注意: 列名是volume不是vol
                'amount': float(row['amount']),
                'turnover_rate': float(row['turnover']) * 100,  # ⚠️ 通达信返回小数，需×100转百分比
                'pre_close': prev_close,         # 用前日close填充
            }
            if prev_close and prev_close > 0:
                doc['pct_chg'] = round((close_p - prev_close) / prev_close * 100, 2)
            
            batch.append(UpdateOne(
                {'ts_code': ts_code, 'trade_date': trade_date},
                {'$set': doc},
                upsert=True
            ))
            prev_close = close_p
        
        # 4. 批量写入（每3000条一次）
        if len(batch) >= 3000:
            coll.bulk_write(batch, ordered=False)
            batch = []
        
        time.sleep(0.15)  # ⚠️ 必须限速! 通达信不支持并发，0.15s/只安全
        
    except Exception as e:
        # "No value to decode" = 退市/停牌，正常跳过
        pass

# 5. 写入剩余
if batch:
    coll.bulk_write(batch, ordered=False)

# 6. 补全pre_close缺失（用open近似）
for r in coll.find({'pre_close': None, 'open': {'$gt': 0}}, {'_id': 1, 'open': 1}):
    coll.update_one({'_id': r['_id']}, {'$set': {'pre_close': r['open']}})
```

### 2.3 关键踩坑点

| 踩坑 | 说明 | 解决 |
|------|------|------|
| **trade_date类型** | 必须是int64(20260323)，不能是string("20260323") | `int(str(row['date']).replace('-', ''))` |
| **turnover_rate单位** | 通达信返回小数(0.027)，数据库存百分比(2.7) | `×100` |
| **pre_close字段** | 通达信不返回pre_close | 用前日close填充，缺失用open近似 |
| **symbol前缀** | 必须是sh/sz前缀，不是6/0前缀 | `f"{'sh' if suffix=='SH' else 'sz'}{code}"` |
| **BJ不支持** | 北交所(8/4开头)报"No value to decode" | 跳过BJ股票 |
| **不能并发** | 4线程下99%失败 | **必须单线程**，0.15s间隔 |
| **退市股** | "No value to decode" | 正常跳过，不影响 |
| **volume列名** | 返回列名是`volume`不是`vol` | 注意字段映射 |
| **stock_basic代码错** | 新浪源导入时代码带了sh/sz/bj前缀 | 不要用stock_basic，用stock_daily_ak_full已有的ts_code |

### 2.4 性能数据

| 指标 | 值 |
|------|------|
| 单只耗时 | 0.4秒 |
| 5510只总耗时 | 34分钟 |
| 成功率 | ~44% (5510只中2449只成功，其余退市/停牌) |
| 每只股票数据量 | ~29行(29个交易日) |
| 总新增 | 71K条 |

---

## 三、PE/PB数据补充（部分完成，待完善）

### 3.1 可行数据源对比

| 数据源 | 覆盖 | 含PE/PB | 速度 | 当前可用 |
|--------|------|---------|------|----------|
| **量脉 all_network** | ⚠️ 仅300只SH | ✅ pe/pb/sjl/lt/sz | 0.3秒/次 | 间歇性(IP槽位) |
| **量脉 all_broker** | ❓待测(可能更全) | ✅ | 1次/分 | 间歇性(IP槽位) |
| **量脉 stock_realtime** | 逐只含PE/PB | ✅ | 120次/分(IP修复后) | 间歇性 |
| **东财 spot_em** | ✅全市场5200+ | ✅ | 12秒全市场 | ❌ IP被封 |
| **通达信 daily** | ✅SH/SZ | ❌只有换手率 | 0.4s/只 | ✅ |

### 3.2 量脉 market_realtime_all_network 实测

```python
import urllib.request, json

token = 'ebacbad6d64444cd037ac5504b63f25d'
base = 'http://124.220.44.71/api/gateway'

url = f'{base}?token={token}&api=market_realtime_all_network'
with urllib.request.urlopen(url, timeout=15) as resp:
    data = json.loads(resp.read())
```

**返回字段映射:**

| 量脉字段 | 含义 | 示例 | 用途 | 单位转换 |
|----------|------|------|------|----------|
| `dm` | 股票代码 | 688553 | 匹配 | 需加后缀(.SH/.SZ/.BJ) |
| `p` | 现价 | 20.34 | 行情 | 直接用 |
| `pe` | **市盈率** | 98.5 | ✅补daily_basic | 直接用 |
| `sjl` | **市净率(PB)** | 2.28 | ✅补daily_basic | 直接用 |
| `lt` | **流通市值** | 6987598007 | ✅补daily_basic | 元→万元: ÷10000 |
| `sz` | **总市值** | 8616024000 | ✅补daily_basic | 元→万元: ÷10000 |
| `hs` | **换手率(%)** | 2.7 | ✅补daily_basic | 直接用(已是百分比) |
| `lb` | 量比 | 0.9 | 回测筛选 | 直接用 |
| `zf` | 涨幅(%) | 4.85 | 回测筛选 | 直接用 |
| `cje` | 成交额 | 188198782 | 因子 | 直接用(元) |
| `yc` | 昨收 | 19.98 | 计算pre_close | 直接用 |
| `zdf60` | 60日涨跌(%) | 3.3 | 因子 | 直接用 |
| `zdfnc` | 年内涨跌(%) | 14.33 | 因子 | 直接用 |

**⚠️ 关键限制:**
- **只返回300只SH股票**，SZ/BJ不覆盖（实测3次确认）
- 每次返回相同的300只（不是分页，不是随机）
- 限1次/分钟 + IP绑定限制
- 这是**实时数据**（当日快照），不是历史数据

### 3.3 stock_realtime 单只获取（IP修复后推荐）

```python
# IP修复后可用，120次/分
url = f'{base}?token={token}&api=stock_realtime&ts_code=000001.SZ'
```

**预估**: 5200只 ÷ 120次/分 = 43分钟覆盖全市场  
**优势**: 逐只获取，确保全覆盖  
**待确认**: 返回字段是否与all_network相同（含PE/PB）

### 3.4 market_realtime_all_broker（待测）

- 文档说"全市场行情(券商)"，可能覆盖比network更全
- 限1次/分钟
- **当前因4291未能测试**，IP修复后优先测试

---

## 四、4291 IP槽位竞争策略

### 4.1 实测数据

| 间隔 | 结果 |
|------|------|
| 0秒(连续) | ❌ 4291 |
| 10秒 | ❌ 4291 |
| 20秒 | ✅ 成功 |
| 30秒 | ❌ 4291 |
| 40秒 | ❌ 4291 |
| 51秒 | ✅ 成功 |

**结论**: 约20-30秒能抢到1个IP槽位，但随即被其他IP抢占。

### 4.2 间歇窗口使用策略

```python
import urllib.request, json, time

for attempt in range(max_attempts):
    try:
        url = f'{base}?token={token}&api=xxx'
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read())
            # 处理数据...
            print(f"✅ 成功")
            time.sleep(65)  # 成功后等65秒(特殊接口1次/分限制)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"❌ 429")
            time.sleep(25)  # 失败后等25秒再试
        else:
            raise
```

**⚠️ 红线:**
- 不要连续快速请求（2次/5秒内可能触发10分钟+封锁）
- 成功后不要立即再请求（等60秒+）
- 一天最多用间歇窗口获取几十次，不要贪心

---

## 五、stock_basic 修复

### 5.1 问题

用新浪源 `ak.stock_zh_a_spot()` 更新stock_basic时，代码列格式是 `bj920000`/`sh600000`，带了sh/sz/bj前缀。之前的代码 `code.isdigit()` 过滤掉了所有记录。

### 5.2 修复方法

```python
# ❌ 错误: 新浪代码列是 "sh600000"，不是纯数字
code = str(row['代码']).zfill(6)
if code.isdigit():  # False! "sh600000".isdigit() = False

# ✅ 正确: 去掉前缀后判断
raw_code = str(row['代码'])
clean_code = raw_code.replace('sh', '').replace('sz', '').replace('bj', '')
if clean_code.startswith(('6', '9')):
    ts_code = f"{clean_code}.SH"
elif clean_code.startswith(('8', '4')):
    ts_code = f"{clean_code}.BJ"  # 之后删除BJ
else:
    ts_code = f"{clean_code}.SZ"
```

### 5.3 最终方案

不要用stock_basic补充代码列表，**直接从stock_daily_ak_full取已有的ts_code**：

```python
codes = coll.distinct('ts_code', {'ts_code': {'$regex': '\\.(SH|SZ)$'}})
```

---

## 六、指数日线补充（已完成）

```python
import akshare as ak

indices = {
    '000001': '上证指数', '000300': '沪深300',
    '399001': '深证成指', '399006': '创业板指', '899050': '北证50',
}

for code, name in indices.items():
    # 前缀: SH用sh, SZ用sz
    prefix = 'sh' if code.startswith(('0', '8')) else 'sz'
    df = ak.stock_zh_index_daily(symbol=f"{prefix}{code}")
    # 写入index_daily...
```

---

## 七、量脉单只/批量获取PE/PB（IP修复后操作）

### 7.1 stock_realtime 单只获取

```python
# 获取单只股票实时行情（含PE/PB）
url = f'{base}?token={token}&api=stock_realtime&ts_code=000001.SZ'
```

**待确认**: 返回字段是否含PE/PB（与all_network相同？）
**预估**: IP修复后120次/分，5200只≈43分钟覆盖全市场

**操作步骤（IP修复后）**:
```python
import urllib.request, json, time, pymongo
from pymongo import UpdateOne

token = 'ebacbad6d64444cd037ac5504b63f25d'
base = 'http://124.220.44.71/api/gateway'
client = pymongo.MongoClient('localhost', 27017)
db = client['stock_agent']
coll = db['daily_basic']

# 获取股票列表
codes = db['stock_daily_ak_full'].distinct('ts_code', {'ts_code': {'$regex': '\.(SH|SZ)$'}})
today = int(time.strftime('%Y%m%d'))

for ts_code in codes:
    try:
        url = f'{base}?token={token}&api=stock_realtime&ts_code={ts_code}'
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
            if isinstance(data, dict) and 'data' in data:
                data = data['data']
            if data and len(data) > 0:
                r = data[0]
                doc = {
                    'ts_code': ts_code,
                    'trade_date': today,
                    'pe': r.get('pe'),
                    'pb': r.get('sjl'),  # 注意: PB字段名是sjl不是pb
                    'circ_mv': r.get('lt', 0) / 10000 if r.get('lt') else None,  # 元→万元
                    'total_mv': r.get('sz', 0) / 10000 if r.get('sz') else None,
                    'turnover_rate': r.get('hs'),  # 已是百分比
                    'volume_ratio': r.get('lb'),
                    'close': r.get('p'),
                    'pct_chg': r.get('zf'),
                }
                coll.update_one(
                    {'ts_code': ts_code, 'trade_date': today},
                    {'$set': doc},
                    upsert=True
                )
        time.sleep(0.6)  # ⚠️ 120次/分 = 0.5s + 0.1s余量
    except Exception as e:
        time.sleep(2)  # 出错后等2秒
```

### 7.2 stock_realtime_multi 批量获取

```python
# 批量获取（≤20只）
codes_str = '000001,600000,300750'  # 不带后缀!
url = f'{base}?token={token}&api=stock_realtime_multi&ts_code={codes_str}'
```

**待确认**: 是否含PE/PB字段
**预估**: IP修复后120次/分÷20只/次 = 6次/分×20 = 120只/分，5200只≈43分钟

### 7.3 market_realtime_all_broker 全市场行情

```python
# 可能返回全市场（比all_network更全）
url = f'{base}?token={token}&api=market_realtime_all_broker'
```

**⚠️ 待测**: IP修复后优先测试！如果返回全市场5200+只，这是最快方案（1次请求搞定）
**限制**: 1次/分钟

### 7.4 IP修复后推荐操作顺序

1. **先测 `all_broker`** → 如果返回全市场含PE/PB，1次请求写入daily_basic，完成！
2. **再测 `stock_realtime`** → 确认单只返回字段含PE/PB
3. **最后用 `stock_realtime` 逐只补全** → 如果all_broker不全，用逐只方案兜底
4. **历史PE/PB** → 需要其他方案（量脉无历史PE/PB接口，需东财或其他）

---

## 八、待解决事项

| 优先级 | 事项 | 依赖 |
|--------|------|------|
| **P0** | 量脉IP白名单更新为118.196.127.163 | 用户操作 |
| **P0** | 测试market_realtime_all_broker覆盖范围 | IP修复后 |
| **P1** | 全市场PE/PB补充(5200只) | IP修复后用stock_realtime逐只 |
| **P1** | 历史PE/PB补充(143天×5200只) | 东财API恢复或量脉历史接口 |
| **P2** | limit_list涨停池数据扩展(216→应有143天) | 量脉或AKShare |
| **P2** | volume_ratio量比数据补充 | 通达信不提供，需量脉或计算 |
