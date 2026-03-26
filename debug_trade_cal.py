#!/usr/bin/env python3
import asyncio
import sys
import pandas as pd

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from core.managers.tushare_manager import tushare_manager

async def debug():
    await tushare_manager.initialize()
    
    # Direct call pro.trade_cal
    import tushare as ts
    token = settings.tushare.token.get_secret_value()
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    pro._DataApi__http_url = 'https://x-fpv.com'
    
    print("Direct call: pro.trade_cal(exchange='SSE', start_date='20260105', end_date='20260320', is_open='1')")
    df = pro.trade_cal(exchange='SSE', start_date='20260105', end_date='20260320', is_open='1')
    print(f"shape={df.shape}")
    print(df.head())
    print()
    
    # Check dtypes
    print(df.dtypes)
    print()
    
    # What's in cal_date
    print("cal_date values:")
    print(df["cal_date"].head(10).tolist())
    
    # Convert to list
    print()
    result = df["cal_date"].tolist()
    print(f"result={result}")
    print(f"len(result)={len(result)}")
    
asyncio.run(debug())
