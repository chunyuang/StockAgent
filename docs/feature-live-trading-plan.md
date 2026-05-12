# feature/live-trading — 实盘交易 & 市场监听

## 当前状态 (2026-05-12)

### 已有代码
| 模块 | 文件 | 行数 | 状态 |
|------|------|------|------|
| **每日调度器** | `real_trading/daily_scheduler.py` | 947 | ⚠️ 独立脚本，与 `nodes/scheduler/` 重复 |
| **调度器(Web)** | `AgentServer/nodes/scheduler/daily_scheduler.py` | 600+ | ✅ 已整合进Web API |
| **调度器API** | `AgentServer/nodes/web/api/scheduler.py` | 443 | ✅ REST接口 |
| **模拟盘引擎** | `AgentServer/core/managers/sim_trading_engine.py` | 506 | ✅ 已整合 |
| **模拟盘交易** | `real_trading/paper_trading.py` | 526 | ⚠️ 与SimTradingEngine功能重叠 |
| **交易网关** | `real_trading/trade_gateway.py` | 508 | ⚠️ 框架设计，未对接实盘券商 |
| **实时监控** | `real_trading/realtime_monitor.py` | 340 | ⚠️ 用AKShare轮询，非WebSocket |
| **持仓管理** | `real_trading/position_manager.py` | 572 | ⚠️ 独立，未与SimTradingEngine统一 |
| **风控检查** | `real_trading/pre_buy_risk_check.py` | 596 | ⚠️ 独立 |
| **风险告警** | `real_trading/risk_alert.py` | 245 | ⚠️ 独立 |
| **信号推送** | `real_trading/signal_pusher.py` | 380 | ⚠️ 独立(飞书/微信) |
| **智能复盘** | `real_trading/smart_reviewer.py` | 422 | ⚠️ 独立 |
| **策略优化** | `real_trading/strategy_optimizer.py` | 428 | ⚠️ 独立 |
| **每日信号** | `real_trading/generate_daily_signals.py` | 505 | ⚠️ 与DailyScheduler重叠 |
| **净值跟踪** | `real_trading/nav_tracker.py` | 622 | ⚠️ 独立 |
| **绩效分析** | `real_trading/performance_analyzer.py` | 495 | ⚠️ 独立 |
| **绩效计算** | `real_trading/performance_calculator.py` | 671 | ⚠️ 独立 |
| **调仓报告** | `real_trading/daily_rebalance_report.py` | 519 | ⚠️ 独立 |
| **数据维护** | `real_trading/data_maintainer.py` | 848 | ⚠️ 独立(与eastmoney脚本重叠) |
| **多账户** | `real_trading/multi_account_manager.py` | 421 | ⚠️ 独立 |
| **前端** | `frontend/src/views/trading/LiveTradingView.vue` | 481 | ✅ 基础UI |
| **前端API** | `frontend/src/api/modules/trading.ts` | 200+ | ✅ 类型定义 |

### 核心问题
1. **双份调度器**: `real_trading/daily_scheduler.py` (947行独立脚本) vs `nodes/scheduler/daily_scheduler.py` (整合版)
2. **双份模拟盘**: `real_trading/paper_trading.py` vs `core/managers/sim_trading_engine.py`
3. **real_trading/ 全是独立脚本**: 9800行代码各自为政，没有统一入口，没有import到AgentServer
4. **交易网关只有框架**: `trade_gateway.py` 定义了AB C但没实现任何券商
5. **实时监控用轮询**: AKShare 30秒轮询，不是真正的实时行情

## 分支目标

### Phase 1: 整合 & 清理
- [ ] 合并 `real_trading/daily_scheduler.py` → `nodes/scheduler/daily_scheduler.py`
- [ ] 合并 `real_trading/paper_trading.py` → `core/managers/sim_trading_engine.py`
- [ ] 把有用的独立模块整合进 `AgentServer/nodes/` 或 `AgentServer/core/`
- [ ] 删除 `real_trading/` 中已整合的重复代码
- [ ] 统一数据维护: `data_maintainer.py` → 复用 `scripts/eastmoney_*.py`

### Phase 2: 市场监听
- [ ] WebSocket实时行情接入 (替代AKShare轮询)
- [ ] 量脉1分钟K线订阅 (有Token, 120次/分钟)
- [ ] 大盘异动检测 (涨跌停数量/速度/板块轮动)
- [ ] 持仓股实时监控 (止损/止盈/异动告警)
- [ ] 前端实时行情面板 (WebSocket推送)

### Phase 3: 实盘交易闭环
- [ ] 交易网关实现: 券商API对接 (QMT/掘金/恒生)
- [ ] 下单→成交→持仓 全链路
- [ ] T+1限制/涨跌停不可买/停牌检查
- [ ] 实时风控: 单股/行业/总仓位/回撤
- [ ] 信号→审核→下单 工作流

### Phase 4: 智能化
- [ ] 信号质量评分 (历史胜率+市场环境)
- [ ] 自适应仓位管理
- [ ] 盘后智能复盘 (GPT分析)
- [ ] 策略参数动态优化

## 架构设计

```
AgentServer/
├── nodes/
│   ├── scheduler/          # 已有: 每日调度
│   │   └── daily_scheduler.py
│   ├── market_monitor/     # 新增: 市场监听
│   │   ├── __init__.py
│   │   ├── ws_feed.py      # WebSocket行情源
│   │   ├── anomaly.py      # 异动检测
│   │   └── alert.py        # 告警推送
│   ├── trade_gateway/      # 新增: 交易网关
│   │   ├── __init__.py
│   │   ├── base.py         # 抽象基类
│   │   ├── sim.py          # 模拟盘 (复用SimTradingEngine)
│   │   └── qmt.py          # QMT实盘 (TODO)
│   └── web/api/
│       ├── scheduler.py    # 已有
│       ├── monitor.py      # 新增: 监听API
│       └── live_trade.py   # 新增: 实盘API
├── core/
│   └── managers/
│       └── sim_trading_engine.py  # 已有
frontend/
├── views/
│   └── trading/
│       ├── LiveTradingView.vue     # 已有,需增强
│       └── MarketMonitorView.vue   # 新增: 市场监听
└── api/modules/
    ├── trading.ts          # 已有
    └── monitor.ts          # 新增
```

## 第一优先级

从Phase 1开始: 整合现有代码，消除重复，建立可工作的模拟盘闭环。
