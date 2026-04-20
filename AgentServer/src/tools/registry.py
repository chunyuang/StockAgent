"""
工具注册中心

管理所有可用工具的注册、查询和执行。
支持 OpenAI Function Calling 格式转换。
"""

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union, get_type_hints

logger = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    """工具参数定义"""
    name: str
    type: str  # string | number | integer | boolean | array | object
    description: str
    required: bool = True
    enum: Optional[List[str]] = None
    default: Any = None
    
    def to_json_schema(self) -> dict:
        """转换为 JSON Schema 格式"""
        schema = {
            "type": self.type,
            "description": self.description,
        }
        if self.enum:
            schema["enum"] = self.enum
        if self.default is not None:
            schema["default"] = self.default
        return schema


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: List[ToolParameter]
    handler: Callable
    category: str = "data"  # data | search | analysis | action
    tags: List[str] = field(default_factory=list)
    
    def to_openai_tool(self) -> dict:
        """转换为 OpenAI Function Calling 格式"""
        properties = {}
        required = []
        
        for p in self.parameters:
            properties[p.name] = p.to_json_schema()
            if p.required:
                required.append(p.name)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
    
    def to_anthropic_tool(self) -> dict:
        """转换为 Anthropic Tool 格式"""
        properties = {}
        required = []
        
        for p in self.parameters:
            properties[p.name] = p.to_json_schema()
            if p.required:
                required.append(p.name)
        
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


class ToolRegistry:
    """
    工具注册中心
    
    负责管理所有工具的注册、查询和执行。
    
    Example:
        registry = ToolRegistry()
        
        # 注册工具
        registry.register(my_tool)
        
        # 获取工具列表
        tools = registry.to_openai_tools(["get_quote", "search_news"])
        
        # 执行工具
        result = await registry.execute("get_quote", stock_code="000001.SZ")
    """
    
    _instance: Optional["ToolRegistry"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools: Dict[str, ToolDefinition] = {}
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._tools: Dict[str, ToolDefinition] = {}
            self._initialized = True
    
    def register(self, tool: ToolDefinition) -> None:
        """注册工具"""
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name} ({tool.category})")
    
    def unregister(self, name: str) -> bool:
        """注销工具"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False
    
    def get(self, name: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        return self._tools.get(name)
    
    def get_or_raise(self, name: str) -> ToolDefinition:
        """获取工具定义，不存在则抛出异常"""
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"Tool not found: {name}")
        return tool
    
    def list_all(self) -> List[str]:
        """列出所有工具名称"""
        return list(self._tools.keys())
    
    def list_by_category(self, category: str) -> List[ToolDefinition]:
        """按分类列出工具"""
        return [t for t in self._tools.values() if t.category == category]
    
    def list_by_tag(self, tag: str) -> List[ToolDefinition]:
        """按标签列出工具"""
        return [t for t in self._tools.values() if tag in t.tags]
    
    def to_openai_tools(self, names: List[str] = None) -> List[dict]:
        """转换为 OpenAI Function Calling 格式"""
        if names is None:
            tools = self._tools.values()
        else:
            tools = [self._tools[n] for n in names if n in self._tools]
        return [t.to_openai_tool() for t in tools]
    
    def to_anthropic_tools(self, names: List[str] = None) -> List[dict]:
        """转换为 Anthropic Tool 格式"""
        if names is None:
            tools = self._tools.values()
        else:
            tools = [self._tools[n] for n in names if n in self._tools]
        return [t.to_anthropic_tool() for t in tools]
    
    async def execute(self, name: str, **kwargs) -> Any:
        """
        执行工具
        
        Args:
            name: 工具名称
            **kwargs: 工具参数
            
        Returns:
            工具执行结果
        """
        tool = self.get(name)
        if not tool:
            raise KeyError(f"Tool '{name}' not found")
        
        logger.debug(f"Executing tool: {name} with args: {list(kwargs.keys())}")
        
        # 检查是否为异步函数
        if asyncio.iscoroutinefunction(tool.handler):
            result = await tool.handler(**kwargs)
        else:
            result = tool.handler(**kwargs)
        
        return result
    
    def get_stats(self) -> Dict[str, Any]:
        """获取注册统计"""
        categories = {}
        for tool in self._tools.values():
            categories[tool.category] = categories.get(tool.category, 0) + 1
        
        return {
            "total": len(self._tools),
            "categories": categories,
        }


# Python 类型到 JSON Schema 类型的映射
_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    List: "array",
    Dict: "object",
}


def _infer_type(annotation) -> str:
    """从 Python 类型注解推断 JSON Schema 类型"""
    if annotation is inspect.Parameter.empty:
        return "string"
    
    # 处理 Optional 类型
    origin = getattr(annotation, "__origin__", None)
    if origin is Union:
        args = annotation.__args__
        # Optional[X] 等价于 Union[X, None]
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _infer_type(non_none[0])
    
    return _TYPE_MAP.get(annotation, "string")


def tool(
    name: str = None,
    description: str = None,
    category: str = "data",
    tags: List[str] = None,
):
    """
    工具注册装饰器
    
    自动从函数签名推断参数定义。
    
    Example:
        @tool(name="get_quote", description="获取实时行情", category="data")
        async def get_realtime_quote(stock_code: str, market: str = "CN") -> dict:
            '''
            获取股票实时行情
            
            Args:
                stock_code: 股票代码
                market: 市场代码 (CN/HK/US)
            '''
            ...
    """
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        tool_desc = description or (func.__doc__ or "").split("\n")[0].strip()
        
        # 解析函数签名
        sig = inspect.signature(func)
        hints = get_type_hints(func) if hasattr(func, "__annotations__") else {}
        
        # 解析参数
        parameters = []
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            
            # 推断类型
            param_type = _infer_type(hints.get(param_name, param.annotation))
            
            # 从 docstring 获取描述
            param_desc = f"参数 {param_name}"
            if func.__doc__:
                # 简单解析 Args 部分
                import re
                pattern = rf"{param_name}:\s*(.+?)(?:\n|$)"
                match = re.search(pattern, func.__doc__)
                if match:
                    param_desc = match.group(1).strip()
            
            # 是否必需
            is_required = param.default is inspect.Parameter.empty
            default_value = None if is_required else param.default
            
            parameters.append(ToolParameter(
                name=param_name,
                type=param_type,
                description=param_desc,
                required=is_required,
                default=default_value,
            ))
        
        # 创建工具定义
        tool_def = ToolDefinition(
            name=tool_name,
            description=tool_desc,
            parameters=parameters,
            handler=func,
            category=category,
            tags=tags or [],
        )
        
        # 注册到全局注册中心
        tool_registry.register(tool_def)
        
        # 保存工具定义到函数属性
        func._tool_definition = tool_def
        
        return func
    
    return decorator


# 全局单例
tool_registry = ToolRegistry()
