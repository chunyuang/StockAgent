#!/usr/bin/env python3
"""
单独验证 Tushare trade_cal 接口
"""

import os
import tushare as ts

token = os.getenv("TUSHARE_TOKEN")
if not token:
    raise ValueError("请设置环境变量 TUSHARE_TOKEN")
pro = ts.pro_api(token)

print("=== Testing Tushare trade_cal (official API) ===")
print(f"token: {token}")
print(f"http_url: {pro._DataApi__http_url}")
print()

# 测试获取 2026-01-05 ~ 2026-03-20
print("Requesting: exchange='SSE', start_date='20260105', end_date='20260320', is_open='1'")
print()

df = pro.trade_cal(exchange='SSE', start_date='20260105', end_date='20260320', is_open='1')

print(f"Result shape: {df.shape}")
print()
if not df.empty:
    print(df.head(20))
    print()
    print(f"Total trading days: {len(df)}")
else:
    print("❌ Got empty DataFrame!")
