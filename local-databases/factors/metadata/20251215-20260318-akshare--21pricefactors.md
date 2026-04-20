# 因子计算: 20251215-20260318-akshare--21pricefactors

## 基本信息

| 项目 | 信息 |
|------|------|
| **名称** | 20251215-20260318-akshare--21pricefactors |
| **版本** | v1 |
| **依赖原始数据** | raw/20251215-20260318-akshare |
| **因子数量** | 21 |
| **总因子记录数** | 23,070 |
| **包含因子列表** | 见下文 |
| **计算时间** | 2026-03-21 |
| **更新时间** | 2026-03-22 |
| **备注** | 21 个价量因子，不含财务因子 |

## 因子列表

### 技术因子 (10)
- `ma` - 移动平均
- `ema` - 指数移动平均
- `rsi` - 相对强弱指数
- `macd` - MACD
- `boll` - 布林带
- `atr` - 平均真实波动
- `amplitude` - 振幅
- `return_n` - 5日收益
- `high_n` - 5日最高
- `low_n` - 5日最低

### 规模因子 (3)
- `total_market_cap` - 总市值
- `circulating_cap` - 流通市值
- `log_market_cap` - 对数市值

### 流动性因子 (3)
- `avg_turnover` - 平均换手率
- `avg_amount` - 平均成交额
- `amihud_illiq` - Amihud 非流动性

### 动量因子 (3)
- `return_1m` - 一个月收益
- `one_month_reversal` - 一个月反转
- `relative_strength` - 相对强度

### 市场因子 (2)
- `market_emotion` - 市场情绪 (缺失)
- `index_return` - 指数收益 (缺失)

## MongoDB 集合统计

| 集合名称 | 预期文档数 |
|----------|-----------:|
| `strategy_signals` | 23,070 |

