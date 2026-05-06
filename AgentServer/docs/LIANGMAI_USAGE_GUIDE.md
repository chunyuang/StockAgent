# 量脉(LiangMai)数据源使用指南

> 最后更新: 2026-05-06 | 基于实际踩坑经验整理

## 1. 基本配置

| 项目 | 值 |
|------|------|
| 网关地址 | `http://124.220.44.71/api/gateway` |
| Token | `ebacbad6d64444cd037ac5504b63f25d` |
| 请求方式 | GET, 参数: `token=xxx&api=接口名&其他参数` |
| 返回格式 | JSON `{"code":0, "data":[...]}` |

## 2. 限流规则（实测）

### 2.1 官方文档声称
- 120次/分钟
- Token绑定2个IP

### 2.2 实际情况（踩坑结论）
- **4291是IP槽位竞争，不是冷却期**：Token的2个IP槽位被其他IP占用，当前服务器IP(118.196.127.163)不在白名单
- **间歇性成功**：约每20-30秒能临时抢到1个槽位，但随即被其他IP抢占回去
- **一旦4291，不能连续重试**：连续请求会延长封锁时间
- **429有两种**：
  - HTTP 429 (nginx层)：返回HTML或JSON，aiohttp按JSON解析必报错
  - JSON code=4291 (业务层)：返回正常JSON，`{"code":4291,"msg":"已超过该 Token 允许的 IP 数量（上限 2）"}`

### 2.3 特殊接口限流
| 接口 | 限制 |
|------|------|
| `market_realtime_all_broker` | 1次/分钟 |
| `market_realtime_all_network` | 1次/分钟 |
| 其余普通接口 | 120次/分钟(文档值) |

### 2.4 安全请求间隔（IP绑定修复后）
- 普通接口: ≥0.6秒 (120/min = 0.5s + 0.1s余量)
- 特殊接口: ≥65秒 (1次/分 + 5s余量)
- 缓存TTL: 60秒(相同请求不重计)

## 3. 核心踩坑记录

### 坑1: HTTP 429 vs JSON 4291
**问题**: LiangMaiClient只处理JSON code=4291，没处理HTTP 429。429→JSON解析失败→异常→重试循环(30s+60s)→IP被长期封禁  
**修复**: commit 28f5e57
- HTTP 429在JSON解析前检测
- 429后重建session(force_close连接池)
- 重试等待5s递增(非30s)

### 坑2: aiohttp连接池污染
**问题**: 429标记的连接被连接池复用，导致后续正常请求也失败  
**修复**: TCPConnector(force_close=True)，429后重建整个session

### 坑3: IP绑定问题
**问题**: Token绑定2个IP，当前服务器IP(118.196.127.163)不在白名单  
**表现**: 间歇性成功(约20-30秒能抢到1次)，大部分时间4291  
**解决**: 在量脉平台更新IP白名单为 `118.196.127.163`（替换旧IP `118.196.127.165`）

### 坑4: 涨停池日期格式
**问题**: 日期参数需用 `yyyy-MM-dd` 格式(如 `2026-03-20`)，不是 `yyyyMMdd`  
**正确**: `trade_date=2026-03-20`  
**错误**: `trade_date=20260320`

### 坑5: 全市场行情只返回300只
**问题**: `market_realtime_all_network` 文档说"全市场"，实测只返回300只  
**可能原因**: network源本身只覆盖活跃股票，或有未文档化分页参数  
**替代方案**: 用 `stock_realtime_multi` 分批获取(每批≤20只)，120次/分≈2400只/分

## 4. 可行性方案

### 方案A: IP绑定修复后（推荐）

**日常使用（历史数据回测）**:
- 不需要量脉！直接读MongoDB本地数据(无限流)
- 历史数据已通过AKShare下载到stock_daily_ak_full

**实时数据获取**:
- 涨停池/跌停池: 1次/天，trade_date=yyyy-MM-dd
- 全市场PE/PB: market_realtime_all_network(300只/次, 1次/分) + stock_realtime_multi分批补全
- 单只行情: stock_realtime, 120次/分

