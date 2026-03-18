"""
采集源基类
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from datetime import datetime

import httpx

from ..types import (
    NewsItem,
    NewsSource,
    NewsCategory,
    SourcePriority,
    PolicyLevel,
    get_source_priority,
)


class BaseSource(ABC):
    """
    采集源基类
    
    所有采集源继承此类，实现 fetch() 方法。
    
    Example:
        class MySource(BaseSource):
            name = NewsSource.OTHER
            display_name = "我的来源"
            priority = SourcePriority.P4_GENERAL_MEDIA  # 可选，设置优先级
            
            async def fetch(self, since: datetime = None) -> List[NewsItem]:
                # 抓取逻辑
                ...
    """
    
    name: NewsSource = NewsSource.OTHER
    display_name: str = "未知来源"
    default_category: NewsCategory = NewsCategory.GENERAL
    
    # 新增: 源优先级配置 (子类可覆盖)
    priority: Optional[SourcePriority] = None  # None 时从 SOURCE_PRIORITY_MAP 自动获取
    policy_level: Optional[PolicyLevel] = None  # 政策类源设置
    
    def __init__(self):
        self.logger = logging.getLogger(f"src.collector.sources.{self.name.value}")
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
        )
    
    @abstractmethod
    async def fetch(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
        trace_id: Optional[str] = None,
    ) -> List[NewsItem]:
        """
        抓取新闻
        
        Args:
            since: 只抓取该时间之后的新闻
            limit: 最多抓取数量
            trace_id: 追踪ID
            
        Returns:
            新闻项列表
        """
        raise NotImplementedError
    
    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()
    
    def create_news_item(
        self,
        title: str,
        content: str = "",
        url: str = "",
        publish_time: Optional[datetime] = None,
        category: Optional[NewsCategory] = None,
        source_id: str = "",
        extra: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> NewsItem:
        """
        创建新闻项的便捷方法
        
        自动填充:
        - source_priority: 来源优先级 (从类属性或映射表获取)
        - source_unique_key: 快速去重键 (source:source_id)
        - policy_level: 政策级别 (如果是政策类源)
        """
        # 计算源优先级
        if self.priority is not None:
            priority_value = self.priority.value
        else:
            priority_value = get_source_priority(self.name)
        
        # 生成快速去重键
        unique_key = f"{self.name.value}:{source_id}" if source_id else ""
        
        return NewsItem(
            title=title,
            content=content,
            url=url,
            source=self.name,
            category=category or self.default_category,
            publish_time=publish_time,
            source_id=source_id,
            extra=extra or {},
            # 新增字段
            source_priority=priority_value,
            source_unique_key=unique_key,
            policy_level=self.policy_level,
            **kwargs,
        )
    
    async def fetch_page(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[httpx.Response]:
        """
        抓取页面的便捷方法
        """
        try:
            resp = await self.client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp
        except Exception as e:
            self.logger.error(f"Fetch page error: {url} - {e}")
            return None
    
    async def fetch_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        抓取 JSON 的便捷方法
        """
        resp = await self.fetch_page(url, params, headers)
        if resp:
            try:
                return resp.json()
            except Exception:
                pass
        return None
