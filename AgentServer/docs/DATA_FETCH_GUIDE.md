# 数据获取操作手册

> 最后更新: 2026-05-08
> 分支: fix/data-layer-and-docs

---

## ⚠️ 数据统一标准（最高优先级）

**所有写入MongoDB的数据必须满足以下格式，不接受例外：**

| 字段 | 单位 | 类型 | 示例 | 说明 |
|------|------|------|------|------|
| open/high/low/close | 元 | float | 11.37 | **真实价(不复权)** |
| pre_close | 元 | float | 11.36 | **真实价(不复权)** |
| pct_chg | % | float | -2.15 | 涨跌幅百分比 |
| vol | 股 | int | 93695800 | **不是手** |
| amount | 元 | float | 1062755238.5 | **不是千元/万元** |
| circ_mv | 万元 | float | 22064167.94 | 流通市值 |
| turnover_rate | % | float | 0.48 | 换手率 |
| volume_ratio | 倍 | float | 1.5 | 量比 |
| trade_date | — | int | 20260508 | yyyyMMdd格式 |

**🔴 绝对禁止: 前复权价、vol=手、amount=千元/万元**

### 数据写入前必须做的转换

每个数据源写入MongoDB前，必须做以下转换确保统一：

| 数据源 | 需要转换的字段 | 转换规则 |
|--------|--------------|----------|
| 东方财富API | circ_mv | 元→万元: ÷10000 |
| 东方财富API | vol | 手→股: ×100 |
| AKShare stock_zh_a_daily | turnover | 小数→百分比: ×100 |
| AKShare stock_zh_a_daily | pre_close | close-change (API不直接返回) |
| AKShare stock_zh_a_spot_em | vol | 手→股: ×100 |
| AKShare stock_zh_a_spot_em | amount | 万元→元: ×10000 |
| 量脉 | circ_mv(lt) | 元→万元: ÷10000 |
| 量脉 | pe/sjl/pb/hs/lb | **直接使用,不需转换** (上次sniper脚本映射错误已清除) |
| Tushare | **不要使用** | token已失效 |

### 数据质量验证

**每次写入数据后，必须运行验证:**

```bash
python3 scripts/unify_data.py --validate
```

验证项:
1. 前复权数据检测(平安银行close>30=前复权，正常应<15)
2. vol单位检测(vol<1000可能是手而非股)
3. amount单位检测(amount<100000可能是千元而非元)
4. 每日股票数量(<4000=偏少)

### 当前数据质量问题（截至2026-05-08）

| 问题 | 范围 | 严重度 | 修复方案 |
|------|------|--------|----------|
| **前复权close** | 114天(20251008~20260320) | 🔴致命 | 用AKShare重新拉真实价覆盖 |
| **amount=千元** | 同上114天，全部5510只 | 🔴致命 | 同上 |
| **vol=手** | 同上114天 | 🔴致命 | 同上 |
| **4月底每天只有2400只** | AKShare段(3/23~5/6) | 🟡 | AKShare补全SZ/BJ |
| **5/7前circ_mv缺失** | AKShare段 | 🟡 | 东方财富/daily_basic合并 |
| **circ_mv 9只大盘股存元** | 全部日期 | 🟡 | 特殊处理9只股票 |
| **5/8=5/7盘中快照** | 东方财富段当天盘中运行 | 🟡 | 收盘后再拉 |

**⚠️ 在修复前复权数据之前，回测结果不可信！**

修复命令:
```bash
# 修复前复权数据(约17分钟, 逐只从AKShare拉)
python3 scripts/unify_data.py --fix-qfq --start 20251008 --end 20260320

# 先干跑看效果
python3 scripts/unify_data.py --fix-qfq --dry-run
```

---

## 一、数据集合总览