**补充daily_basic方案**:
```
1. market_realtime_all_network: 300只/次, 1次/分 → 17次≈17分钟覆盖约5000只
   (需确认分页或broker源是否更全)
2. stock_realtime_multi: 20只/次, 120次/分 → 260次≈2.2分钟覆盖5200只
   (但单次只返回行情不含PE/PB)
3. stock_realtime(单只): 含PE/PB, 120次/分 → 5200/120≈43分钟
   (最慢但最可靠)
```

### 方案B: 当前IP未绑定时（临时方案）

**可行操作**（利用间歇性窗口）:
- 每20-30秒可成功1次请求
- 适合低频操作: 每天获取1次涨停池/全市场行情
- **绝不连续请求**: 2次连续请求可能触发10分钟+封锁

**不可行操作**:
- 连续快速请求(>1次/5秒)
- 需要大量请求的场景(如逐只获取PE/PB)

### 方案C: 完全不用量脉（兜底）

**历史数据**: MongoDB本地读(628K+条)  
**实时数据**: AKShare stock_zh_a_daily(通达信源, 0.4s/只, 单线程)  
**PE/PB**: AKShare stock_zh_a_spot_em(东财源, 当前IP被封)  
**涨停池**: AKShare stock_zt_pool_em(东财源, 当前IP被封)

## 5. 代码使用示例

### Python异步客户端
```python
from core.data_fetchers.liangmai_client import LiangMaiClient

async def example():
    client = LiangMaiClient(token='ebacbad6d64444cd037ac5504b63f25d')
    await client.initialize()
    
    # 涨停池
    limit_up = await client.get_pool_limit_up(trade_date='2026-05-06')
    
    # 单只实时行情
    realtime = await client.get_realtime(ts_code='000001.SZ')
    
    # 多只行情(≤20)
    multi = await client.get_realtime_multi(codes=['000001', '600000'])
    
    await client.close()
```

### 直接HTTP请求
```python
import urllib.request, json

url = 'http://124.220.44.71/api/gateway'
params = {'token': 'ebacbad6d64444cd037ac5504b63f25d', 'api': 'hs_list_main'}
url_with_params = f"{url}?{'&'.join(f'{k}={v}' for k,v in params.items())}"

with urllib.request.urlopen(url_with_params, timeout=15) as resp:
    data = json.loads(resp.read())
```

## 6. 全市场行情字段解析 (market_realtime_all_network)

| 字段 | 含义 | 示例值 | 用途 |
|------|------|--------|------|
| dm | 股票代码 | 688553 | 匹配 |
| p | 现价 | 20.34 | 行情 |
| pe | **市盈率** | 98.5 | ✅补daily_basic |
| sjl | **市净率(PB)** | 2.28 | ✅补daily_basic |
| lt | **流通市值(元)** | 69.9亿 | ✅补daily_basic |
| sz | **总市值(元)** | 86.2亿 | ✅补daily_basic |
| hs | **换手率(%)** | 2.7 | ✅补daily_basic |
| lb | 量比 | 0.9 | 回测筛选 |
| zf | 涨幅(%) | 4.85 | 回测筛选 |
| h/l/o/yc | 最高/最低/开盘/昨收 | - | 行情 |
| cje | 成交额 | 188198782 | 因子 |
| zdf60 | 60日涨跌幅(%) | 3.3 | 因子 |
| zdfnc | 年内涨跌幅(%) | 14.33 | 因子 |

## 7. 待确认事项

- [ ] IP白名单更新为118.196.127.163
- [ ] market_realtime_all_network是否有分页参数(当前只返回300只)
- [ ] market_realtime_all_broker是否覆盖全市场(待IP修复后测试)
- [ ] 安全请求间隔确认(120/min是否实际可达)
- [ ] 缓存机制确认(相同请求60秒内是否不计次数)
