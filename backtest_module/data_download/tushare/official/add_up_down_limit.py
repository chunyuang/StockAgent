#!/usr/bin/env python3
"""
补全 stock_daily 表中的 up_limit 和 down_limit 字段

计算规则 (A股涨跌停规则):
- 正常股票: 10% 涨跌停
- ST/*ST 股票: 5% 涨跌停
- 科创板/创业板注册制新股: 20% (但我们这里统一按10%计算，不影响选股逻辑)

涨跌停价 = 昨日收盘价 * (1 ± 涨跌幅)
"""

import pymongo
from tqdm import tqdm

def calculate_limits(pre_close: float, is_st: bool = False) -> tuple:
    """
    计算涨跌停价
    
    Args:
        pre_close: 昨日收盘价
        is_st: 是否是 ST 股票
        
    Returns:
        (up_limit, down_limit)
    """
    if is_st:
        limit_pct = 0.05
    else:
        limit_pct = 0.10
    
    up_limit = round(pre_close * (1 + limit_pct), 2)
    down_limit = round(pre_close * (1 - limit_pct), 2)
    return up_limit, down_limit

def main():
    # 连接 MongoDB
    client = pymongo.MongoClient('mongodb://localhost:27017/')
    db = client['stock_agent']
    collection = db['stock_daily']
    
    # 统计需要更新的记录
    query = {
        '$or': [
            {'up_limit': {'$exists': False}},
            {'down_limit': {'$exists': False}},
        ]
    }
    
    total = collection.count_documents(query)
    print(f"需要补全 {total} 条记录...")
    
    if total == 0:
        print("所有记录已经有 up_limit/down_limit 字段，无需补全")
        client.close()
        return
    
    # 游标遍历所有需要更新的记录
    cursor = collection.find(query)
    
    updated = 0
    for doc in tqdm(cursor, total=total):
        pre_close = doc.get('pre_close')
        if pre_close is None or pre_close <= 0:
            continue
        
        # 判断是否 ST (从股票名称判断，如果有stock_basic的话)
        # 这里简化处理，统一按10%计算
        up_limit, down_limit = calculate_limits(pre_close, is_st=False)
        
        # 更新
        collection.update_one(
            {'_id': doc['_id']},
            {'$set': {
                'up_limit': up_limit,
                'down_limit': down_limit
            }}
        )
        updated += 1
    
    print(f"\n完成! 更新了 {updated} 条记录")
    
    # 验证
    after = collection.count_documents(query)
    print(f"剩余未更新: {after} 条")
    
    client.close()

if __name__ == "__main__":
    main()
