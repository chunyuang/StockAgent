# V30回测审查报告

## 基线结果 (V29, 2025-01-01~2025-06-01)
- 总收益率: 658.83% | 夏普: 7.80 | 回撤: 6.69% | 胜率: 76.53% | 盈亏比: 3.53 | 98笔

## V30结果 (2025-01-01~2025-06-01)
- 总收益率: 658.39% | 夏普: 7.80 | 回撤: 6.69% | 胜率: 76.53% | 盈亏比: 3.53 | 98笔
- **回测耗时: 25.0s vs V29基线~120s (加速4.8倍)**

## 完成的修复

### P1-1: 持仓天数O(1)优化 ✅
- 替换6处`sum(1 for d in _all_td if buy_dt < d <= trade_dt)` O(N)遍历
- 新增`_calc_trade_days_held`方法+`_trade_date_index_map`索引映射
- `idx_sell - idx_buy` O(1)计算,未命中时fallback到旧逻辑

### P1-3: 非调仓日情绪缓存 ✅
- 调仓日正常调用`_print_market_environment`(含涨跌停统计+日志)
- 非调仓日复用上次缓存的sentiment_level/score/limit_up/down
- 每个非调仓日省1次5万条聚合查询+5条日志输出

### P1-4: FactorEngine prev_date缓存 ✅ (最大性能提升)
- 替换2处`$match+$group`全表扫描(2000万行,每次1-2秒)
- `set_trade_dates()`预构建{trade_date: prev_trade_date}映射
- `get_prev_trade_date()`O(1)查找,缓存未命中时回退到$group聚合
- 第一天prev_date(不在all_trade_dates中)通过fallback获取

### P1-fix: 因子自动计算跳过 ✅
- `factor_auto_compute`在5个月区间下卡死
- 改为只输出告警,不在回测流程中触发自动计算
- 缺失因子在`factor_engine.compute_factors`运行时动态处理

### P3-1: 半路追涨优化尝试 → 回滚
- pct_chg_prev>0条件: 信号暴降33→13,胜率反降54.5%→46.2% → 回滚
- min_volume_ratio 2.0→2.5: 同样导致信号暴降 → 回滚到2.0
- 止损5%→4%: 微弱改善但不够显著 → 回滚到5%

### Sortino比率计算修正 ✅
- 下行标准差应相对于0(目标收益率)计算,而非下行收益的均值
- `downside_variance = sum(r^2) / N_total`替代`sum((r-avg)^2) / N_downside`

## 未修复(优先级低)

### P2-1: _rebalance方法512行过长
- 需进一步提取子方法,但风险较高,留给V31

### P2-2: run_state dict解包冗余
- 每个方法15+行解包+15+行回写,改用SimpleNamespace需大改动

### P2-3: _build_strategy_filter_conditions硬编码
- 5策略200行参数读取,新增策略需复制40行
- 建议定义STRATEGY_FILTER_TEMPLATES数据结构

## Git提交
- `e066659` feat: V30 - 持仓天数O(1)优化+非调仓日情绪缓存+因子自动计算跳过
- `a34f628` feat: V30续 - FactorEngine prev_date缓存优化,回测加速4.8倍
- `5318984` fix: V30 - 索提诺比率计算修正