| 集合 | 用途 | 当前数据量 | 最新日期 |
|------|------|-----------|---------|
| stock_daily_ak_full | 回测日线(OHLCV+因子) | 710K条/145天/8649只 | 20260508 |
| daily_basic | PE/PB/流通市值/换手率/量比 | 40K条/85天 | 20260508 |
| index_daily | 指数日K | 464条/4只 | 20260331 |
| stock_basic | 股票基本信息(代码/名称/行业) | 5511只 | — |
| limit_pool_up | 涨停池 | 101条/1天 | 20260506 |
| limit_pool_down | 跌停池 | 2条/1天 | 20260506 |

---

## 二、stock_daily_ak_full 日线数据

### 2.1 数据来源与格式分段（⚠️ 最重要的坑）

**该集合有3个数据段，格式/单位完全不同：**

| 时段 | 来源 | 每日只数 | amount单位 | vol单位 | close类型 | circ_mv | 特点 |
|------|------|---------|-----------|--------|----------|---------|------|
| 20251008~20260320 | Tushare(通达信) | ~5510 | 千元 | 手(×100=股) | **前复权价** | 万元(但9只大盘股存元) | 数据最全 |
| 20260323~20260506 | AKShare `stock_zh_a_daily` | ~2440 | **元** | **股** | **真实价(不复权)** | None(缺失) | 缺SZ/BJ |
| 20260507~ | 东方财富API | ~5849 | **元** | **股** | **真实价(不复权)** | 万元(东方财富) | 最快最全 |

**⚠️ 关键注意：**
- **amount不能直接跨段比较**：3/20前的千元 vs 3/23后的元，差1000倍
- **vol不能直接跨段比较**：3/20前的手 vs 3/23后的股，差100倍
- **close不能直接跨段比较**：3/20前的前复权 vs 3/23后的真实价，差异巨大(茅台66 vs 1408)
- **circ_mv单位混乱**：旧数据9只大盘蓝筹(600036/600519/600900/601318/601899/000001/000002/000858/300750)存的是元而非万元
- **turnover_rate**：旧数据=amount反算(不精确)，新数据=东方财富直取

### 2.2 如何补充最新日线

**方法1: 东方财富API (推荐，3秒/次，无限流)**

```bash
python3 scripts/eastmoney_daily_bar.py --date 20260508
```

- 脚本: `scripts/eastmoney_daily_bar.py`
- 速度: 2.8秒拉5849只，0.4秒写入MongoDB
- 字段: open/high/low/close/pre_close/pct_chg/vol(股)/amount(元)/turnover_rate/volume_ratio/circ_mv(万元)
- 涨跌停: 自动判断(主板10%/创业板20%/北交所30%)
- **数据转换(脚本内已处理):**
  - f5(vol)手→股: ×100
  - f21(流通市值)元→万元: ÷10000
  - f10(量比)直接使用
- **注意**: 拉的是盘中实时快照，盘中运行时数据会变化，**收盘后拉才是最终数据**
- **注意**: 5/8和5/7数据相同，说明是盘中快照未更新，**需在收盘后重新拉**

**方法2: AKShare (备选，逐只拉，慢)**

```python
import akshare as ak
# 历史日线(逐只，0.2s/只，5000只≈17分钟)
df = ak.stock_zh_a_daily(symbol='sz000001', start_date='20260507', end_date='20260507', adjust='')
# 字段: date/open/high/low/close/volume(股)/amount(元)/outstanding_share/turnover
# **数据转换(需手动处理):**
#   - turnover: 小数→百分比, ×100
#   - pre_close: close - change (API不返回pre_close)
#   - 北交所(8/4开头)会报KeyError('date')，需过滤
#   - 不含PE/PB/流通市值/量比
```

### 2.3 补因子数据

新写入的日线数据缺少技术因子(MA/RSI/MACD等)，需在回测前补算：

```bash
# 方式1: factor_auto_compute (回测启动时自动检测补算，推荐)
# 回测引擎会自动调用，无需手动操作

# 方式2: 手动补算
python3 scripts/compute_all_factors.py
```

---

## 三、daily_basic PE/PB/流通市值数据

### 3.1 数据来源

**方法1: 东方财富API (推荐，2.4秒/次，无限流)**

