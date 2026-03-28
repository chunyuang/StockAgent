#!/usr/bin/env python3
"""
测试 Tushare 代理连接 - 获取交易日历
"""

import os
from dotenv import load_dotenv
import tushare as ts

# 加载环境变量
load_dotenv()

token = os.getenv('TUSHARE_TOKEN', '')
http_url = os.getenv('TUSHARE_HTTP_URL', '')

print("Testing proxy connection with trade_cal...")
print(f"Token: {token[:4]}****")
print(f"Proxy URL: {http_url}")
print()

try:
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    if http_url:
        pro._DataApi__http_url = http_url

    df = pro.trade_cal(start_date='20260105', end_date='20260320', is_open='1')
    print("✅ SUCCESS! Got trade calendar:")
    print(df)
    print()
    print(f"Retrieved {len(df)} trading days")
except Exception as e:
    print(f"❌ FAILED: {e}")
    import traceback
    traceback.print_exc()
