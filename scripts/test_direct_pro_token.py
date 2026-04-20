#!/usr/bin/env python3
import tushare as ts

# 使用你的 Pro 账号 token 直接测试
token = "3b610bc78011b162b4bbb5efa8c4f0ee"
pro = ts.pro_api(token)

# 不需要修改 http_url，因为默认使用官方地址，token 正确应该能访问
print("=== Testing your Pro token directly ===\n")
print(f"token: {token}")
print()

df = pro.trade_cal(exchange='SSE', start_date='20260105', end_date='20260320', is_open='1')
print(f"Result shape: {df.shape}")
print()
if not df.empty:
    print(df.head(10))
    print()
    print(f"Got {len(df)} trading days")
else:
    print("❌ Empty result!")
