"""
Agent 基类

实现 ReAct 循环和工具调用的核心逻辑。
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Agent 配置"""
    max_steps: int = 10           # 最大执行步数
    max_tokens: int = 4096        # 单次响应最大 token
    temperature: float = 0.3      # 温度参数
    timeout: float = 120.0        # 超时时间（秒）
    verbose: bool = False         # 是否输出详细日志


@dataclass
class ToolCall:
    """工具调用记录"""
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Any = None
    success: bool = True
    error: Optional[str] = None
    elapsed_ms: float = 0


@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool = False
    content: str = ""
    data: Optional[Dict[str, Any]] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    total_steps: int = 0
    total_tokens: int = 0
    elapsed_ms: float = 0
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "success": self.success,
            "content": self.content,
            "data": self.data,
            "total_steps": self.total_steps,
            "total_tokens": self.total_tokens,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "tool_calls": [
                {
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "success": tc.success,
                }
                for tc in self.tool_calls
            ],
        }


class BaseAgent(ABC):
    """
    Agent 基类
    
    实现 ReAct 循环：
    1. 思考（Thought）- LLM 分析当前状态
    2. 行动（Action）- 调用工具获取信息
    3. 观察（Observation）- 处理工具返回结果
    4. 重复直到得出结论
    
    Example:
        class MyAgent(BaseAgent):
            name = "my_agent"
            description = "My custom agent"
            prompt_template_name = "agent_my_agent"  # 引用 YAML 模板
            
            @property
            def available_tools(self) -> List[str]:
                return ["tool1", "tool2"]
        
        agent = MyAgent(llm_service, tool_registry)
        result = await agent.run("分析股票 000001.SZ")
    """
    
    name: str = "base_agent"
    description: str = "Base agent"
    prompt_template_name: Optional[str] = None  # 引用 config/prompts/*.yaml 中的模板
    
    def __init__(
        self,
        llm_service,
        tool_registry,
        config: AgentConfig = None,
    ):
        self.llm = llm_service
        self.tools = tool_registry
        self.config = config or AgentConfig()
        self.logger = logging.getLogger(f"agent.{self.name}")
    
    @property
    def system_prompt(self) -> str:
        """
        Agent 的系统提示词
        
        优先从 PromptRegistry 加载模板，如果未配置则使用默认提示词。
        子类可以：
        1. 设置 prompt_template_name 引用 YAML 模板
        2. 重写此属性返回硬编码提示词
        """
        if self.prompt_template_name:
            from src.llm.prompts.registry import prompt_registry
            template = prompt_registry.get(self.prompt_template_name)
            if template:
                return template.system_prompt
            else:
                self.logger.warning(
                    f"Template '{self.prompt_template_name}' not found, using default"
                )
        return self._default_system_prompt()
    
    def _default_system_prompt(self) -> str:
        """默认系统提示词，子类可重写"""
        return "You are a helpful assistant."
    
    @property
    @abstractmethod
    def available_tools(self) -> List[str]:
        """Agent 可用的工具名称列表"""
        pass
    
    async def run(
        self,
        task: str,
        context: Dict[str, Any] = None,
    ) -> AgentResult:
        """
        执行 Agent 任务
        
        Args:
            task: 用户任务描述
            context: 上下文信息
            
        Returns:
            AgentResult
        """
        start_time = time.time()
        context = context or {}
        tool_calls_log = []
        total_tokens = 0
        
        # 构建初始消息
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self._build_user_message(task, context)},
        ]
        
        # 获取可用工具的 OpenAI 格式
        tool_decls = self.tools.to_openai_tools(self.available_tools)
        
        self.logger.info(f"Starting agent run: {task[:50]}...")
        
        # ReAct 循环
        for step in range(self.config.max_steps):
            self.logger.info(f"Step {step + 1}/{self.config.max_steps}")
            
            try:
                # 调用 LLM
                response = await self._call_llm(messages, tool_decls)
                total_tokens += response.get("usage", {}).get("total_tokens", 0)
                
                # 检查是否有工具调用
                tool_calls = response.get("tool_calls", [])
                
                if tool_calls:
                    # 处理工具调用
                    for tc in tool_calls:
                        tool_call = await self._execute_tool(tc)
                        tool_calls_log.append(tool_call)
                        
                        # 添加工具调用和结果到消息
                        messages.append({
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                                },
                            }],
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": self._serialize_result(tool_call.result),
                        })
                else:
                    # LLM 返回最终回答
                    content = response.get("content", "")
                    
                    return AgentResult(
                        success=True,
                        content=content,
                        data=self._parse_response(content),
                        tool_calls=tool_calls_log,
                        total_steps=step + 1,
                        total_tokens=total_tokens,
                        elapsed_ms=(time.time() - start_time) * 1000,
                    )
                    
            except Exception as e:
                self.logger.error(f"Step {step + 1} failed: {e}")
                return AgentResult(
                    success=False,
                    error=str(e),
                    tool_calls=tool_calls_log,
                    total_steps=step + 1,
                    total_tokens=total_tokens,
                    elapsed_ms=(time.time() - start_time) * 1000,
                )
        
        # 超过最大步数
        return AgentResult(
            success=False,
            error=f"Exceeded max steps ({self.config.max_steps})",
            content="分析未能在限定步数内完成，请尝试简化任务。",
            tool_calls=tool_calls_log,
            total_steps=self.config.max_steps,
            total_tokens=total_tokens,
            elapsed_ms=(time.time() - start_time) * 1000,
        )
    
    async def _call_llm(
        self,
        messages: List[Dict],
        tools: List[Dict],
    ) -> Dict[str, Any]:
        """
        调用 LLM
        
        Returns:
            {
                "content": str,
                "tool_calls": [{id, name, arguments}],
                "usage": {total_tokens}
            }
        """
        response = await self.llm.chat_with_tools(
            messages=messages,
            tools=tools,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        
        return response
    
    async def _execute_tool(self, tool_call: Dict) -> ToolCall:
        """执行单个工具调用"""
        tc_id = tool_call.get("id", "")
        name = tool_call.get("name", "")
        arguments = tool_call.get("arguments", {})
        
        self.logger.info(f"Calling tool: {name}")
        
        start_time = time.time()
        
        try:
            result = await self.tools.execute(name, **arguments)
            elapsed_ms = (time.time() - start_time) * 1000
            
            return ToolCall(
                id=tc_id,
                name=name,
                arguments=arguments,
                result=result,
                success=True,
                elapsed_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            self.logger.error(f"Tool {name} failed: {e}")
            
            return ToolCall(
                id=tc_id,
                name=name,
                arguments=arguments,
                result={"error": str(e)},
                success=False,
                error=str(e),
                elapsed_ms=elapsed_ms,
            )
    
    def _build_user_message(self, task: str, context: Dict[str, Any]) -> str:
        """构建用户消息"""
        parts = [task]
        
        if context:
            parts.append("\n\n## 上下文信息")
            for key, value in context.items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False, indent=2)
                parts.append(f"\n### {key}\n{value}")
        
        return "\n".join(parts)
    
    def _serialize_result(self, result: Any) -> str:
        """序列化工具结果为字符串"""
        if isinstance(result, str):
            return result
        
        try:
            return json.dumps(result, ensure_ascii=False, default=str, indent=2)
        except Exception:
            return str(result)
    
    def _parse_response(self, content: str) -> Optional[Dict[str, Any]]:
        """
        解析 LLM 响应中的结构化数据
        
        子类可重写此方法来提取 JSON 等结构化内容。
        """
        # 尝试提取 JSON
        try:
            import re
            # 匹配 ```json ... ``` 或 { ... }
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
            if json_match:
                return json.loads(json_match.group(1))
            
            # 尝试直接解析
            if content.strip().startswith("{"):
                return json.loads(content)
        except Exception:
            pass
        
        return None
