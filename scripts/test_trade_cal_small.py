#!/usr/bin/env python3
import tushare as ts
import time

token = "3b610bc78011b162b4bbb5efa8c4f0ee"
pro = ts.pro_api(token)
pro._DataApi__token = token
pro._DataApi__http_url = 'https://x-fpv.com'

print("Testing trade_cal 20260105 ~ 20260110")
print()

time.sleep(1)
df = pro.trade_cal(exchange='SSE', start_date='20260105', end_date='20260110', is_open='1')
print(f"Shape: {df.shape}")
print(df)
