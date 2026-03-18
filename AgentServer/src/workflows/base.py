"""
工作流基类

定义工作流的基本结构和执行逻辑。
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.agents.base import BaseAgent, AgentResult


@dataclass
class WorkflowStep:
    """工作流步骤记录"""
    name: str
    agent_name: str
    status: str = "pending"  # pending | running | success | failed
    result: Optional[AgentResult] = None
    elapsed_ms: float = 0
    error: Optional[str] = None


@dataclass
class WorkflowResult:
    """工作流执行结果"""
    success: bool = False
    data: Dict[str, Any] = field(default_factory=dict)
    steps: List[WorkflowStep] = field(default_factory=list)
    total_steps: int = 0
    elapsed_ms: float = 0
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "success": self.success,
            "data": self.data,
            "total_steps": self.total_steps,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "steps": [
                {
                    "name": s.name,
                    "agent": s.agent_name,
                    "status": s.status,
                    "elapsed_ms": s.elapsed_ms,
                }
                for s in self.steps
            ],
        }


class BaseWorkflow(ABC):
    """
    工作流基类
    
    工作流用于编排复杂的多步骤任务，可以：
    - 顺序执行多个 Agent
    - 传递中间结果
    - 处理错误和回退
    
    Example:
        class MyWorkflow(BaseWorkflow):
            name = "my_workflow"
            
            async def execute(self, input_data):
                # Step 1
                result1 = await self.agents["agent1"].run(task1)
                
                # Step 2: 使用 Step 1 的结果
                result2 = await self.agents["agent2"].run(
                    task2,
                    context={"step1": result1.data}
                )
                
                return WorkflowResult(...)
    """
    
    name: str = "base_workflow"
    description: str = "Base workflow"
    
    def __init__(self, agents: Dict[str, BaseAgent]):
        """
        初始化工作流
        
        Args:
            agents: Agent 字典 {name: agent_instance}
        """
        self.agents = agents
        self.logger = logging.getLogger(f"workflow.{self.name}")
    
    @abstractmethod
    async def execute(self, input_data: Dict[str, Any]) -> WorkflowResult:
        """
        执行工作流
        
        Args:
            input_data: 输入数据
            
        Returns:
            WorkflowResult
        """
        pass
    
    async def run_step(
        self,
        step_name: str,
        agent_name: str,
        task: str,
        context: Dict[str, Any] = None,
    ) -> tuple[WorkflowStep, AgentResult]:
        """
        执行单个步骤
        
        Args:
            step_name: 步骤名称
            agent_name: Agent 名称
            task: 任务描述
            context: 上下文
            
        Returns:
            (WorkflowStep, AgentResult)
        """
        agent = self.agents.get(agent_name)
        if not agent:
            step = WorkflowStep(
                name=step_name,
                agent_name=agent_name,
                status="failed",
                error=f"Agent '{agent_name}' not found",
            )
            return step, None
        
        step = WorkflowStep(
            name=step_name,
            agent_name=agent_name,
            status="running",
        )
        
        self.logger.info(f"Running step: {step_name} (agent: {agent_name})")
        start_time = time.time()
        
        try:
            result = await agent.run(task, context)
            elapsed_ms = (time.time() - start_time) * 1000
            
            step.status = "success" if result.success else "failed"
            step.result = result
            step.elapsed_ms = elapsed_ms
            step.error = result.error
            
            self.logger.info(
                f"Step {step_name} completed: "
                f"success={result.success}, elapsed={elapsed_ms:.0f}ms"
            )
            
            return step, result
            
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            step.status = "failed"
            step.elapsed_ms = elapsed_ms
            step.error = str(e)
            
            self.logger.error(f"Step {step_name} failed: {e}")
            
            return step, None
