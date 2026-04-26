#!/usr/bin/env python3
"""
调试 Tushare 官方 API
"""

import os
import tushare as ts

token = os.getenv("TUSHARE_TOKEN")
if not token:
    raise ValueError("请设置环境变量 TUSHARE_TOKEN")
pro = ts.pro_api(token)

print("=== 直接调试 Tushare 官方 API ===")
print(f"token: {token}")
print(f"http_url: {pro._DataApi__http_url}")
print()

# 测试获取交易日历
print("=== 测试 trade_cal ===")
try:
    df = pro.trade_cal(start_date='20260105', end_date='20260105', is_open='1')
    print(f"trade_cal result: {df.shape}")
    print(df)
except Exception as e:
    print(f"❌ Error: {e}")

print()

# 测试获取日线数据 000001.SZ
print("=== 测试 daily 000001.SZ ===")
try:
    df = pro.daily(ts_code='000001.SZ', start_date='20260105', end_date='20260105')
    print(f"daily result: {df.shape}")
    print(df)
except Exception as e:
    print(f"❌ Error: {e}")

print()

# 测试按日期获取
print("=== 测试 daily by trade_date 20260105 ===")
try:
    df = pro.daily(trade_date='20260105')
    print(f"daily result: {df.shape}")
    if not df.empty:
        print(df.head())
except Exception as e:
    print(f"❌ Error: {e}")
