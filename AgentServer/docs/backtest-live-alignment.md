# 回测如何真实对标实盘 — 完整方案

> 2026-05-13 | 从第一性原理推导，不是打补丁

---

## 核心原则：信号时刻的信息边界

实盘交易的本质：**你只能在信号触发的那一刻，用那一刻已知的信息做决策。**

```
回测(现状):  T-1日收盘选股 → T日open买入  ← 错！用T日close选股
实盘(真实):  T日盘中观察 → 信号触发时买入  ← 对！只用当前已知信息
```

回测对标实盘的唯一标准：**任何时刻的决策，只用该时刻之前的信息。**

---

## 一、问题根因：日线数据的信息边界

日线OHLCV只给我们4个价格点，没有盘中时间序列。关键问题：

| 因子 | 9:30可用 | 10:00可用 | 11:00可用 | 15:00可用 |
|------|---------|----------|----------|----------|
| open | ✅ | ✅ | ✅ | ✅ |
| pct_chg(实时) | ✅(≈0) | ✅(约半程) | ✅(约70%) | ✅(收盘) |
| volume_ratio | ✅(早盘偏大) | ✅ | ✅ | ✅ |
| is_limit_up | ❌(不知道) | ⚠️(可能封板) | ⚠️ | ✅(确认) |
| close | ❌ | ❌ | ❌ | ✅ |
| high/low | ❌(还在走) | ❌ | ❌ | ✅ |

**关键洞察**: 不同策略的信号在不同时刻触发，可用信息不同。

---

## 二、每个策略的信息模型

### 半路追涨（97.4%的交易量）

```
实盘信号时刻: ≈10:00-11:00 (股价涨到2-7%时触发)
盘中可用信息: open, 当前价(≈+2~5%), volume_ratio, turnover_rate(累计)
盘中不可用: close, 是否全天维持涨幅

当前回测:
  选股: pct_chg ≥ 2% (用close算的)
  买入: open价 (9:30价)
  问题: 9:30时股票还没涨2%！用close选股是未来函数

正确模型:
  选股: open * (1 + min_rise) ≤ high (盘中确实涨到了阈值)
        这等价于: 当日振幅覆盖了信号触发区间
  买入: open * (1 + min_rise * signal_fraction)
        signal_fraction = 信号触发时已涨幅占全日涨幅的比例
        保守估计: 0.5 (信号在日中区间触发)
```

**买入价公式**:
```python
# 半路追涨正确买入价
if close > open:  # 阳线(上涨日)
    # 股价从open涨到close，信号在涨到min_rise时触发
    # 但我们无法知道盘中轨迹，保守假设在日内30-50%位置触发
    trigger_fraction = 0.4  # 保守: 信号在40%的日内涨幅处触发
    buy_price = open + (close - open) * trigger_fraction
    # 不能低于阈值价(至少涨了min_rise才触发)
    threshold_price = open * (1 + min_rise_pct)
    buy_price = max(buy_price, threshold_price)
else:
    # 高开低走: 不应选入(实盘看到的是冲高回落)
    # 但如果low曾触发过(盘中涨过)，需要判断
    buy_price = open  # 高开时open就可能已超阈值
```

**但这还不够** — 回测用close的pct_chg选股本身就包含了全天信息。需要改为：

```
正确选股条件(只用盘中可得信息):
  1. volume_ratio ≥ 2.0        ← ✅ 10:00可见
  2. open到信号价之间存在路径    ← 用high确认: high ≥ open*(1+min_rise)
  3. 不用close的pct_chg         ← ❌ 收盘才知道
```

### 首板打板

```
实盘信号时刻: ≈9:30-10:00 (封板瞬间)
盘中可用信息: open, 当前价=涨停价, 是否封板, 封单量
盘中不可用: 是否全天封住(可能炸板)

当前回测:
  选股: is_limit_up=1 (close确认涨停)
  买入: close(涨停价)
  问题: 收盘确认涨停, 但封板可能在盘中任何时候

正确模型:
  选股: high ≥ 涨停价 (盘中确实到过涨停)
  买入: 涨停价 (和现在一样)
  新增风险: 炸板概率 — 用open_times/limit_up_open_count建模
    - 一字板(open=close=high=low): 0%买入概率(排不到)
    - 早封板(limit_up_time ≤ 10:00): 炸板率低, 可买
    - 晚封板(limit_up_time > 13:00): 炸板率高, 应过滤

这和当前逻辑基本一致, 首板打板的回测偏差相对最小。
```

### 跌停翘板

