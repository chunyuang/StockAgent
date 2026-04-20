#!/usr/bin/env python
"""
配置系统测试脚本

测试 YAML 配置加载和访问功能。

使用方式:
    python scripts/test_config.py
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def main():
    from src.config import config_manager, ConfigValidator, NewsFilterOutputConfig
    
    print("=" * 60)
    print("配置系统测试")
    print("=" * 60)
    
    # 1. 加载配置
    print("\n[1] 加载配置文件...")
    count = config_manager.load()
    print(f"    配置目录: {config_manager.config_dir}")
    print(f"    已加载文件数: {count}")
    print(f"    已加载模块: {config_manager.list_modules()}")
    
    # 2. 测试 news_filter 配置
    print("\n[2] 测试 news_filter 配置...")
    
    noise_keywords = config_manager.get("news_filter.noise_keywords", [])
    print(f"    噪音关键词数量: {len(noise_keywords)}")
    if noise_keywords:
        print(f"    示例关键词: {noise_keywords[:5]}")
    
    source_level = config_manager.get("news_filter.source_level_keywords", {})
    print(f"    来源级别配置: {list(source_level.keys())}")
    
    cluster_pools = config_manager.get("news_filter.cluster_pools", {})
    print(f"    聚类池数量: {len(cluster_pools)}")
    
    output_config = config_manager.get("news_filter.output", {})
    print(f"    输出配置: {output_config}")
    
    # 3. 测试 report 配置
    print("\n[3] 测试 report 配置...")
    
    morning = config_manager.get("report.morning_report", {})
    print(f"    早报配置: {morning}")
    
    push = config_manager.get("report.push", {})
    print(f"    推送配置: {push}")
    
    # 4. 测试 collector 配置
    print("\n[4] 测试 collector 配置...")
    
    general = config_manager.get("collector.general", {})
    print(f"    通用配置: {general}")
    
    dedup = config_manager.get("collector.dedup", {})
    print(f"    去重配置: {dedup}")
    
    # 5. 测试配置验证器
    print("\n[5] 测试配置验证器...")
    
    validator = ConfigValidator(config_manager)
    validated_output = validator.validate("news_filter.output", NewsFilterOutputConfig)
    print("    验证后的输出配置:")
    print(f"      max_events: {validated_output.max_events}")
    print(f"      min_events: {validated_output.min_events}")
    print(f"      importance_threshold: {validated_output.importance_threshold}")
    
    # 6. 测试动态设置
    print("\n[6] 测试动态设置...")
    
    config_manager.set("test.dynamic_key", "dynamic_value")
    value = config_manager.get("test.dynamic_key")
    print(f"    动态设置值: {value}")
    
    # 7. 测试 news_filter 模块集成
    print("\n[7] 测试 news_filter 模块集成...")
    
    from src.report.news_filter import filter_config, NewsFilter
    
    print(f"    噪音关键词数量: {len(filter_config.noise_keywords)}")
    print(f"    来源模式数量: {len(filter_config.noise_source_patterns)}")
    print(f"    聚类池数量: {len(filter_config.cluster_pools)}")
    
    # 测试 NewsFilter 初始化
    news_filter = NewsFilter()
    print(f"    NewsFilter.max_output: {news_filter.max_output}")
    print(f"    NewsFilter.min_score: {news_filter.min_score}")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
