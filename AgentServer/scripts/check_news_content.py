#!/usr/bin/env python
"""
检查新闻的 content 字段是否有内容

用法:
    python scripts/check_news_content.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.managers import mongo_manager


async def check_news_content():
    """检查新闻内容字段"""
    if not mongo_manager.is_initialized:
        await mongo_manager.initialize()
    
    # 获取最近 20 条新闻
    news_list = await mongo_manager.find_many(
        "news",
        {},
        limit=20,
        sort=[("collect_time", -1)],
    )
    
    print(f"\n{'='*70}")
    print(f"检查最近 {len(news_list)} 条新闻的 content 字段")
    print(f"{'='*70}\n")
    
    empty_count = 0
    same_as_title_count = 0
    
    for i, news in enumerate(news_list, 1):
        title = news.get("title", "")
        content = news.get("content", "")
        source = news.get("source", "")
        
        # 检查状态
        if not content:
            status = "❌ 空"
            empty_count += 1
        elif content.strip() == title.strip():
            status = "⚠️ 与标题相同"
            same_as_title_count += 1
        else:
            status = f"✓ 有内容 ({len(content)} 字符)"
        
        print(f"{i:2}. [{source:15}] {status}")
        print(f"    标题: {title[:50]}...")
        if content and content != title:
            print(f"    内容: {content[:80]}...")
        print()
    
    print(f"{'='*70}")
    print("统计:")
    print(f"  - 总数: {len(news_list)}")
    print(f"  - 内容为空: {empty_count}")
    print(f"  - 内容=标题: {same_as_title_count}")
    print(f"  - 有独立内容: {len(news_list) - empty_count - same_as_title_count}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    asyncio.run(check_news_content())
