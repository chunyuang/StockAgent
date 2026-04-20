#!/usr/bin/env python3
"""
弱势行情宽松参数版回测
"""
import pymongo
import pandas as pd
from tqdm import tqdm

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

START_DATE = 20251217
END_DATE = 20260317
INITIAL_CAPITAL = 1000000
LIQUIDITY_THRESHOLD = 300  # 进一步放宽到300万
SLIPPAGE = 0.001
COMMISSION = 0.0002
STAMP_DUTY = 0.001
MAX_POSITION_PER_STOCK = 0.2

print("🚀 弱势行情宽松参数回测启动")
print("="*60)
print(f"📅 区间: {START_DATE} ~ {END_DATE}")
print(f"💰 初始资金: {INITIAL_CAPITAL:,}")
print("🔧 参数: 流动性300万 | 量能放大≥1.2倍 | 低开0-7%")
print("="*60)

# 预加载数据
all_dates = sorted(coll.distinct('trade_date', {'trade_date': {'$gte': START_DATE, '$lte': END_DATE}}))
all_ts_codes = coll.distinct('ts_code')

print("⏳ 预加载全市场数据...")
all_data = {}
for ts_code in tqdm(all_ts_codes, desc="加载中"):
    data = list(coll.find({
        'ts_code': ts_code,
        'trade_date': {'$gte': 20251201, '$lte': END_DATE}
    }).sort('trade_date', 1))
    if len(data) >= 20:
        df = pd.DataFrame(data)
        df = df.sort_values('trade_date').reset_index(drop=True)
        # 预计算因子
        df['is_limit_up'] = abs(df['close'] - df['up_limit']) < 0.01
        df['limit_up_yesterday'] = df['is_limit_up'].shift(1).fillna(False).astype(int)
        df['prev_up_limit'] = df['up_limit'].shift(1)
        df['open_pct_diff'] = (df['prev_up_limit'] - df['open']) / df['prev_up_limit']
        df['open_below_limit_loose'] = ((df['open_pct_diff'] >= 0) & (df['open_pct_diff'] <= 0.07)).astype(int)  # 放宽到0-7%
        df['volume_increase_loose'] = (df['vol'] / df['vol'].rolling(5).mean() >= 1.2).astype(int)  # 进一步放宽到1.2倍
        df['limit_up_sum_20d'] = df['is_limit_up'].rolling(20).sum().shift(1)
        df['first_limit_up'] = ((df['is_limit_up'] == True) & (df['limit_up_sum_20d'] < 1)).astype(int)
        all_data[ts_code] = df

print(f"✅ 加载完成，有效股票数: {len(all_data)}只")

# 回测半路追涨策略（宽松版）
cash = INITIAL_CAPITAL
holdings = {}
daily_values = []
trades = []

print("\n📈 开始回测半路追涨（宽松参数）:")
for idx, trade_date in enumerate(all_dates):
    # 先卖出
    to_sell = []
    for ts_code, (vol, buy_price) in holdings.items():
        df = all_data.get(ts_code)
        if df is None or len(df) == 0:
            continue
        pos = df[df['trade_date'] == trade_date].index
        if len(pos) == 0:
            continue
        pos = pos[0]
        sell_price = df.iloc[pos]['close'] * (1 - SLIPPAGE)
        sell_amount = vol * sell_price
        commission = max(5, sell_amount * COMMISSION)
        stamp = sell_amount * STAMP_DUTY
        cash_got = sell_amount - commission - stamp
        cash += cash_got
        trades.append({
            'date': trade_date,
            'type': 'sell',
            'ts_code': ts_code,
            'profit': (sell_price - buy_price) * vol - commission - stamp
        })
        to_sell.append(ts_code)
    for ts_code in to_sell:
        del holdings[ts_code]
    
    # 选股
    candidates = []
    for ts_code, df in all_data.items():
        pos = df[df['trade_date'] == trade_date].index
        if len(pos) == 0:
            continue
        pos = pos[0]
        if pos < 2:
            continue
        row = df.iloc[pos]
        # 宽松半路追涨条件
        if (row['limit_up_yesterday'] == 1 
            and row['open_below_limit_loose'] == 1
            and row['volume_increase_loose'] == 1
            and row['amount'] >= LIQUIDITY_THRESHOLD):
            candidates.append({
                'ts_code': ts_code,
                'open': row['open'],
                'amount': row['amount']
            })
    
    # 买入
    if candidates and cash > 0:
        position_per_stock = min(cash * MAX_POSITION_PER_STOCK, cash / len(candidates))
        for item in candidates:
            ts_code = item['ts_code']
            open_price = item['open'] * (1 + SLIPPAGE)
            if position_per_stock < open_price * 100:
                continue
            volume = int(position_per_stock / (open_price * 100)) * 100
            cost = volume * open_price
            commission = max(5, cost * COMMISSION)
            total_cost = cost + commission
            if cash < total_cost:
                continue
            cash -= total_cost
            holdings[ts_code] = (volume, open_price)
            trades.append({
                'date': trade_date,
                'type': 'buy',
                'ts_code': ts_code,
                'volume': volume,
                'buy_price': open_price
            })
    
    # 统计净值
    current_value = cash
    for ts_code, (vol, buy_price) in holdings.items():
        df = all_data.get(ts_code)
        pos = df[df['trade_date'] == trade_date].index
        if len(pos) > 0:
            current_value += vol * df.iloc[pos[0]]['close']
    daily_values.append({'date': trade_date, 'value': current_value})
    
    if (idx + 1) % 10 == 0:
        print(f"📅 {trade_date} | 净值: {current_value:,.2f} | 持仓: {len(holdings)}只 | 候选: {len(candidates)}只")

# 统计结果
final_value = cash
for ts_code, (vol, buy_price) in holdings.items():
    df = all_data.get(ts_code)
    pos = df[df['trade_date'] == END_DATE].index
    if len(pos) > 0:
        final_value += vol * df.iloc[pos[0]]['close']

total_return = (final_value - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
max_drawdown = 0
peak = INITIAL_CAPITAL
for dv in daily_values:
    if dv['value'] > peak:
        peak = dv['value']
    drawdown = (peak - dv['value']) / peak * 100
    if drawdown > max_drawdown:
        max_drawdown = drawdown

sell_trades = [t for t in trades if t['type'] == 'sell']
win_trades = [t for t in sell_trades if t['profit'] > 0]
win_rate = len(win_trades) / len(sell_trades) * 100 if sell_trades else 0

print("\n" + "="*60)
print("📊 宽松版半路追涨回测结果")
print("="*60)
print(f"初始资金: {INITIAL_CAPITAL:,.2f}元")
print(f"最终资金: {final_value:,.2f}元")
print(f"总收益率: {total_return:.2f}%")
print(f"最大回撤: {max_drawdown:.2f}%")
print(f"总交易次数: {len(sell_trades)}次")
print(f"胜率: {win_rate:.2f}%")