```
实盘信号时刻: ≈9:30-10:30 (跌停板被撬开)
盘中可用信息: open是否高于跌停价, 成交量放大
盘中不可用: 之后是否重新跌停

当前回测:
  选股: limit_down_yesterday=1, open_above_limit_down=1
  买入: low * 1.005 (接近最低价)
  问题: 买入价用low是合理的(跌停撬板确实在低价区)

正确模型: 基本同现有逻辑, 但需要加入"重新跌停"的风险
  - 翘板后可能再次封死跌停
  - 用 open_above_limit_down + is_limit_down(当日最终) 建模
  - 如果当日最终is_limit_down=1(重新封死), 实际无法卖出
```

### 龙头低吸

```
实盘信号时刻: ≈全天(回调到支撑位时)
盘中可用信息: 当前价接近支撑位, 前期连板历史
当前回测买入: low * 1.005 (接近最低价)
偏差: 用low买入偏乐观(不可能精确抄底)

正确模型:
  buy_price = low + (high - low) * 0.3  (在日内30%位置接)
  或: buy_price = max(low * 1.01, support_level_price)
```

---

## 三、完整修复方案

### 第一层：信号生成 — 只用历史信息

**核心改动**: 把"用T日close选T日买"改为"T-1日选股→T日验证执行"

```python
def select_stocks_for_tomorrow(trade_date_T_minus_1):
    """T-1日收盘后选股，为T日做准备"""
    # T-1日的所有因子都已知（close, pct_chg, is_limit_up等）
    # 用T-1日数据选候选池
    candidates = apply_strategy_filters(T_minus_1_factors)
    return candidates

def execute_on_trade_day(trade_date_T, candidates):
    """T日盘中执行候选池中的股票"""
    prices = get_T_day_open(trade_date_T)  # 只用open及之前的
    
    for stock in candidates:
        # T日验证：开盘后是否符合条件
        if strategy_specific_check(stock, prices):
            buy(stock, get_realistic_buy_price(stock))
```

**但这有个问题** — 半路追涨的核心是"盘中涨2-7%时追入"，这是T日盘中事件，不是T-1能预测的。

### 第二层（更正确）：T日盘中信号模型

不是T-1选股，而是**用T日盘中可得信息选股**，但约束信息边界：

```python
def apply_strategy_filter_intraday(df, trade_date):
    """盘中信号筛选——只用盘中可得信息"""
    
    # ===== 半路追涨 =====
    # 条件1: volume_ratio ≥ 2.0  ← 盘中可见
    # 条件2: 盘中涨到过min_rise  ← 用high验证: high ≥ open*(1+min_rise)
    # 条件3: 不在涨停价          ← close < 涨停价 或 high < 涨停价*1.01
    # ❌ 不用: close的pct_chg（收盘才知道）
    # ❌ 不用: turnover_rate的收盘值（盘中只有累计值）
    
    halfway_mask = (
        (df['volume_ratio'] >= 2.0) &
        (df['high'] >= df['open'] * (1 + 0.02)) &  # 盘中涨到过2%
        (df['close'] < df['pre_close'] * 1.095)     # 非涨停
    )
    
    # ===== 首板打板 =====
    # 条件: 盘中封板 ← high ≥ 涨停价
    # 不用close确认(可能炸板后回封)
    first_limit_mask = (
        (df['high'] >= df['pre_close'] * 1.095) &  # 到过涨停
        (df['limit_up_yesterday'] == 0)              # 昨日未涨停
    )
```

### 第三层：买入价模型

```python
def get_realistic_buy_price(strategy, row):
    """根据策略特性，计算真实可成交的买入价"""
    
    if strategy == '半路追涨':
        # 信号在涨2%时触发，不是9:30(open)时
        # 保守估计: 买入价 = open + 日内涨幅的40%
        # 这模拟了10:00左右追入的真实价格
        o, h, l, c = row['open'], row['high'], row['low'], row['close']
        if c > o:  # 阳线
            threshold = o * (1 + 0.02)  # 涨2%触发
            # 在threshold和c之间取一个点(保守取40%位置)
            buy = threshold + (c - threshold) * 0.4
            return max(buy, threshold)
        else:
            # 高开低走: 不应买入(实盘看到冲高会犹豫)
            return 0  # 跳过
    
    elif strategy == '首板打板':
        # 涨停价买入(和现有逻辑一致)
        return get_limit_up_price(row)
    
    elif strategy == '跌停翘板':
        # 翘板后买入，价格在跌停价附近
        # 实际在跌停价上方1-3%买入
        limit_down = row['pre_close'] * 0.9
        return max(row['low'], limit_down) * 1.01
    
    elif strategy == '龙头低吸':
        # 回调到支撑位买入，不可能精确抄底
        # 在low上方一些买入
        return row['low'] + (row['high'] - row['low']) * 0.25
```

