#!/usr/bin/env python
"""
清空 MongoDB stock_agent 数据库

用法:
    python scripts/clear_database.py
    python scripts/clear_database.py --confirm    # 跳过确认直接执行
    python scripts/clear_database.py --no-auth    # 不使用认证连接
"""

import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from core.settings import settings


async def clear_database(skip_confirm: bool = False, no_auth: bool = False):
    """清空数据库"""
    # 连接配置
    mongo_settings = settings.mongo
    
    if no_auth:
        # 不使用认证
        uri = f"mongodb://{mongo_settings.host}:{mongo_settings.port}"
    elif mongo_settings.username and mongo_settings.password:
        uri = (
            f"mongodb://{mongo_settings.username}:{mongo_settings.password}"
            f"@{mongo_settings.host}:{mongo_settings.port}"
            f"/{mongo_settings.database}?authSource={mongo_settings.auth_source}"
        )
    else:
        uri = f"mongodb://{mongo_settings.host}:{mongo_settings.port}"
    
    database_name = mongo_settings.database
    
    print("=" * 60)
    print("MongoDB 数据库清空工具")
    print("=" * 60)
    print(f"目标数据库: {database_name}")
    print(f"连接地址: {mongo_settings.host}:{mongo_settings.port}")
    print("=" * 60)
    
    # 连接数据库
    client = AsyncIOMotorClient(uri)
    db = client[database_name]
    
    # 获取所有集合
    collections = await db.list_collection_names()
    
    if not collections:
        print("\n数据库为空，无需清理")
        return
    
    print(f"\n找到 {len(collections)} 个集合:")
    for i, col in enumerate(sorted(collections), 1):
        count = await db[col].count_documents({})
        print(f"  {i}. {col}: {count} 条记录")
    
    # 确认
    if not skip_confirm:
        print("\n" + "!" * 60)
        print("警告: 此操作将删除以上所有集合的全部数据!")
        print("!" * 60)
        confirm = input("\n确认要清空数据库吗? 输入 'YES' 确认: ")
        if confirm != "YES":
            print("已取消")
            return
    
    # 执行清空
    print("\n正在清空数据库...")
    
    for col in collections:
        try:
            await db[col].drop()
            print(f"  ✓ 已删除集合: {col}")
        except Exception as e:
            print(f"  ✗ 删除失败 {col}: {e}")
    
    print("\n" + "=" * 60)
    print("数据库已清空!")
    print("=" * 60)
    
    # 关闭连接
    client.close()


def main():
    parser = argparse.ArgumentParser(description="清空 MongoDB stock_agent 数据库")
    parser.add_argument("--confirm", action="store_true", help="跳过确认直接执行")
    parser.add_argument("--no-auth", action="store_true", help="不使用认证连接")
    args = parser.parse_args()
    
    asyncio.run(clear_database(skip_confirm=args.confirm, no_auth=args.no_auth))


if __name__ == "__main__":
    main()
