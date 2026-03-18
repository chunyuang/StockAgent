"""检查报告状态"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
from core.managers import mongo_manager


async def check():
    await mongo_manager.initialize()
    reports = await mongo_manager.find_many(
        "reports", {}, sort=[("created_at", -1)], limit=5
    )
    
    if not reports:
        print("No reports found")
        return
    
    for r in reports:
        print(f"ID: {r.get('_id')}")
        print(f"  Created: {r.get('created_at')}")
        print(f"  Pushed: {r.get('pushed')}")
        print(f"  pushed_wechat_at: {r.get('pushed_wechat_at')}")
        print(f"  Content WeChat Length: {len(r.get('content_wechat', ''))}")
        wechat_content = r.get('content_wechat', '')
        if wechat_content:
            preview = wechat_content[:100].encode('utf-8', errors='replace').decode('utf-8')
            print(f"  Content Preview: {preview}...")
        print()


if __name__ == "__main__":
    asyncio.run(check())