```bash
python3 scripts/eastmoney_daily_basic.py --date 20260508
```

- 脚本: `scripts/eastmoney_daily_basic.py`
- 速度: 2.4秒拉5849只，0.4秒写入MongoDB
- 字段: pe(PE_TTM)/pb/circ_mv(亿元)/total_mv(亿元)/turnover_rate(%)/volume_ratio/close
- 覆盖率: PE 75.7%, PB 93.6%, circ_mv 94.3%, volume_ratio 93.9%
- **数据转换(脚本内已处理):**
  - f21(流通市值)元→亿元: ÷1e8
  - f20(总市值)元→亿元: ÷1e8
  - f115(PE_TTM)优先于f9(PE动态)
- **注意**: daily_basic的circ_mv存的是**亿元**（与stock_daily_ak_full的**万元**不同！）
- **注意**: 已有>100条时自动删除旧数据重写（确保数据是最新的）
- **注意**: 写入后运行 `python3 scripts/unify_data.py --validate` 验证

**方法2: 量脉 (不推荐，4291限制)**

```bash
python3 scripts/liangmai_sniper.py --task multi
```

- 4291 IP限制: Token绑2个IP，服务器动态IP导致几乎无法使用
- 速度: 约30秒抢到1次槽位，每次20只，2435只需~1小时
- ⚠️ 字段映射容易出错: 量脉PE/PB是原始整数(需除以100?), 上次写入错误数据已清除

### 3.2 daily_basic → stock_daily_ak_full 合并

回测引擎(factor_engine)在回测模式下会自动从daily_basic合并PE/PB/circ_mv到stock_daily_ak_full:
- 合并条件: stock_daily_ak_full的字段为None/0时，用daily_basic的同日同股数据覆盖
- 优先级: daily_basic精确值 > stock_daily_ak_full近似值
- circ_mv单位转换: daily_basic(亿元) × 10000 → stock_daily_ak_full(万元)

### 3.3 daily_basic历史分段

| 时段 | 来源 | 每日只数 | 质量 |
|------|------|---------|------|
| ~20260430 | 量脉market_realtime_all_network | ~10-977 | ⚠️ 仅SH 300只, PE/PB可能不准 |
| 20260506 | 量脉sniper(stock_realtime_multi) | 8161 | ❌ 字段映射错误(已删除) |
| 20260508 | 东方财富API | 5849 | ✅ 正确 |

**⚠️ 5/7之前的daily_basic数据质量不可靠（量脉仅300只SH）**

---

## 四、index_daily 指数数据

### 4.1 当前状态
- 仅4个指数: 000001.SH/399001.SZ/399006.SZ/000016.SH (不确定)
- 最新到20260331，缺5周数据

### 4.2 补数据方法

**方法1: 东方财富API (待实现，推荐)**

```python
# 东方财富指数K线接口
url = 'https://push2.eastmoney.com/api/qt/stock/kline/get'
params = {
    'secid': '1.000001',  # 1=SH, 0=SZ
    'fields1': 'f1,f2,f3,f4,f5,f6',
    'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
    'klt': '101',  # 日K
    'fqt': '0',    # 不复权
    'beg': '0',    # 从最早开始
    'end': '20500101',
    'lmt': '1000000',
}
```

**方法2: 量脉 (不推荐)**

```bash
python3 scripts/liangmai_sniper.py --task index
```

**方法3: AKShare**

```python
import akshare as ak
df = ak.index_zh_a_hist(symbol='000001', period='daily', start_date='20260401', end_date='20260508')
```

---

## 五、stock_basic 股票基础信息

### 5.1 当前状态
- 5511只，含ts_code/name/industry/list_status等

### 5.2 更新方法

```python
import akshare as ak
df = ak.stock_zh_a_spot_em()  # 含代码和名称
# 或
df = ak.stock_info_a_code_name()  # 新浪源，需注意代码前缀(sh/sz)转换
```

