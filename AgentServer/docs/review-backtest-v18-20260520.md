# V18回测模块审查报告

**审查日期**: 2026-05-20
**审查范围**: portfolio_backtest.py (4034行) + ultra_short.py (675行) + strategy_defaults.py
**基线版本**: commit 571db78 (V17)
**V17基线结果**: 2策略 收益69.38% 夏普9.01 回撤3.05% 胜率68.27% 104笔

---

## 审查方法

系统性通读ultra_short.py全文 + portfolio_backtest.py关键逻辑段，重点检查：
1. 数据一致性（SL/TP参数、fallback值、买卖价格）
2. 边界条件（除零、空值、T+1）
3. 代码重复与同步
4. 卖出逻辑3处一致性（调仓日无交易/非调仓日/_rebalance内）

## 审查发现

### P0级 (0项)

无P0级问题。V1-V17的修复已经覆盖了主要数据正确性bug。

### P1级 (1项)

**P1-1: `_rebalance`中buy_p=0时ZeroDivisionError风险(已修复)**
- 位置: `_rebalance` L3574 `shares = int(int(target_value / buy_p) / 100) * 100`
- 问题: buy_p从`_get_buy_price_for_stock`获取，当返回0时fallback到open_price。若open也为0(停牌股)，除零异常
- 触发条件: 停牌股仍在目标池中(universe_mgr应已排除，但极端case可能漏过)
- 修复: 添加 `if buy_p <= 0: continue` 防护

### P2级 (代码质量，4项)

**P2-1: 止损止盈参数获取3处重复，应统一调用`_get_sl_tp_for_code`**
- 位置: L1764-1767(调仓日无交易)、L1892-1895(非调仓日)、L3601(_rebalance内)
- 现状: 3处都内联了相同的逻辑`sl_pct = min(strategy_rp.get(...))`
- 建议: 统一调用`self._get_sl_tp_for_code(code)`
- 风险: 如果未来修改_get_sl_tp_for_code逻辑，其他2处可能不同步

**P2-2: 清仓方式不一致: `del holdings[code]` vs `holdings[code]=0`**
- 位置: L1793/L1974用del，L1193/L3778/L3849用=0
- 影响: 中间状态不一致，但最终`holdings = {code: shares for code, shares in holdings.items() if shares > 0}`统一清理
- 建议: 统一为`holdings[code] = 0`，最终清理由dict comprehension处理

**P2-3: `volume_threshold`参数fallback用`or`而非`if None`**
- 位置: L356 `params.get("volume_threshold", params.get("min_volume_ratio")) or 2.0`
- 问题: 如果min_volume_ratio=0(不合理但理论上)，`or 2.0`会变成2.0
- 影响: 极低概率，实际不会触发

**P2-4: merged_trades中sell_cost=0时ZeroDivisionError风险**
- 位置: L2172 `profit = (net_sell_amount - sell_cost) / sell_cost * 100`
- 问题: 如果sell_cost=0，除零异常
- 触发条件: 理论上不可能(buy_rec.amount>0)，但缺乏防护
- 建议: 添加`if sell_cost > 0`防护

---

## V18验证结果(2策略 20260105-20260320)

| 指标 | V17 | V18 | 变化 |
|------|-----|-----|------|
| 收益 | 69.38% | 69.38% | 0 |
| 回撤 | 3.05% | 3.05% | 0 |
| 胜率 | 68.27% | 68.27% | 0 |
| 夏普 | 9.01 | 9.01 | 0 |
| 盈亏比 | 2.15 | 2.15 | 0 |
| 交易 | 104笔 | 104笔 | 0 |
| other | 0 | 0 | ✅ |

无回归。P1-1修复为防御性代码，当前数据无触发。

## 结论

经过V1-V18共18轮审查，回测模块核心逻辑已相当稳健：
- 数据正确性: 卖出原因other=0，所有止损止盈冲高回落逻辑一致
- 代码质量: 仍有3处止损止盈参数获取重复(P2-1)，但不影响正确性
- 防御性: P1-1增加了buy_p=0防护

**建议**: 后续可考虑将P2-1的3处重复提取为_get_sl_tp_for_code统一调用，进一步降低不同步风险。但当前不影响回测结果。
