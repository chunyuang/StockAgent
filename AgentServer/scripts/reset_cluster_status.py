#!/usr/bin/env python
"""
重置所有新闻的聚类状态

将所有新闻标记为未聚类，使其可以重新被聚类引擎处理。

Usage:
    python scripts/reset_cluster_status.py [--delete-events]
    
Options:
    --delete-events  同时删除所有聚类事件（news_events 集合）
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.managers import mongo_manager


async def reset_cluster_status(delete_events: bool = False):
    """重置聚类状态"""
    print("=" * 50)
    print("重置新闻聚类状态")
    print("=" * 50)
    
    # 初始化 MongoDB
    if not mongo_manager.is_initialized:
        await mongo_manager.initialize()
    
    # 统计当前状态（新闻存储在 "news" 集合）
    total_news = await mongo_manager.count("news", {})
    clustered_news = await mongo_manager.count("news", {
        "clustered_at": {"$exists": True, "$ne": None}
    })
    total_events = await mongo_manager.count("news_events", {})
    
    print(f"\n当前状态:")
    print(f"  - 总新闻数: {total_news}")
    print(f"  - 已聚类新闻: {clustered_news}")
    print(f"  - 聚类事件数: {total_events}")
    
    if clustered_news == 0 and total_events == 0:
        print("\n没有需要重置的数据")
        return
    
    # 确认操作
    print(f"\n即将执行:")
    print(f"  1. 重置 {clustered_news} 条新闻的聚类状态 (清除 event_id, clustered_at)")
    if delete_events:
        print(f"  2. 删除 {total_events} 个聚类事件")
    
    confirm = input("\n确认执行? (y/N): ").strip().lower()
    if confirm != 'y':
        print("已取消")
        return
    
    # 执行重置
    print("\n执行中...")
    
    # 1. 重置新闻聚类状态（直接使用底层 API，因为 update_many 会自动加 $set）
    result = await mongo_manager.db["news"].update_many(
        {"clustered_at": {"$exists": True}},
        {
            "$unset": {
                "event_id": "",
                "clustered_at": "",
                "is_primary": "",
            }
        }
    )
    print(f"  ✓ 已重置 {result.modified_count} 条新闻的聚类状态")
    
    # 2. 删除聚类事件（可选）
    if delete_events and total_events > 0:
        result = await mongo_manager.db["news_events"].delete_many({})
        print(f"  ✓ 已删除 {result.deleted_count} 个聚类事件")
    
    # 验证结果
    remaining_clustered = await mongo_manager.count("news", {
        "clustered_at": {"$exists": True, "$ne": None}
    })
    remaining_events = await mongo_manager.count("news_events", {})
    
    print(f"\n重置后状态:")
    print(f"  - 已聚类新闻: {remaining_clustered}")
    print(f"  - 聚类事件数: {remaining_events}")
    print("\n完成！新闻将在下次聚类任务时重新处理。")


async def main():
    delete_events = "--delete-events" in sys.argv
    
    if delete_events:
        print("⚠️  警告: 将同时删除所有聚类事件!")
    
    await reset_cluster_status(delete_events)


if __name__ == "__main__":
    asyncio.run(main())
