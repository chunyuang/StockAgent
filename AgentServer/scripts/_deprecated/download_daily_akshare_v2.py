#!/usr/bin/env python3
"""
逐个股票下载 stock_daily_ak_full 数据，使用 AKShare，下载指定区间
区间: 2026-01-05 至 2026-03-20
"""
import sys
sys.path.insert(0, '.')

import akshare as ak
import pandas as pd
import pymongo
from core.settings import settings
from tqdm import tqdm

def main():
    start_date = "20260105"
    end_date = "20260320"
    
    # 获取全部股票列表
    print("正在获取股票列表...")
    stock_info = ak.stock_info_a_code_name()
    print(f"共 {len(stock_info)} 只股票需要下载")
    
    # 获取 mongo db 客户端
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    
    success_count = 0
    fail_count = 0
    total_records = 0
    
    for idx, row in tqdm(stock_info.iterrows(), total=len(stock_info), desc="下载进度"):
        code = str(row['code']).zfill(6)
        name = row['name']
        
        # 转换 AKShare 需要的格式: sh600000 / sz000001
        if code.startswith(('6', '5', '9')):
            symbol = f"sh{code}"
        else:
            symbol = f"sz{code}"
        
        try:
            # AKShare 获取每日行情
            df = ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"
            )
            
            if df is not None and not df.empty:
                # 标准化列名
                df = df.rename(columns={
                    'date': 'trade_date',
                    'open': 'open',
                    'high': 'high',
                    'low': 'low',
                    'close': 'close',
                    'pre_close': 'pre_close',
                    'volume': 'vol',
                    'amount': 'amount',
                    'pct_chg': 'pct_chg',
                })
                
                # 添加 ts_code 标准格式: 600000.SH
                if symbol.startswith('sh'):
                    ts_code = f"{code}.SH"
                else:
                    ts_code = f"{code}.SZ"
                
                df['ts_code'] = ts_code
                
                # 处理 trade_date 格式
                if df['trade_date'].dtype == object:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d').astype(int)
                
                records = df.to_dict('records')
                bulk = []
                for r in records:
                    r['_id'] = f"{r['ts_code']}_{r['trade_date']}"
                    bulk.append({
                        'replaceOne': {
                            'filter': {'_id': r['_id']},
                            'replacement': r,
                            'upsert': True
                        }
                    })
                
                if bulk:
                    result = db.stock_daily_ak_full.bulk_write(bulk)
                    total_records += len(bulk)
                    # tqdm.write(f"{symbol} {name}: {len(bulk)} 条, +{inserted} 新增")
                    success_count += 1
            else:
                # tqdm.write(f"{symbol} {name}: 无数据")
                fail_count += 1
                
        except Exception as e:
            tqdm.write(f"❌ {symbol} {name} 错误: {str(e)[:100]}")
            fail_count += 1
            continue
    
    print("\n" + "="*50)
    print("下载完成!")
    print(f"成功: {success_count} 只")
    print(f"失败: {fail_count} 只")
    print(f"总记录数: {total_records}")
    
    final_count = db.stock_daily_ak_full.count_documents({'trade_date': {'$gte': int(start_date), '$lte': int(end_date)}})
    print(f"区间 {start_date} - {end_date} 总记录数: {final_count}")
    
    client.close()

if __name__ == "__main__":
    main()
