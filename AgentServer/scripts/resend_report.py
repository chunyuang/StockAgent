"""重新推送报告到企业微信"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from datetime import datetime
from core.managers import mongo_manager, notification_manager


async def resend_report(report_id: str):
    await mongo_manager.initialize()
    await notification_manager.initialize()
    
    # 获取报告
    report = await mongo_manager.find_one("reports", {"_id": report_id})
    
    if not report:
        print(f"Report not found: {report_id}")
        return
    
    print(f"Found report: {report_id}")
    print(f"  Created: {report.get('created_at')}")
    print(f"  Current pushed status: {report.get('pushed')}")
    
    content_wechat = report.get("content_wechat", "")
    if not content_wechat:
        print("No WeChat content in report!")
        return
    
    print(f"  Content length: {len(content_wechat)}")
    print(f"\nSending to WeChat...")
    
    # 推送
    success = await notification_manager.send_markdown(
        content=content_wechat,
        mentioned_list=["@all"],
    )
    
    if success:
        # 更新推送状态
        await mongo_manager.update_one(
            "reports",
            {"_id": report_id},
            {"$set": {"pushed.wechat": True, "pushed_wechat_at": datetime.utcnow()}}
        )
        print(f"Success! Report pushed to WeChat.")
    else:
        print(f"Failed to push report.")


if __name__ == "__main__":
    report_id = sys.argv[1] if len(sys.argv) > 1 else "morning_20260311"
    print(f"Resending report: {report_id}")
    asyncio.run(resend_report(report_id))
