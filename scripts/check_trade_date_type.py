#!/usr/bin/env python3
import pymongo
import sys

# Add paths
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')
from core.settings import settings

client = pymongo.MongoClient(settings.mongo.url)
db = client[settings.mongo.database]

sample = db['stock_daily_ak_full'].find_one()
if sample:
    print('Sample document (stock_daily_ak_full):')
    for k, v in sample.items():
        print(f'  {k}: {repr(v)}, type={type(v).__name__}')
    print(f'\ntrade_date: value={sample["trade_date"]}, type={type(sample["trade_date"]).__name__}')

# Check daily_basic too
print('\n---\n')
sample2 = db['daily_basic'].find_one()
if sample2:
    print('Sample document (daily_basic):')
    for k, v in sample2.items():
        print(f'  {k}: {repr(v)}, type={type(v).__name__}')
    print(f'\ntrade_date: value={sample2["trade_date"]}, type={type(sample2["trade_date"]).__name__}')

client.close()
