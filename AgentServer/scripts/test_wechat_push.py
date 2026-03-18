"""
测试企业微信推送

用法:
    cd AgentServer
    
    # 发送最新报告
    python scripts/test_wechat_push.py
    
    # 发送指定报告
    python scripts/test_wechat_push.py --id morning_2026-03-12
    
    # 仅预览不发送
    python scripts/test_wechat_push.py --dry-run
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import argparse
from core.managers import mongo_manager, notification_manager


async def get_latest_report():
    """获取最新报告"""
    if not mongo_manager.is_initialized:
        await mongo_manager.initialize()
    
    doc = await mongo_manager.find_one(
        "reports",
        {},
        sort=[("created_at", -1)],
    )
    return doc


async def get_report_by_id(report_id: str):
    """根据ID获取报告"""
    if not mongo_manager.is_initialized:
        await mongo_manager.initialize()
    
    doc = await mongo_manager.find_one("reports", {"_id": report_id})
    return doc


async def send_report(report_id: str = None, dry_run: bool = False):
    """发送报告到企业微信"""
    
    # 获取报告
    if report_id:
        print(f"获取报告: {report_id}")
        report = await get_report_by_id(report_id)
    else:
        print("获取最新报告...")
        report = await get_latest_report()
    
    if not report:
        print("❌ 未找到报告")
        return False
    
    print(f"✓ 找到报告: {report.get('_id')}")
    print(f"  标题: {report.get('title')}")
    print(f"  日期: {report.get('date')}")
    print(f"  类型: {report.get('type')}")
    
    # 获取微信格式内容
    content = report.get("content_wechat", "")
    
    if not content:
        print("❌ 报告没有企业微信格式内容 (content_wechat)")
        return False
    
    print(f"\n{'='*60}")
    print("企业微信内容预览:")
    print(f"{'='*60}")
    print(content[:1000])
    if len(content) > 1000:
        print(f"\n... (共 {len(content)} 字符)")
    print(f"{'='*60}\n")
    
    if dry_run:
        print("🔸 [dry-run] 仅预览，未实际发送")
        return True
    
    # 发送
    await notification_manager.initialize()
    
    if not notification_manager._config.is_configured:
        print("❌ 企业微信 Webhook 未配置")
        return False
    
    print("发送中...")
    success = await notification_manager.send_markdown(content=content)
    
    if success:
        print("✓ 发送成功")
    else:
        print("❌ 发送失败")
    
    return success


def main():
    parser = argparse.ArgumentParser(description="发送报告到企业微信")
    parser.add_argument("--id", type=str, help="报告ID (如 morning_2026-03-12)")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不发送")
    args = parser.parse_args()
    
    asyncio.run(send_report(report_id=args.id, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
