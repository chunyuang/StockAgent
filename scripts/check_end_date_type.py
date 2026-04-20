#!/usr/bin/env python3
import pymongo
import sys

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')
from core.settings import settings

client = pymongo.MongoClient(settings.mongo.url)
db = client[settings.mongo.database]

sample = db['fina_indicator'].find_one()
if sample:
    print('Sample document (fina_indicator):')
    for k, v in sample.items():
        print(f'  {k}: {repr(v)}, type={type(v).__name__}')
    if 'end_date' in sample:
        print(f'\nend_date: value={sample["end_date"]}, type={type(sample["end_date"]).__name__}')

client.close()
