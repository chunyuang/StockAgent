from pathlib import Path
"""
用ARKCLAW stock_basic批量补全stock_basic集合的股票名称
每批50只，写入MongoDB stock_basic
"""
import asyncio
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.managers.mongo_manager import MongoManager

# 从arkclaw stock_basic工具的结果中提取名字
# 这里需要通过openclaw的工具调用，脚本只负责MongoDB写入
# 实际数据通过arkclaw工具分批获取后手动调用本脚本

async def fill_names(name_mapping: dict):
    """name_mapping: {ts_code: short_name}"""
    mm = MongoManager()
    await mm.initialize()
    
    updated = 0
    inserted = 0
    for ts_code, name in name_mapping.items():
        if not name:
            continue
        existing = await mm.db.stock_basic.find_one({"ts_code": ts_code})
        if existing:
            if not existing.get("name") or existing["name"] == ts_code.split(".")[0]:
                await mm.db.stock_basic.update_one(
                    {"ts_code": ts_code},
                    {"$set": {"name": name}}
                )
                updated += 1
        else:
            await mm.db.stock_basic.insert_one({
                "ts_code": ts_code,
                "name": name,
                "is_st": "ST" in name or "st" in name
            })
            inserted += 1
    
    print(f"更新: {updated}, 新增: {inserted}, 总计: {updated+inserted}")
    await mm.shutdown()

if __name__ == "__main__":
    # 示例: python3 arkclaw_fill_stock_names.py
    # 实际数据通过arkclaw工具获取
    asyncio.run(fill_names({}))
