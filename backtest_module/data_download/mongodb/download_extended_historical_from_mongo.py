#!/usr/bin/env python3
"""
从现有 MongoDB stock_daily 导出指定区间数据到 local-databases (独立回测模块)

用于:
- 将已经下载好的数据导出到 local-databases 分级存储
- 方便归档和追溯
"""

import sys
import json
from datetime import datetime
import pymongo


def export_range_to_local(start_date: str, end_date: str, output_dir: str):
    """导出指定区间数据"""
    print(f"=== MongoDB 数据导出: stock_daily → local-databases ===")
    print(f"区间: {start_date} ~ {end_date}")
    print()

    # 连接 MongoDB
    client = pymongo.MongoClient()
    db = client['stock_agent']
    collection = db['stock_daily']

    # 查询指定区间
    query = {
        'trade_date': {
            '$gte': start_date,
            '$lte': end_date
        }
    }

    count = collection.count_documents(query)
    print(f"查询到 {count} 条记录")
    print()

    # 导出
    output_file = f"{output_dir}/stock_daily_{start_date}_{end_date}.jsonl"
    
    exported = 0
    with open(output_file, 'w') as f:
        cursor = collection.find(query)
        for doc in cursor:
            # 移除 _id
            doc.pop('_id', None)
            json.dump(doc, f, ensure_ascii=False)
            f.write('\n')
            exported += 1
            
            if exported % 10000 == 0:
                print(f"已导出 {exported}/{count}")

    print()
    print("="*60)
    print(f"导出完成!")
    print(f"输出文件: {output_file}")
    print(f"导出记录: {exported}")

    client.close()


if __name__ == "__main__":
    start_date = "20251215"
    end_date = datetime.now().strftime("%Y%m%d")
    output_dir = "."

    if len(sys.argv) >= 2:
        start_date = sys.argv[1]
    if len(sys.argv) >= 3:
        end_date = sys.argv[2]
    if len(sys.argv) >= 4:
        output_dir = sys.argv[3]

    export_range_to_local(start_date, end_date, output_dir)
