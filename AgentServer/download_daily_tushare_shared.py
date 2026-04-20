#!/usr/bin/env python3
"""
使用共享 Tushare 节点下载全部日线数据
"""
import sys
sys.path.insert(0, '.')

import pymongo
from core.settings import settings
from core.managers.tushare_manager import tushare_manager
import asyncio

async def main():
    await tushare_manager.initialize()
    
    # 获取交易日历
    trade_dates = await tushare_manager.get_trade_cal(start_date="20260105", end_date="20260320")
    trade_dates = [int(d) for d in trade_dates]
    
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
            # Tushare pro daily 接口支持按 trade_date 查询
            records = await tushare_manager.get_daily(trade_date=str(trade_date))
            
            if not records:
                print("  ⚠️  无数据")
                fail_count += 1
                continue
            
            print(f"  获取到 {len(records)} 只股票")
            
            # 批量写入
            bulk = []
            for r in records:
                r['_id'] = f"{r['ts_code']}_{trade_date}"
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
        
        # 限流，共享节点配额有限
        await asyncio.sleep(2)
    
    print("\n===== 下载完成 =====")
    print(f"交易日 成功: {success_count}, 失败: {fail_count}")
    print(f"总计记录: {total_records}")
    
    final_count = db.stock_daily_ak_full.count_documents({'trade_date': {'$gte': 20260105, '$lte': 20260320}})
    print(f"最终 stock_daily_ak_full 区间 (20260105-20260320) 记录数: {final_count}")
    
    client.close()
    await tushare_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
