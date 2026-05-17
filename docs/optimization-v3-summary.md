# 实盘交易全面优化V3 — 修复汇总

**日期**: 2026-05-18  
**分支**: feature/live-trading  
**Commit**: 285a30c

---

## 已修复 (本次)

### P0 修复 (3项)
| 编号 | 问题 | 修复 |
|------|------|------|
| P0-1 | `_check_circuit_breaker`是同步方法但内部用了`await` | ✅ 改为`async def`，2个调用点加`await` |
| P0-2 | `save_state`30秒节流在止损后跳过保存 | ✅ 添加`force`参数，止损/止盈后`save_state(force=True)` |
| P0-7 | 卖出后`pos.available_qty`已被修改，timeline记录的profit_amount为0 | ✅ 在`place_order`前保存`sell_qty/sell_profit_pct/sell_profit_amount` |

### P1 修复 (6项)
| 编号 | 问题 | 修复 |
|------|------|------|
| P1-1 | `stop()`不保存状态到MongoDB | ✅ 添加`save_state(force=True)`和`_save_timeline()` |
| P1-2 | 交易终止无清仓选项 | ✅ `stop(sell_all=True)`支持清仓 |
| P1-3 | 一键清仓无确认弹窗 | ✅ 添加`showConfirm`显示持仓数和总市值 |
| P1-4 | 重置账户无确认弹窗 | ✅ 添加`showConfirm`提示不可恢复 |
| P1-5 | 手动下单无确认弹窗 | ✅ 添加`showConfirm`显示代码/方向/数量/金额 |
| P1-6 | WS消息每次都触发5次并发fetch | ✅ 500ms debounce合并多次更新 |

### 前端优化 (3项)
| 编号 | 问题 | 修复 |
|------|------|------|
| FE-1 | `fetchScanner`默认5次并发请求 | ✅ 默认使用`/all`合并端点(1请求) |
| FE-2 | 持仓排序在模板中计算 | ✅ 提取为`sortedPositions` computed |
| FE-3 | 距止损计算可能不正确 | ✅ 优先用`stop_loss_price`计算，回退用`profit_pct + stop_loss_pct` |

### 后端增强 (2项)
| 编号 | 问题 | 修复 |
|------|------|------|
| BE-1 | 日报缺少策略胜率分析 | ✅ 添加`win_rate/closed_count/closed_profit`到策略汇总 |
| BE-2 | stop API不支持清仓 | ✅ 添加`StopScannerRequest(sell_all: bool)`参数 |

---

## 待修复 (后续)

### P0 (0项) — 无

### P1 (4项)
| 编号 | 问题 | 预估工时 |
|------|------|----------|
| P1-7 | 交易确认弹窗`onConfirm`是异步但无loading防重复点击 | 0.5h |
| P1-8 | LiveTradingView已废弃但未删除 | 1h |
| P1-9 | 策略编辑弹窗无参数校验 | 1h |
| P1-10 | 手动下单缺少价格输入框 | 1h |

### P2 (10项) — 见 docs/review-frontend-v3.md

### UX优化 (24项) — 见 docs/review-frontend-v3.md

---

## 文件变更清单

### 后端
- `AgentServer/nodes/market_monitor/scanner.py` — P0-1/P0-2/P0-7/P1-1/P1-2修复
- `AgentServer/nodes/market_monitor/broker.py` — P0-2修复(save_state force参数)
- `AgentServer/nodes/web/api/scanner.py` — P1-2/P1-6修复(策略胜率增强)

### 前端
- `frontend/src/views/monitor/MarketMonitorView.vue` — P1-3/P1-4/P1-5/FE-1/FE-2/FE-3修复

### 文档
- `docs/review-live-trading-v3.md` — 后端审查报告
- `docs/review-frontend-v3.md` — 前端审查报告(5P0+10P1+10P2+24UX+6CQ)