**⚠️ 代码后缀转换规则:**
- 6/9开头 → .SH (上海)
- 0/3开头 → .SZ (深圳)
- 8/4开头 → .BJ (北交所)
- **5开头是基金不是股票**，不要误转为.SH

---

## 六、涨停池/跌停池/开板池

### 6.1 当前状态
- 极少数据：涨停池仅5/6一天101只，跌停池2只，开板池0只

### 6.2 补数据方法

**方法1: 东方财富API (推荐)**

```python
# 东方财富涨停池
url = 'https://push2.eastmoney.com/api/qt/clist/get'
params = {
    'pn': 1, 'pz': 500, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
    'fid': 'f3', 'fs': 'b:BK0815',  # 涨停板块
    'fields': 'f2,f3,f12,f14'
}
# ⚠️ 需要验证是否真的能拉到涨停池
```

**方法2: 量脉 (4291限制)**

```python
import requests
r = requests.get('http://124.220.44.71/api/gateway', 
    params={'token': TOKEN, 'api': 'pool_limit_up', 'date': '2026-05-07'})
# 参数: date格式=yyyy-MM-dd (不是yyyyMMdd!)
# 返回: 封板时间/炸板次数/连板数/行业等
```

**方法3: AKShare**

```python
import akshare as ak
df = ak.stock_zt_pool_em(date='20260507')  # 涨停池
df = ak.stock_zt_pool_dtgc_em(date='20260507')  # 跌停池
```

---

## 七、量脉API (仅用于实时盘中/分钟K线)

### 7.1 使用规则

- **日常数据获取不要用量脉**，用东方财富API替代
- **仅当需要以下数据时才用量脉**: 实时盘中行情、1分钟K线、盘中因子(opening_pct_chg/limit_up_time等)
- **4291不可避免**: 服务器公网IP是动态的(118.196.127.x)，每次可能变，Token限2个IP白名单

### 7.2 API调用格式

```python
import requests
GATEWAY = 'http://124.220.44.71/api/gateway'
TOKEN = 'ebacbad6d64444cd037ac5504b63f25d'

# 通用调用
r = requests.get(GATEWAY, params={'token': TOKEN, 'api': '接口名', ...参数}, timeout=30)
d = r.json()
# code=0成功, code=4291=IP超限, code=5429=频率限制

# 重要参数格式:
# - 日期参数: date='2026-05-07' (yyyy-MM-dd, 不是20260507!)
# - 股票代码: ts_code='600519' (6位纯数字, 不带后缀!)
# - 批量代码: stock_codes='000001,000002,600519' (逗号分隔, 不是ts_code!)
# - K线参数: klt='101'(日K)/'1'(1分钟), fqt='n'(不复权), lt='5'(条数)
```

### 7.3 常用接口

| API名 | 用途 | 参数 | 限流 |
|-------|------|------|------|
| stock_realtime | 单只实时行情(含PE/PB) | ts_code | 120/min |
| stock_realtime_multi | 批量实时行情(≤20只) | stock_codes | 120/min |
| market_realtime_all_network | 全市场行情 | 无 | 1/min, **仅300只SH** |
| pool_limit_up | 涨停池 | date | 120/min |
| pool_limit_down | 跌停池 | date | 120/min |
| quote_bars_history | 历史K线 | ts_code, klt, fqt, lt | 120/min |
| index_kline | 指数K线 | ts_code, klt | 120/min |

### 7.4 量脉字段映射

```
量脉 → 含义
dm   → 股票代码(6位)
p    → 最新价
yc   → 昨收价
o    → 开盘价
h    → 最高价
l    → 最低价
pe   → 动态PE
sjl  → 市净率PB
lt   → 流通市值(元)
sz   → 总市值(元)
hs   → 换手率(%)
lb   → 量比
vol  → 成交量
amt  → 成交额
fbt  → 首次封板时间
zbc  → 炸板次数
Lbc  → 连板数
```

### 7.5 量脉4291处理策略

