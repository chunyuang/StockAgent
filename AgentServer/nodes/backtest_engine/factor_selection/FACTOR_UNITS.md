# 因子单位参考文档

> 本文档记录所有回测因子在 MongoDB `stock_daily_ak_full` 集合中的存储单位。
> 修改策略筛选条件时**必须**参考此文档，确保 `target` 值与存储单位一致。

## 因子单位表

| 因子名 | 存储单位 | 示例值 | 说明 |
|--------|----------|--------|------|
| `pct_chg` | % | 2.5 | 当日涨跌幅，2.5=2.5% |
| `opening_pct_chg` | % | 2.5 | 竞价开盘涨幅，2.5=2.5% |
| `turnover_rate` | % | 3.0 | 换手率，3.0=3% |
| `volume_ratio` | 倍 | 1.5 | 量比，1.5=1.5倍 |
| `circ_mv` | 万元 | 5000000 | 流通市值，50亿=5000000万 |
| `amount` | 千元 | 50000 | 成交额，5000万=50000千 |
| `limit_up_open_amount` | 千元 | 50000 | 涨停开板/封单金额 |
| `limit_down_open_amount` | 千元 | 100000 | 翘板金额 |
| `rise_after_limit_down` | % | 3.0 | 翘板后涨幅，3.0=3% |
| `pullback_pct` | 小数(负) | -0.15 | 回调幅度，-0.15=回调15% |
| `pullback_days` | 天 | 3 | 整数 |
| `limit_up_time` | 分钟 | 600 | 9:30=570, 10:00=600 |
| `limit_up_open_duration` | 分钟 | 5 | 开板时长 |
| `limit_up_count` | 天 | 2 | 连续涨停天数 |
| `limit_down_count` | 天 | 2 | 连续跌停天数 |
| `sentiment_score` | 0~100 | 50 | 整数分数 |
| `first_limit_up` | 0/1 | 1 | 布尔 |
| `limit_up_yesterday` | 0/1 | 0 | 布尔 |
| `limit_down_yesterday` | 0/1 | 1 | 布尔 |
| `hot_sector` | 0/1 | 0 | 布尔 |
| `open_below_limit` | 0/1 | 1 | 布尔 |
| `open_above_limit_down` | 0/1 | 1 | 布尔 |
| `pullback_ma5` | 0/1 | 1 | 布尔 |
| `limit_up_open_count` | 次 | 1 | 开板次数 |
| `amplitude` | % | 5.0 | 振幅 |
| `vol` | 手 | 10000 | 成交量 |
| `open/high/low/close` | 元 | 15.50 | 价格 |

## 单位转换规则

### 前端 → 后端转换

| 前端参数 | 前端单位 | 后端因子 | 转换公式 |
|----------|----------|----------|----------|
| `min_circulation_market_cap` | 亿 | `circ_mv` | `target = value × 10000` (亿→万元) |
| `max_circulation_market_cap` | 亿 | `circ_mv` | `target = value × 10000` |
| `min_seal_amount` | 万元 | `limit_up_open_amount` | `target = value × 10` (万→千元) |
| `min_qiao_amount` | 万元 | `limit_down_open_amount` | `target = value × 10` (万→千元) |
| `min_rise_after_qiao` | 小数 | `rise_after_limit_down` | `target = value × 100` (小数→%) |
| `min_correction_pct` | 小数 | `pullback_pct` | `target = -value` (取负，符号反转) |
| `max_correction_pct` | 小数 | `pullback_pct` | `target = -value` (取负，符号反转) |
| `min_turnover_rate` | 小数或% | `turnover_rate` | `if <1: value×100` (小数→%) |
| `max_limit_up_time` | HH:MM | `limit_up_time` | `int(H)×60+int(M)` (时间→分钟) |

### 历史Bug记录

| Bug | 因子 | 错误条件 | 正确条件 | 修复轮次 |
|-----|------|----------|----------|----------|
| 龙头低吸永远0候选 | `pullback_pct` | `>=0.15` | `<=-0.15` | 第15轮 |
| 翘板涨幅筛选无效 | `rise_after_limit_down` | `>=0.03` | `>=3.0` | 第15轮 |
| 龙头低吸流通市值无效 | `circ_mv` | `>=100` | `>=1000000` | 第12轮 |
| 翘板金额单位错误 | `limit_down_open_amount` | `>=1000` | `>=10000` | 第4轮 |
| 换手率单位错误 | `turnover_rate` | `>=0.15` | `>=15` | 第4轮 |
