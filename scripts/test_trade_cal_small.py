#!/usr/bin/env python3
import os
import time
import tushare as ts

token = os.getenv("TUSHARE_TOKEN")
if not token:
    raise ValueError("请设置环境变量 TUSHARE_TOKEN")
pro = ts.pro_api(token)
pro._DataApi__token = token
pro._DataApi__http_url = 'https://x-fpv.com'

print("Testing trade_cal 20260105 ~ 20260110")
print()

time.sleep(1)
df = pro.trade_cal(exchange='SSE', start_date='20260105', end_date='20260110', is_open='1')
print(f"Shape: {df.shape}")
print(df)
