"""
测试新闻筛选器

验证4步硬规则筛选效果：
1. 极速降噪
2. 重要性打分
3. 同类聚类
4. 截断输出
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from datetime import datetime, timedelta

from core.managers import mongo_manager
from src.report.news_filter import (
    NewsFilter,
    news_filter,
    score_importance,
    is_noise_news,
    get_cluster_key,
)


async def test_filter():
    """测试筛选器"""
    await mongo_manager.initialize()
    
    # 获取最近的事件
    cutoff = datetime.utcnow() - timedelta(hours=24)
    events = await mongo_manager.find_many(
        "news_events",
        {"last_update_time": {"$gte": cutoff}},
        limit=100,
        sort=[("news_count", -1), ("last_update_time", -1)],
    )
    
    print(f"\n{'='*70}")
    print(f"原始事件数量: {len(events)}")
    print(f"{'='*70}\n")
    
    if not events:
        print("没有找到事件，请先运行事件聚类")
        return
    
    # 显示原始事件
    print("原始事件列表 (前20条):")
    print("-" * 70)
    for i, event in enumerate(events[:20], 1):
        title = event.get("title", "")[:50]
        news_count = event.get("news_count", 0)
        print(f"{i:2}. (新闻:{news_count:2}) {title}")
    print()
    
    # 测试降噪
    print(f"\n{'='*70}")
    print("第1步: 降噪测试")
    print(f"{'='*70}\n")
    
    noise_count = 0
    for event in events[:20]:
        is_noise, reason = is_noise_news(event)
        if is_noise:
            noise_count += 1
            print(f"  [过滤] {event.get('title', '')[:40]} - {reason}")
    print(f"\n降噪结果: {len(events[:20])} → {len(events[:20]) - noise_count} (过滤了 {noise_count} 条)")
    
    # 测试打分
    print(f"\n{'='*70}")
    print("第2步: 打分测试")
    print(f"{'='*70}\n")
    
    for event in events[:10]:
        score = score_importance(event)
        title = event.get("title", "")[:40]
        cluster = get_cluster_key(event) or "-"
        print(f"  [{score.importance_tag}] 总分={score.total:2} "
              f"(来源:{score.source_level} 范围:{score.impact_scope} 资金:{score.fund_sensitivity}) "
              f"聚类:{cluster}")
        print(f"      {title}")
    
    # 执行完整筛选
    print(f"\n{'='*70}")
    print("完整4步筛选结果")
    print(f"{'='*70}\n")
    
    filtered = news_filter.filter_events(events, "test")
    
    print(f"\n筛选结果: {len(events)} → {len(filtered)} 条核心事件\n")
    print("-" * 70)
    
    for i, fe in enumerate(filtered, 1):
        print(f"{i}. 【{fe.importance_tag}】{fe.title}")
        print(f"   总分: {fe.score.total} (来源:{fe.score.source_level} 范围:{fe.score.impact_scope} 资金:{fe.score.fund_sensitivity})")
        if fe.sectors:
            print(f"   板块: {', '.join(fe.sectors[:4])}")
        if fe.cluster_key:
            print(f"   聚类: {fe.cluster_key}")
        if fe.merged_events:
            print(f"   合并: {len(fe.merged_events)} 条相关事件")
        print()
    
    # 输出格式化结果
    print(f"\n{'='*70}")
    print("格式化输出 (企业微信格式)")
    print(f"{'='*70}\n")
    
    output = news_filter.format_output(filtered)
    print(output)


if __name__ == "__main__":
    asyncio.run(test_filter())
