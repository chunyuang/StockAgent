"""
Agent 路由器

根据用户任务自动选择合适的 Agent 或 Workflow。
"""

import logging
import re
from typing import Dict, List, Optional, Union

from src.agents.base import BaseAgent, AgentResult
from src.workflows.base import BaseWorkflow, WorkflowResult


logger = logging.getLogger(__name__)


class AgentRouter:
    """
    Agent 路由器
    
    根据任务描述自动选择合适的 Agent 或 Workflow。
    
    支持两种路由方式：
    1. 规则路由 - 基于关键词匹配，速度快
    2. LLM 路由 - 使用 LLM 进行智能选择，更灵活
    
    Example:
        router = AgentRouter(agents, workflows)
        handler = await router.route("深度分析贵州茅台")
        result = await handler.execute({"stock_code": "600519.SH"})
    """
    
    def __init__(
        self,
        agents: Dict[str, BaseAgent],
        workflows: Dict[str, BaseWorkflow],
        llm_service=None,
    ):
        """
        初始化路由器
        
        Args:
            agents: Agent 字典
            workflows: Workflow 字典
            llm_service: LLM 服务（可选，用于智能路由）
        """
        self.agents = agents
        self.workflows = workflows
        self.llm = llm_service
        self.logger = logging.getLogger(f"{__name__}.AgentRouter")
        
        # 路由规则
        self._rules = self._build_rules()
    
    def _build_rules(self) -> List[Dict]:
        """构建路由规则"""
        return [
            # Workflow 路由
            {
                "patterns": ["深度分析", "详细分析", "全面分析", "完整分析"],
                "target_type": "workflow",
                "target_name": "stock_deep_dive",
            },
            # Agent 路由
            {
                "patterns": ["分析股票", "分析个股", "股票分析", "看看.*股票"],
                "target_type": "agent",
                "target_name": "stock_analyzer",
            },
            {
                "patterns": ["生成报告", "写报告", "撰写报告"],
                "target_type": "agent",
                "target_name": "report_writer",
            },
        ]
    
    async def route(self, task: str) -> Union[BaseAgent, BaseWorkflow, None]:
        """
        根据任务路由到合适的 Agent 或 Workflow
        
        Args:
            task: 任务描述
            
        Returns:
            Agent 或 Workflow 实例
        """
        self.logger.info(f"Routing task: {task[:50]}...")
        
        # 规则匹配
        for rule in self._rules:
            for pattern in rule["patterns"]:
                if re.search(pattern, task):
                    target_type = rule["target_type"]
                    target_name = rule["target_name"]
                    
                    self.logger.info(f"Rule matched: {target_type}:{target_name}")
                    
                    if target_type == "workflow":
                        return self.workflows.get(target_name)
                    else:
                        return self.agents.get(target_name)
        
        # 默认使用股票分析 Agent
        self.logger.info("No rule matched, using default: stock_analyzer")
        return self.agents.get("stock_analyzer")
    
    async def route_with_llm(self, task: str) -> Union[BaseAgent, BaseWorkflow, None]:
        """
        使用 LLM 进行智能路由
        
        Args:
            task: 任务描述
            
        Returns:
            Agent 或 Workflow 实例
        """
        if not self.llm:
            return await self.route(task)
        
        # 构建选项描述
        options = {}
        for name, agent in self.agents.items():
            options[f"agent:{name}"] = agent.description
        for name, workflow in self.workflows.items():
            options[f"workflow:{name}"] = workflow.description
        
        options_text = "\n".join([f"- {k}: {v}" for k, v in options.items()])
        
        prompt = f"""根据用户任务选择最合适的处理方式。

用户任务: {task}

可选项:
{options_text}

请只返回选项名称（如 "agent:stock_analyzer" 或 "workflow:stock_deep_dive"），不要其他内容。
"""
        
        try:
            response = await self.llm.chat([{"role": "user", "content": prompt}])
            choice = response.get("content", "").strip()
            
            self.logger.info(f"LLM routing choice: {choice}")
            
            if choice.startswith("agent:"):
                return self.agents.get(choice[6:])
            elif choice.startswith("workflow:"):
                return self.workflows.get(choice[9:])
        except Exception as e:
            self.logger.error(f"LLM routing failed: {e}")
        
        # 降级到规则路由
        return await self.route(task)
    
    async def run(
        self,
        task: str,
        input_data: Dict = None,
        use_llm_routing: bool = False,
    ) -> Union[AgentResult, WorkflowResult]:
        """
        执行任务
        
        自动路由并执行任务。
        
        Args:
            task: 任务描述
            input_data: 输入数据（用于 Workflow）
            use_llm_routing: 是否使用 LLM 路由
            
        Returns:
            执行结果
        """
        # 路由
        if use_llm_routing:
            handler = await self.route_with_llm(task)
        else:
            handler = await self.route(task)
        
        if handler is None:
            return AgentResult(
                success=False,
                error="No suitable agent or workflow found",
            )
        
        # 执行
        if isinstance(handler, BaseWorkflow):
            return await handler.execute(input_data or {})
        else:
            return await handler.run(task, input_data)
    
    def list_available(self) -> Dict[str, List[str]]:
        """列出所有可用的 Agent 和 Workflow"""
        return {
            "agents": [
                {"name": name, "description": agent.description}
                for name, agent in self.agents.items()
            ],
            "workflows": [
                {"name": name, "description": wf.description}
                for name, wf in self.workflows.items()
            ],
        }
