#!/usr/bin/env python3
"""
单日全部股票下载，使用 AKShare stock_zh_a_spot，修正列名
"""
import sys
sys.path.insert(0, '.')

import akshare as ak
import pandas as pd
import pymongo
import time
from core.settings import settings

def main():
    # 获取交易日历
    print("正在获取交易日历...")
    trade_cal = ak.tool_trade_date_hist_sina()
    trade_cal['trade_date'] = pd.to_datetime(trade_cal['trade_date'])
    mask = (trade_cal['trade_date'] >= '2026-01-05') & (trade_cal['trade_date'] <= '2026-03-20')
    trade_dates = trade_cal[mask]['trade_date'].dt.strftime('%Y%m%d').astype(int).tolist()
    
    print(f"需要下载 {len(trade_dates)} 个交易日")
    
    success_count = 0
    fail_count = 0
    total_records = 0
    
    # mongo 连接
    client = pymongo.MongoClient(settings.mongo.url)
    db = client[settings.mongo.database]
    
    for trade_date in trade_dates:
        print(f"正在下载 {trade_date}...")
        try:
            # AKShare 获取当日全部A股行情
            df = ak.stock_zh_a_spot()
            if df is None or df.empty:
                print("  ⚠️  无数据")
                fail_count += 1
                continue
            
            print(f"  获取到 {len(df)} 只股票")
            
            # AKShare 最新列名: 代码,名称,最新,涨跌,涨跌幅,今开,最高,最低,昨收,成交量,成交额
            df = df.rename(columns={
                '代码': 'code',
                '名称': 'name',
                '最新': 'close',
                '今开': 'open',
                '最高': 'high',
                '最低': 'low',
                '昨收': 'pre_close',
                '涨跌幅': 'pct_chg',
                '成交量': 'vol',
                '成交额': 'amount',
            })
            
            # 添加 ts_code 后缀
            def add_suffix(code: str) -> str:
                code = str(code).zfill(6)
                if code.startswith(('6', '5', '9')):
                    return f"{code}.SH"
                else:
                    return f"{code}.SZ"
            
            df['ts_code'] = df['code'].apply(add_suffix)
            
            records = []
            for _, r in df.iterrows():
                record = {
                    '_id': f"{r['ts_code']}_{trade_date}",
                    'ts_code': r['ts_code'],
                    'trade_date': trade_date,
                    'open': float(r['open']),
                    'high': float(r['high']),
                    'low': float(r['low']),
                    'close': float(r['close']),
                    'pre_close': float(r['pre_close']),
                    'vol': float(r['vol']) * 100,  # 手 → 股
                    'amount': float(r['amount']),
                    'pct_chg': float(r['pct_chg']),
                }
                records.append(record)
            
            # 批量写入
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
                result = db.stock_daily_ak_full.bulk_write(bulk)
                inserted = result.upserted_count
                modified = result.modified_count
                total_records += len(records)
                print(f"  → {len(records)} 条, 插入/更新: {inserted}/{modified}")
            success_count += 1
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ❌ 错误: {e}")
            fail_count += 1
        
        # 限流，避免被封
        time.sleep(8)
    
    print("\n===== 下载完成 =====")
    print(f"交易日 成功: {success_count}, 失败: {fail_count}")
    print(f"总计记录: {total_records}")
    
    final_count = db.stock_daily_ak_full.count_documents({'trade_date': {'$gte': 20260105, '$lte': 20260320}})
    print(f"最终 stock_daily_ak_full 区间 (20260105-20260320) 记录数: {final_count}")
    
    client.close()

if __name__ == "__main__":
    main()
