#!/usr/bin/env python3
"""
逐个交易日下载 stock_daily 数据，使用 AKShare
"""
import asyncio
import sys
sys.path.insert(0, '.')

import akshare as ak
import pandas as pd
import pymongo
from core.settings import settings

def main():
    # 获取交易日历
    trade_cal = ak.tool_trade_date_hist_sina()
    trade_cal['trade_date'] = pd.to_datetime(trade_cal['trade_date'])
    mask = (trade_cal['trade_date'] >= '2026-01-05') & (trade_cal['trade_date'] <= '2026-03-20')
    trade_dates = trade_cal[mask]['trade_date'].dt.strftime('%Y%m%d').astype(int).tolist()
    
    print(f"需要下载 {len(trade_dates)} 个交易日")
    
    success_count = 0
    fail_count = 0
    
    # 获取 mongo db 客户端
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    
    for i, trade_date in enumerate(trade_dates):
        print(f"[{i+1}/{len(trade_dates)}] 正在下载 {trade_date}...")
        try:
            # AKShare 获取每日行情
            df = ak.stock_zh_a_daily(symbol=str(trade_date), adjust="qfq")
            if df is not None and not df.empty:
                # 标准化列名
                df = df.rename(columns={
                    'code': 'ts_code',
                    'open': 'open',
                    'high': 'high',
                    'low': 'low',
                    'close': 'close',
                    'pre_close': 'pre_close',
                    'volume': 'vol',
                    'amount': 'amount',
                    'pct_chg': 'pct_chg',
                })
                # 添加后缀
                def add_suffix(code: str) -> str:
                    code = str(code).zfill(6)
                    if code.startswith(('6', '5', '9')):
                        return f"{code}.SH"
                    else:
                        return f"{code}.SZ"
                
                df['ts_code'] = df['ts_code'].apply(add_suffix)
                df['trade_date'] = trade_date
                
                records = df.to_dict('records')
                for r in records:
                    r['_id'] = f"{r['ts_code']}_{trade_date}"
                
                # 批量 upsert
                bulk = []
                for r in records:
                    bulk.append({
                        'replaceOne': {
                            'filter': {'_id': r['_id']},
                            'replacement': r,
                            'upsert': True
                        }
                    })
                if bulk:
                    result = db.stock_daily.bulk_write(bulk)
                    inserted = result.upserted_count
                    modified = result.modified_count
                    print(f"  → {len(records)} 条, 插入/更新: {inserted}/{modified}")
                success_count += 1
            else:
                print(f"  ⚠️  无数据")
                fail_count += 1
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            fail_count += 1
    
    print(f"\n===== 下载完成 =====")
    print(f"成功: {success_count}, 失败: {fail_count}")
    
    final_count = db.stock_daily.count_documents({'trade_date': {'$gte': 20260105, '$lte': 20260320}})
    print(f"最终 stock_daily 区间记录数: {final_count}")
    
    client.close()

if __name__ == "__main__":
    main()