### 第四层：卖出价模型（关键！）

当前回测用close卖出，但实盘止损在盘中触发，可能更差：

```python
def get_realistic_sell_price(sell_reason, row):
    """卖出价模型"""
    
    if sell_reason == '止损':
        # 止损在盘中触发，价格可能比close更差
        # 用策略级止损价而非close
        stop_price = cost_basis * (1 - stop_loss_pct)
        # 实际成交: 止损价 - 滑点(市场冲击)
        return stop_price * (1 - slippage_pct)
    
    elif sell_reason == '止盈':
        # 止盈可能在盘中触发，也可能收盘才确认
        take_profit_price = cost_basis * (1 + take_profit_pct)
        return take_profit_price * (1 - slippage_pct)
    
    elif sell_reason == '调仓卖出':
        # 正常卖出用open价(次日开盘卖出)
        return row['open'] * (1 - slippage_pct)
    
    elif sell_reason == '跳空止损':
        # ⚠️ 最重要的新增场景！
        # low直接跌破止损价(跳空低开)，实际卖出价=low附近
        stop_price = cost_basis * (1 - stop_loss_pct)
        if row['open'] < stop_price:
            # 开盘就低于止损 → 以open价卖出(最差情况)
            return row['open'] * (1 - slippage_pct)
        elif row['low'] < stop_price:
            # 盘中跌破止损 → 以止损价卖出
            return stop_price * (1 - slippage_pct)
```

### 第五层：T+1约束

```python
class BacktestHoldings:
    """持仓管理(含T+1)"""
    
    def __init__(self):
        self.holdings = {}  # {ts_code: shares}
        self.buy_date = {}  # {ts_code: trade_date}  ← 新增
        self.today_buys = set()  # 当日买入的股票 ← 新增
    
    def can_sell(self, ts_code: str, current_date: int) -> bool:
        """T+1: 当日买入不可卖出"""
        buy_dt = self.buy_date.get(ts_code)
        if buy_dt is None:
            return False
        return current_date > buy_dt  # 必须是T+1日之后
    
    def buy(self, ts_code, shares, date):
        self.holdings[ts_code] = self.holdings.get(ts_code, 0) + shares
        self.buy_date[ts_code] = date
        self.today_buys.add(ts_code)
    
    def sell(self, ts_code, shares):
        if ts_code in self.holdings:
            self.holdings[ts_code] -= shares
            if self.holdings[ts_code] <= 0:
                del self.holdings[ts_code]
                del self.buy_date[ts_code]
```

### 第六层：炸板/回封模型

```python
def should_fill_limit_up_order(ts_code, row, order_type='buy'):
    """涨停买入的成交概率模型
    
    基于limit_up_time和limit_up_open_count:
    - 一字板: 0%成交(排不到)
    - 早封板(≤10:00) + 未炸板: 80%成交
    - 早封板 + 炸板1次: 50%成交
    - 晚封板(>13:00): 30%成交
    - 多次炸板: 20%成交
    """
    open_times = row.get('limit_up_open_count', 0)
    limit_time = row.get('limit_up_time', 1000)
    
    if row['open'] == row['close'] == row['high'] == row['low']:
        return 0.0  # 一字板
    
    if limit_time <= 1000:  # 早封板
        if open_times == 0:
            return 0.8
        elif open_times == 1:
            return 0.5
        else:
            return 0.3
    else:  # 晚封板
        return 0.3 if open_times <= 1 else 0.15
```

---

## 四、选股条件修正对照表

| 策略 | 当前条件(用close) | 修正条件(盘中可得) |
|------|------------------|------------------|
| **半路追涨** | pct_chg ≥ 2% (close) | high ≥ open×1.02 + volume_ratio ≥ 2.0 |
| | pct_chg ≤ 7% (close) | close < 涨停价 (不追涨停) |
| | volume_ratio ≥ 2.0 | volume_ratio ≥ 2.0 (不变) |
| **首板打板** | is_limit_up=1 (close) | high ≥ 涨停价 (盘中到过) |
| | limit_up_yesterday=0 | limit_up_yesterday=0 (不变) |
| **跌停翘板** | open_above_limit_down=1 | open > 跌停价 (开盘可见) |
| | limit_down_yesterday=1 | limit_down_yesterday=1 (不变) |
| **龙头低吸** | pullback_pct ≥ 8% | low ≤ 支撑价×1.05 (盘中跌到) |
| | limit_up_count ≥ 2 | limit_up_count ≥ 2 (不变) |

