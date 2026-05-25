# V50 市场监听模块调优审查报告

## 审查范围

- `AgentServer/nodes/listener/` 全部文件 (3789行)
- `AgentServer/nodes/market_monitor/` 关键文件 (4287行)
- `AgentServer/nodes/scheduler/daily_scheduler.py` (止损止盈部分)

## 审查结论

### 发现问题 22个, 修复 17个

| 优先级 | 编号 | 问题 | 文件 | 状态 |
|--------|------|------|------|------|
| **P0** | P0-1 | daily_profit计算bug: `(total_asset-total_asset)/total_asset`永远为0 | position_manager.py | ✅修复 |
| **P0** | P0-2 | 佣金万2→万3: base_executor/simulator_executor/broker三处不一致 | 3文件 | ✅修复 |
| **P0** | P0-3 | 止损硬编码-5%: 不读strategy_defaults策略级参数 | simulator_executor.py | ✅修复 |
| **P0** | P0-4 | 卖出信号仅有止损: 缺冲高回落/利润保护/跳空止损/超时 | position_manager.py | ✅修复 |
| **P0** | P0-5 | 买入扣款重复: 佣金先扣+total_cost含佣金=双扣 | simulator_executor.py | ✅修复 |
| **P0** | P0-6 | 卖出盈利计算: 用pos.shares而非卖出shares | simulator_executor.py | ✅修复 |
| **P0** | P0-7 | 卖出检查缺open价: 用current_price近似无法判断冲高回落 | position_manager.py | ✅修复 |
| **P0** | P0-8 | 冲高回落用真实open价判断 | position_manager.py | ✅修复 |
| **P0** | P0-9 | 利润保护用真实open价判断 | position_manager.py | ✅修复 |
| **P0** | P0-10 | 首板打板高开即卖(与回测next_day_open_sell_pct对齐) | position_manager.py | ✅修复 |
| **P0** | P0-11 | 跳空止损用真实open价(不再用current_price近似) | position_manager.py | ✅修复 |
| **P1** | P1-1 | max_position_per_stock 0.2→0.35对齐回测V49 | scanner.py | ✅修复 |
| **P1** | P1-2 | 交易时间检查被注释掉→恢复 | node.py | ✅修复 |
| **P1** | P1-3 | emotion_cycle连板高度用估算→从MongoDB真实读取 | emotion_cycle.py | ✅修复 |
| **P1** | P1-4 | emotion_cycle ZT溢价用简单-1天→交易日历 | emotion_cycle.py | ✅修复 |
| **P1** | P1-5 | leading_dragon连板高度从limit_times读取 | leading_dragon.py | ✅修复 |
| **P1** | P1-6 | position_manager新增on_trading_day_start | position_manager.py | ✅修复 |
| **P1** | P1-7 | calculate_max_shares默认0.2→0.35 | simulator_executor.py | ✅修复 |
| **P1** | P1-8 | 佣金预估万2→万3 | simulator_executor.py | ✅修复 |
| **P1** | P1-9 | daily_scheduler止损止盈硬编码-3%/+7%→读strategy_defaults | daily_scheduler.py | ✅修复 |
| **P1** | P1-10 | daily_scheduler daily_return硬编码1000000→用daily_start_asset | daily_scheduler.py | ✅修复 |
| **P2** | P2-1 | emotion_cycle ZT溢价: 逐只查询MongoDB效率低→批量查询 | emotion_cycle.py | ⏳待优化 |
| **P2** | P2-2 | drawdown_controller monthly_reset无人调用→需scheduler集成 | drawdown_control.py | ⏳待集成 |
| **P2** | P2-3 | listener→scanner策略名称映射不一致 | 跨模块 | ⏳待统一 |
| **P2** | P2-4 | broker SLIPPAGE_RATE 0.1%可能偏低→实盘建议0.2% | broker.py | ⏳待确认 |
| **P2** | P2-5 | limit_open策略不支持跌停翘板(只检测开板) | limit_open.py | ⏳待扩展 |

## 改动文件清单

| 文件 | 改动 | Commit |
|------|------|--------|
| `listener/execution/position_manager.py` | daily_profit修复+open价获取+冲高回落/利润保护/跳空止损/首板高开即卖/on_trading_day_start | 1501089, c1cd6a8 |
| `listener/execution/base_executor.py` | 佣金万2→万3 | 1501089 |
| `listener/execution/simulator_executor.py` | 买入扣款修复+卖出盈利修复+止损从strategy_defaults+max_pct→0.35+佣金预估万3 | 1501089, 7aa030a |
| `listener/node.py` | 交易时间检查恢复 | 1501089 |
| `listener/strategies/emotion_cycle.py` | 连板高度真实读取+ZT溢价交易日历 | 1501089 |
| `listener/strategies/leading_dragon.py` | 连板高度从limit_times读取 | 1501089 |
| `market_monitor/broker.py` | 佣金万2→万3 | 1501089 |
| `market_monitor/scanner.py` | max_position_per_stock 0.2→0.35 | 1501089 |
| `scheduler/daily_scheduler.py` | 止损止盈从strategy_defaults+daily_return修复 | 7aa030a |

## 回测验证

V49基线 (改动前):
- 总收益: 360.85%, 最大回撤: 5.86%, 胜率: 77.45%, 夏普: 11.92

V50验证 (改动后):
- 总收益: 360.85%, 最大回撤: 5.86%, 胜率: 77.45%, 夏普: 11.92

**✅ 回测引擎完全未受影响, 所有修改限定在listener/market_monitor/scheduler模块内**

## 修复影响评估

### 高影响 (直接改善实盘/模拟交易收益)

1. **P0-1 daily_profit修复**: 回撤控制器之前永远认为0%盈亏,等于失效。修复后单日亏损超5%将禁止开仓
2. **P0-4 卖出信号对齐**: 之前只有止损(-5%硬编码),现在有冲高回落/利润保护/跳空止损/超时/首板高开即卖
3. **P0-5/P0-6 买入/卖出计算修复**: 之前佣金双扣+卖出盈利计算错误,账户余额可能不准确
4. **P0-2 佣金对齐**: 万2→万3, 实盘佣金更真实(万3是含规费的标准券商费率)

### 中影响 (提升策略准确性)

5. **P1-3/P1-5 连板高度真实读取**: 不再用涨停数//5+1估算,直接从limit_times字段读取
6. **P1-4 ZT溢价交易日历**: 不再简单-1天(周末/节假日会出错)
7. **P1-9 止损止盈策略级**: 龙头低吸tp=30%/跌停翘板sl=5%等,不再一刀切-3%/+7%

### 低影响 (参数对齐/体验改善)

8. **P1-1/P1-7 max_position 0.35**: 与回测V49对齐,提升资金利用率
9. **P1-2 交易时间检查恢复**: 深夜不再浪费API调用
10. **P1-10 daily_return修复**: 不再硬编码100万初始资金
