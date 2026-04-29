"""
复盘报告推送器

将复盘报告推送到各个渠道。
"""

import logging
from typing import Any, Dict, Optional, Union
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_database
from core.managers import notification_manager
from src.config import config_manager
from src.workflows.graph.state import ReviewState
from .formatter import ReviewReportFormatter


logger = logging.getLogger(__name__)


# 类型别名：支持 ReviewState（LangGraph）或普通 dict
WorkflowResult = Union[ReviewState, Dict[str, Any]]


class ReviewReportPusher:
    """
    复盘报告推送器
    
    支持渠道：
    - 企业微信（复用 notification_manager）
    - MongoDB 存储
    
    Example:
        pusher = ReviewReportPusher()
        await pusher.push_review_report(workflow_result)
    """
    
    def __init__(self, db: Optional[AsyncIOMotorDatabase] = None):
        self.db = db
        self.formatter = ReviewReportFormatter()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # 从配置读取推送设置
        report_config = config_manager.get("review.report", {})
        self.push_channels = report_config.get("push_channels", {})
    
    async def _get_db(self) -> AsyncIOMotorDatabase:
        """获取数据库连接"""
        if self.db is None:
            self.db = await get_database()
        return self.db
    
    async def push_review_report(
        self,
        result: WorkflowResult,
        channels: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        推送复盘报告
        
        Args:
            result: 工作流执行结果（ReviewState 或 dict）
            channels: 推送渠道列表，默认全部
        
        Returns:
            推送结果
        """
        state = result if isinstance(result, dict) else dict(result)
        trade_date = state.get("trade_date", "")
        self.logger.info(f"Pushing review report for {trade_date}")
        
        push_result = {
            "trade_date": trade_date,
            "channels": {},
            "success": True,
        }
        
        channels = channels or ["wechat", "mongodb"]
        
        # 1. 保存到 MongoDB
        if "mongodb" in channels:
            try:
                await self._save_to_mongodb(result)
                push_result["channels"]["mongodb"] = {"success": True}
            except Exception as e:
                self.logger.error(f"Failed to save to MongoDB: {e}")
                push_result["channels"]["mongodb"] = {"success": False, "error": str(e)}
                push_result["success"] = False
        
        # 2. 推送到企业微信
        if "wechat" in channels:
            wechat_config = self.push_channels.get("wechat", {})
            if wechat_config.get("enabled", False):
                try:
                    await self._push_to_wechat(result)
                    push_result["channels"]["wechat"] = {"success": True}
                except Exception as e:
                    self.logger.error(f"Failed to push to WeChat: {e}")
                    push_result["channels"]["wechat"] = {"success": False, "error": str(e)}
                    push_result["success"] = False
        
        return push_result
    
    async def _save_to_mongodb(self, result: WorkflowResult) -> str:
        """
        保存报告到 MongoDB
        
        Returns:
            报告ID
        """
        db = await self._get_db()
        
        state = result if isinstance(result, dict) else dict(result)
        trade_date = state.get("trade_date", "")
        
        # 生成各格式内容
        markdown_content = self.formatter.to_markdown(result)
        wechat_content = self.formatter.to_wechat(result)
        
        # 检查是否有错误
        errors = state.get("errors", [])
        workflow_success = len(errors) == 0
        
        doc = {
            "trade_date": trade_date,
            "type": "review",
            "markdown": markdown_content,
            "wechat": wechat_content,
            "workflow_success": workflow_success,
            "errors": errors,
            "analysis_results": {
                "market": state.get("market_result"),
                "sector": state.get("sector_result"),
                "limit": state.get("limit_result"),
                "linkage": state.get("linkage_result"),
                "sentiment": state.get("sentiment_result"),
            },
            "report": state.get("report"),
            "created_at": datetime.now(timezone.utc),
        }
        
        # Upsert
        await db["review_reports"].update_one(
            {"trade_date": trade_date},
            {"$set": doc},
            upsert=True,
        )
        
        # 创建索引
        await db["review_reports"].create_index("trade_date", unique=True)
        await db["review_reports"].create_index("created_at")
        
        self.logger.info(f"Saved review report to MongoDB: {trade_date}")
        
        return trade_date
    
    async def _push_to_wechat(self, result: WorkflowResult) -> bool:
        """
        推送到企业微信
        
        Returns:
            是否成功
        """
        wechat_content = self.formatter.to_wechat(result)
        
        # 复用现有的 notification_manager.send_markdown
        success = await notification_manager.send_markdown(content=wechat_content)
        
        if success:
            self.logger.info("Pushed review report to WeChat")
        else:
            self.logger.error("Failed to push review report to WeChat")
        
        return success
    
    async def get_report(self, trade_date: str) -> Optional[Dict[str, Any]]:
        """
        获取已保存的报告
        
        Args:
            trade_date: 交易日期
        
        Returns:
            报告数据
        """
        db = await self._get_db()
        
        report = await db["review_reports"].find_one({"trade_date": trade_date})
        
        if report:
            report["_id"] = str(report["_id"])
        
        return report
    
    async def get_recent_reports(self, limit: int = 10) -> list:
        """
        获取最近的报告列表
        
        Args:
            limit: 返回数量
        
        Returns:
            报告列表
        """
        db = await self._get_db()
        
        cursor = db["review_reports"].find(
            {},
            {"trade_date": 1, "created_at": 1, "workflow_success": 1}
        ).sort("trade_date", -1).limit(limit)
        
        reports = await cursor.to_list(limit)
        
        for r in reports:
            r["_id"] = str(r["_id"])
        
        return reports