**关键变化**: 把 `pct_chg` (收盘值) 替换为 `high/open` (盘中可达性验证)

---

## 五、买入价修正对照表

| 策略 | 当前买入价 | 修正买入价 | 差异 |
|------|-----------|-----------|------|
| **半路追涨** | open (9:30价) | open×(1+min_rise×0.5)~open×1.03 | 高2-3% |
| **首板打板** | 涨停价 | 涨停价(不变) | 0 |
| **跌停翘板** | low×1.005 | max(low, 跌停价)×1.01 | 略高 |
| **龙头低吸** | low×1.005 | low+(high-low)×0.25 | 略高 |

**半路追涨影响最大**: 买入价从open提高到约+3%，相当于每笔成本增加2-3%，73,863笔交易累计影响巨大。

---

## 六、止损止盈修正

| 方面 | 当前 | 修正 |
|------|------|------|
| 卖出价 | close | 止损价×(1-滑点) 或 open(次日) |
| 跳空缺口 | ❌ 无法处理 | open < 止损价 → 以open卖出 |
| T+1 | ❌ 无 | 当日买入不可卖 |
| 止损检查 | daily(close) | daily(low检查+open检查) |

**跳空止损处理**:
```python
# 当前: low ≤ 止损价 → 以close卖出 (虚高！)
# 修正: 
if open < stop_price:
    sell_at = open  # 开盘就破止损，以open卖出(最差)
elif low <= stop_price:
    sell_at = stop_price  # 盘中破止损，以止损价卖出
```

---

## 七、回测对标的终极验证

修完以上6层后，如何验证回测真的对标实盘？

### 方法1: 纸上回测 vs 模拟盘

1. 用修正后的回测引擎跑历史区间
2. 用MarketScanner(模拟模式)跑同样的区间
3. 对比两者的信号、成交价、收益

### 方法2: 滚动验证

1. 每天收盘后，用修正回测跑当日数据
2. 对比实盘Scanner的当日信号和成交
3. 如果信号一致率>80%，买入价偏差<1%，则可信

### 方法3: 留一法(最严格)

1. 用2024.5-2025.12的数据优化参数
2. 用2026.1-2026.5的数据验证(未参与优化)
3. 如果验证期收益与回测接近(偏差<50%)，策略可信

---

## 八、预期影响

### 对半路追涨(97.4%交易量)的影响

```
当前: open买入 → 收益2.1万倍
修正: open×1.03买入 → 每笔成本+3%
     73,863笔 × 3% ≈ 累计成本增加2216%
     
加上: T+1限制 → 当日无法止损，增加跳空风险
加上: close→盘中止损价 → 止损价更差
加上: 未来函数消除 → 信号减少(不会选到高开低走的)

预估: 收益从2.1万倍降至100-500倍(仍然可观但理性)
      或者降至10倍以下(如果半路追涨的alpha主要来自信息优势)
```

### 对其他策略

- **首板打板**: 影响较小(涨停价买入模型合理)，但T+1增加风险
- **跌停翘板**: 影响中等(买入价模型需微调)
- **龙头低吸**: 影响中等(low价买入偏乐观)

---

## 九、实施路径

### Phase 1: 最小可信回测 (1-2天)

只改最关键的3处，重跑验证：

1. **半路追涨买入价**: open → max(open×1.02, threshold_price)
2. **T+1约束**: 加入buy_date追踪，当日不可卖
3. **止损卖出价**: close → stop_price(含跳空处理)

跑完后看收益。如果仍有正alpha → 策略可信，继续优化。如果收益崩溃 → 之前的收益全是回测幻觉。

### Phase 2: 信息边界修正 (2-3天)

4. **选股条件**: pct_chg → high/open (消除未来函数)
5. **半路追涨买入价精调**: 引入日内价格路径模型
6. **首板打板成交概率**: 炸板模型

### Phase 3: 实盘对标验证 (1-2天)

7. 统一Scanner和Backtest的撮合引擎
8. 滚动验证：回测 vs 模拟盘
9. 输出差异报告

### Phase 4: 架构统一 (3-5天)

10. 提取`strategy_filter.py`独立模块
11. 回测改用SimulatedBroker撮合
12. DailyScheduler职责精简
