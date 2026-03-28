#!/usr/bin/env python3
"""
测试 Tushare 代理连接
"""

import os
from dotenv import load_dotenv
import tushare as ts

# 加载环境变量
load_dotenv()

token = os.getenv('TUSHARE_TOKEN', '')
http_url = os.getenv('TUSHARE_HTTP_URL', '')

pro = ts.pro_api(token)

pro._DataApi__token = token
if http_url:
    pro._DataApi__http_url = http_url

# 测试获取一条数据
print("Testing proxy connection...")
print(f"Token: {token[:4]}****")
print(f"Proxy URL: {http_url}")
print()

try:
    df = pro.daily(ts_code='000001.SZ', start_date='20260105', end_date='20260320')
    print("✅ SUCCESS! Got data:")
    print(df)
    print()
    print(f"Retrieved {len(df)} rows")
except Exception as e:
    print(f"❌ FAILED: {e}")
