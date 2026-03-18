"""
工具基类

提供工具的通用接口和结果封装。
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool = True
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        result = {
            "success": self.success,
        }
        if self.success:
            result["data"] = self.data
        else:
            result["error"] = self.error
        if self.metadata:
            result["metadata"] = self.metadata
        return result
    
    def to_string(self) -> str:
        """转换为字符串（用于 LLM 消息）"""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


class BaseTool(ABC):
    """
    工具基类（面向对象风格）
    
    如果工具逻辑复杂，可以继承此类实现。
    简单工具建议使用 @tool 装饰器。
    
    Example:
        class StockQuoteTool(BaseTool):
            name = "get_realtime_quote"
            description = "获取股票实时行情"
            category = "data"
            
            def get_parameters(self):
                return [
                    ToolParameter(name="stock_code", type="string", description="股票代码"),
                ]
            
            async def execute(self, stock_code: str) -> ToolResult:
                # 实现逻辑
                return ToolResult(success=True, data={...})
    """
    
    name: str = "base_tool"
    description: str = "Base tool"
    category: str = "data"
    tags: List[str] = []
    
    def __init__(self):
        self.logger = logging.getLogger(f"tool.{self.name}")
    
    @abstractmethod
    def get_parameters(self) -> List["ToolParameter"]:
        """返回参数定义列表"""
        pass
    
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        pass
    
    def to_tool_definition(self) -> "ToolDefinition":
        """转换为 ToolDefinition"""
        from .registry import ToolDefinition
        
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.get_parameters(),
            handler=self.execute,
            category=self.category,
            tags=self.tags,
        )
    
    def register(self, registry: "ToolRegistry" = None) -> None:
        """注册到工具注册中心"""
        from .registry import tool_registry
        
        if registry is None:
            registry = tool_registry
        
        registry.register(self.to_tool_definition())


class ToolError(Exception):
    """工具执行错误"""
    
    def __init__(self, message: str, code: str = None, details: Dict[str, Any] = None):
        super().__init__(message)
        self.message = message
        self.code = code or "TOOL_ERROR"
        self.details = details or {}
    
    def to_result(self) -> ToolResult:
        """转换为 ToolResult"""
        return ToolResult(
            success=False,
            error=self.message,
            metadata={
                "code": self.code,
                **self.details,
            },
        )
