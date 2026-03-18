"""
修复 MongoDB 索引冲突

解决因索引 unique 属性不一致导致的冲突。
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

# 需要修复的索引
INDEXES_TO_FIX = [
    ("stock_daily", "ts_code_1_trade_date_-1"),
    ("daily_basic", "ts_code_1_trade_date_-1"),
    ("index_daily", "ts_code_1_trade_date_-1"),
    ("moneyflow_industry", "ts_code_1_trade_date_-1"),
    ("moneyflow_concept", "ts_code_1_trade_date_-1"),
    ("limit_list", "ts_code_1_trade_date_-1"),
]


async def fix_indexes():
    # 连接 MongoDB
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client.stock_agent
    
    print("开始修复 MongoDB 索引冲突...\n")
    
    for collection_name, index_name in INDEXES_TO_FIX:
        collection = db[collection_name]
        
        try:
            # 检查索引是否存在
            indexes = await collection.index_information()
            
            if index_name in indexes:
                index_info = indexes[index_name]
                is_unique = index_info.get("unique", False)
                
                if not is_unique:
                    print(f"[{collection_name}] 删除非 unique 索引: {index_name}")
                    await collection.drop_index(index_name)
                    print(f"[{collection_name}] ✓ 索引已删除，将在服务启动时重建为 unique")
                else:
                    print(f"[{collection_name}] ✓ 索引已是 unique，无需修复")
            else:
                print(f"[{collection_name}] - 索引不存在，跳过")
                
        except Exception as e:
            print(f"[{collection_name}] ✗ 错误: {e}")
    
    print("\n修复完成！请重新启动服务。")
    client.close()


if __name__ == "__main__":
    asyncio.run(fix_indexes())