```python
# 不要反复重试4291
# 策略: 4291时等25-30秒再试一次, 失败就报告放弃
import time
for attempt in range(3):
    r = requests.get(GATEWAY, params={...}, timeout=30)
    d = r.json()
    if d.get('code') == 0:
        return d['data']
    elif d.get('code') == 4291:
        time.sleep(25 + attempt * 5)
    else:
        break
return None  # 放弃
```

---

## 八、每日数据更新流程

### 8.1 交易日收盘后执行(推荐5分钟搞定)

```bash
cd /root/.openclaw/workspace/StockAgent/AgentServer

# 1. 补日线数据 (3秒)
python3 scripts/eastmoney_daily_bar.py --date $(date +%Y%m%d)

# 2. 补daily_basic PE/PB (3秒)
python3 scripts/eastmoney_daily_basic.py --date $(date +%Y%m%d)

# 3. 补指数数据 (需要实现, AKShare约10秒)
# python3 scripts/补指数.py

# 4. 涨停池 (AKShare, 约5秒)
# python3 -c "import akshare as ak; ak.stock_zt_pool_em(date='$(date +%Y%m%d)')"
```

### 8.2 历史数据补全

```bash
# 补某一天的日线
python3 scripts/eastmoney_daily_bar.py --date 20260507

# 补某一天的PE/PB
python3 scripts/eastmoney_daily_basic.py --date 20260507

# ⚠️ 东方财富API只提供当日快照，不能拉历史日期的快照
# 历史数据补全需用AKShare stock_zh_a_daily (逐只，0.2s/只)
```

---

## 九、已知数据质量问题

### 9.1 stock_daily_ak_full

1. **三段数据格式不一致**: 见2.1节，这是最大的坑
2. **circ_mv 9只大盘股单位错误**: 600036/600519/600900/601318/601899/000001/000002/000858/300750 存的是元而非万元
3. **4月底每天只有2400只**: AKShare采集器只拉了部分股票(原因待查)
4. **5/7前的因子缺失**: 新写入的日线数据(AKShare/东方财富)缺少MA/RSI/MACD等技术因子，需factor_auto_compute补算

### 9.2 daily_basic

1. **5/7前数据不可靠**: 量脉只覆盖300只SH，SZ/BJ缺失
2. **5/6有错误数据**: 量脉sniper写入的PE/PB字段映射错误(如PE=380应为5.12)，已删除
3. **circ_mv单位不一致**: daily_basic存亿元，stock_daily_ak_full存万元，合并时需×10000

### 9.3 跨集合单位速查

| 字段 | stock_daily_ak_full | daily_basic | 东方财富API原始值 |
|------|---------------------|-------------|------------------|
| amount | 旧:千元, 新:元 | — | 元 |
| vol | 旧:手, 新:股 | — | 手(需×100) |
| close | 旧:前复权, 新:真实价 | 元 | 元 |
| circ_mv | 万元 | **亿元** | 元(需÷1e8→亿元, ×10000→万元) |
| turnover_rate | % | % | % |
| pe | — | 倍 | 倍 |
| pb | — | 倍 | 倍 |

---

## 十、脚本清单

| 脚本 | 用途 | 速度 | 推荐度 |
|------|------|------|--------|
| `scripts/eastmoney_daily_bar.py` | 全市场日线→stock_daily_ak_full | 3秒/5849只 | ⭐⭐⭐ |
| `scripts/eastmoney_daily_basic.py` | 全市场PE/PB→daily_basic | 2.4秒/5849只 | ⭐⭐⭐ |
| `scripts/liangmai_sniper.py` | 量脉4291间歇窗口拉数据 | ~30秒/20只 | ⭐ (仅分钟线) |
| `scripts/liangmai_batch_fetch.py` | 量脉aiohttp批量拉 | ~30秒/20只 | ⭐ |
| `scripts/compute_all_factors.py` | 补算技术因子 | ~5分钟 | ⭐⭐ |
| `scripts/run_backtest_quick.py` | 快速回测 | ~5分钟 | ⭐⭐ |
