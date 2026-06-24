# 连板/市场高度数据影响复查报告（2026-06-24）

## 背景

用户发现 2026-06-18 盘前综合研判输出：

> 最高仅1连板，市场高度不够，追高需谨慎

复查发现该结论不正确。`limit_list` 当日涨停数据缺少 `limit_times` 字段，旧逻辑使用 `doc.get("limit_times", 1)`，导致所有涨停默认按 1 板统计。

## 2026-06-18 核验结果

本地 `limit_list`：

- 涨停：98 只
- 跌停：18 只
- `limit_times` 覆盖：0 只

按连续交易日涨停记录反推：

| 连板高度 | 数量 |
|---|---:|
| 1板 | 79 |
| 2板 | 12 |
| 3板 | 5 |
| 4板 | 2 |

真实最高连板高度为 **4 板**，不是 1 板。

## 影响范围结论

### 直接受影响

1. 盘前综合研判
   - `limit_pools.continue_stats`
   - “最高仅X连板/市场高度”文案
   - 盘前建议中的市场高度加减分

2. 情绪周期/盘中情绪
   - `max_continue_limit`
   - 情绪评分中“最高连板”维度
   - 仓位系数可能被间接影响

3. 日度统计 `daily_stats`
   - `max_limit_height`
   - `limit_1/2/3/4/5/6_plus`
   - `cont_board_count`
   - 后续市场分析/看板读取这些字段时会受影响

4. 板块主题强度
   - 高板数量统计
   - `max_board`
   - 主题/板块强度评分

5. 涨停池回退接口
   - 非交易时段或 scanner 无实时池时，MongoDB 回退返回的 `limit_times`

### 间接受影响

- 龙头低吸/龙头相关策略的环境判断、展示解释和部分候选排序可能受影响。
- 如果策略条件直接读取 `limit_list.limit_times`，会受影响。

### 基本不受本次 bug 直接影响

1. 回测主因子 `stock_daily_ak_full.limit_up_count`
   - 06/18 抽样显示该字段存在，最高为 4。
   - 龙头低吸回测使用的是 `limit_up_count`（近5日涨停次数/连板相关因子），不是 `limit_list.limit_times`。

2. 半路追涨
   - 主要依赖涨幅、量比、换手、突破等。

3. 跌停翘板
   - 主要依赖跌停/开板/反弹/量能。

4. 普通强制空仓风控中的涨停/跌停数量
   - 关注的是涨停家数和跌停家数，不依赖连板高度。

## 已修复内容

### 提交 df83dbca

`Fix: 缺失连板字段时反推市场高度`

- `scanner_system.py`
- `scanner_debug.py`
- `scanner_scan.py`

修复盘前综合研判、debug/premarket-status/premarket-scan 的 `continue_stats`。

### 提交 c5f17929

`Fix: 连板高度反推覆盖情绪与主题统计`

- `emotion_cycle.py`
- `intraday_sentiment.py`
- `daily_stats.py`（tasks + collectors）
- `theme_manager.py`

修复情绪周期、盘中情绪、日度统计、主题强度中的连板高度口径。

### 提交 2868365f

`Fix: 涨停池回退接口与情绪落库补齐连板反推`

- `scanner_core.py`
- `emotion_cycle.py`

修复涨停池 MongoDB 回退接口与 sentiment_scores 落库统计中的连板高度。

## 验证

已执行：

```bash
python3 -m py_compile \
  nodes/web/api/scanner_system.py \
  nodes/web/api/scanner_debug.py \
  nodes/web/api/scanner_scan.py \
  nodes/web/api/scanner_core.py \
  nodes/data_sync/tasks/daily_stats.py \
  nodes/data_sync/collectors/daily_stats.py \
  nodes/market_monitor/emotion_cycle.py \
  nodes/market_monitor/intraday_sentiment.py \
  core/managers/theme_manager.py
```

结果：通过。

已用 MongoDB 数据核验 20260618 反推结果：

```text
{1: 79, 2: 12, 3: 5, 4: 2}
max_height = 4
```

## 注意事项

- 当前处于盘中，未重启后端/实盘服务。
- 代码已提交，需在服务重载后生效。
- `frontend/playwright-report/index.html` 为无关报告文件改动，未纳入本次提交。
