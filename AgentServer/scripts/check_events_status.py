#!/usr/bin/env python
"""
检查 news_events 表中事件的状态
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.managers import mongo_manager


async def check_events():
    if not mongo_manager.is_initialized:
        await mongo_manager.initialize()
    
    db = mongo_manager.db
    
    print(f"\n{'='*70}")
    print("news_events 表状态检查")
    print(f"{'='*70}\n")
    
    # 总数
    total = await db["news_events"].count_documents({})
    print(f"总事件数: {total}")
    
    if total == 0:
        print("没有事件，请先运行聚类")
        return
    
    # 各字段状态
    enriched = await db["news_events"].count_documents({"enriched_at": {"$exists": True}})
    not_enriched = await db["news_events"].count_documents({"enriched_at": {"$exists": False}})
    print(f"已增强: {enriched}")
    print(f"未增强: {not_enriched}")
    
    low_value_true = await db["news_events"].count_documents({"is_low_value": True})
    low_value_false = await db["news_events"].count_documents({"is_low_value": False})
    low_value_none = await db["news_events"].count_documents({"is_low_value": {"$exists": False}})
    print(f"\nis_low_value 状态:")
    print(f"  True: {low_value_true}")
    print(f"  False: {low_value_false}")
    print(f"  不存在: {low_value_none}")
    
    # 时间范围
    cutoff = datetime.utcnow() - timedelta(hours=24)
    recent = await db["news_events"].count_documents({"last_update_time": {"$gte": cutoff}})
    print(f"\n最近24小时内: {recent}")
    
    # 可增强的事件（符合查询条件）
    can_enrich = await db["news_events"].count_documents({
        "enriched_at": {"$exists": False},
        "last_update_time": {"$gte": cutoff},
        "$or": [
            {"is_low_value": {"$exists": False}},
            {"is_low_value": False},
        ],
    })
    print(f"可增强事件 (未增强 + 24h内 + 非低价值): {can_enrich}")
    
    # 显示前 5 个事件的详细状态
    print(f"\n{'='*70}")
    print("前 5 个事件详情:")
    print(f"{'='*70}")
    
    events = await mongo_manager.find_many(
        "news_events",
        {},
        limit=5,
        sort=[("last_update_time", -1)],
    )
    
    for i, event in enumerate(events, 1):
        print(f"\n{i}. {event.get('title', '')[:50]}...")
        print(f"   id: {event.get('id', '')}")
        print(f"   enriched_at: {event.get('enriched_at', 'None')}")
        print(f"   is_low_value: {event.get('is_low_value', 'None')}")
        print(f"   last_update_time: {event.get('last_update_time', 'None')}")
        print(f"   primary_news_priority: {event.get('primary_news_priority', 'None')}")
        print(f"   related_sectors: {event.get('related_sectors', [])}")
        print(f"   sentiment: {event.get('sentiment', 'None')}")


if __name__ == "__main__":
    asyncio.run(check_events())
