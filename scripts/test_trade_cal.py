#!/usr/bin/env python3
import os
import tushare as ts

token = os.getenv("TUSHARE_TOKEN")
if not token:
    raise ValueError("请设置环境变量 TUSHARE_TOKEN")
pro = ts.pro_api(token)
pro._DataApi__token = token
pro._DataApi__http_url = 'https://x-fpv.com'

print("Testing trade_cal 20260105 ~ 20260320")
print()

df = pro.trade_cal(start_date='20260105', end_date='20260320', is_open='1')
print(f"Shape: {df.shape}")
print(df.head(20))
print()

# 试试 exchange=SSE
df2 = pro.trade_cal(exchange='SSE', start_date='20260105', end_date='20260320', is_open='1')
print(f"With exchange=SSE, shape: {df2.shape}")
print(df2.head(20))
