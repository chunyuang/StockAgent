"""
LangGraph 节点工厂

提供将 Agent 和函数包装为 LangGraph 节点的工具。
"""

import logging
from typing import Callable, Optional, List
from functools import wraps

from src.agents.base import BaseAgent


logger = logging.getLogger(__name__)


def create_agent_node(
    agent: BaseAgent, 
    result_key: str,
    task_template: Optional[str] = None,
    context_keys: Optional[List[str]] = None,
):
    """
    将 Agent 包装为 LangGraph 节点
    
    Args:
        agent: BaseAgent 实例
        result_key: 结果存储到 state 的 key
        task_template: 任务模板，支持 {trade_date} 等占位符
        context_keys: 从 state 中提取作为上下文的 key 列表
    
    Returns:
        异步节点函数
        
    Example:
        market_node = create_agent_node(
            agent=market_agent,
            result_key="market_result",
            task_template="分析 {trade_date} 的大盘表现",
            context_keys=["trade_date"],
        )
    """
    default_template = f"请执行 {agent.name} 任务"
    template = task_template or default_template
    ctx_keys = context_keys or []
    
    async def node(state: dict) -> dict:
        """Agent 节点执行函数"""
        node_logger = logging.getLogger(f"node.{agent.name}")
        
        # 构建任务描述
        try:
            task = template.format(**state)
        except KeyError:
            task = template
        
        # 构建上下文
        context = {}
        for key in ctx_keys:
            if key in state and state[key] is not None:
                context[key] = state[key]
        
        # 添加前置分析结果到上下文
        for key in ["market_result", "sector_result", "limit_result"]:
            if key in state and state[key] is not None and key not in context:
                # 提取内容摘要
                result = state[key]
                if isinstance(result, dict) and "content" in result:
                    context[f"{key.replace('_result', '')}_summary"] = result["content"][:500]
        
        node_logger.info(f"Running agent node: {agent.name}")
        
        try:
            result = await agent.run(task, context)
            
            if result.success:
                node_logger.info(f"Agent {agent.name} completed successfully")
                return {
                    result_key: result.to_dict(),
                }
            else:
                node_logger.warning(f"Agent {agent.name} failed: {result.error}")
                return {
                    result_key: None,
                    "errors": [f"{agent.name}: {result.error}"],
                }
                
        except Exception as e:
            node_logger.error(f"Agent {agent.name} exception: {e}")
            return {
                result_key: None,
                "errors": [f"{agent.name}: {str(e)}"],
            }
    
    # 设置函数名（用于调试）
    node.__name__ = f"{agent.name}_node"
    
    return node


def create_async_node(
    func: Callable,
    result_key: str,
    error_handler: Optional[Callable] = None,
):
    """
    将异步函数包装为 LangGraph 节点
    
    Args:
        func: 异步函数，接收 state dict，返回结果
        result_key: 结果存储到 state 的 key
        error_handler: 可选的错误处理函数
    
    Returns:
        异步节点函数
        
    Example:
        async def my_analysis(state):
            return {"score": 85, "summary": "..."}
        
        node = create_async_node(my_analysis, "analysis_result")
    """
    @wraps(func)
    async def node(state: dict) -> dict:
        node_logger = logging.getLogger(f"node.{func.__name__}")
        
        try:
            result = await func(state)
            
            return {
                result_key: result,
            }
            
        except Exception as e:
            node_logger.error(f"Node {func.__name__} failed: {e}")
            
            if error_handler:
                return error_handler(e, state)
            
            return {
                result_key: None,
                "errors": [f"{func.__name__}: {str(e)}"],
            }
    
    return node


def create_condition_node(
    check_func: Callable[[dict], bool],
    true_key: str = "continue",
    false_key: str = "end",
):
    """
    创建条件检查节点
    
    Args:
        check_func: 检查函数，接收 state，返回 bool
        true_key: 条件为真时返回的 key
        false_key: 条件为假时返回的 key
    
    Returns:
        条件路由函数（用于 add_conditional）
        
    Example:
        def check_confidence(state):
            return state.get("confidence", 0) >= 60
        
        condition = create_condition_node(check_confidence, "report", "refine")
        builder.add_conditional("check", condition, {
            "report": "report_node",
            "refine": "refine_node",
        })
    """
    def condition(state: dict) -> str:
        result = check_func(state)
        return true_key if result else false_key
    
    return condition


def create_supervisor_node(
    conflict_detector: Optional[Callable[[dict], List[str]]] = None,
    confidence_calculator: Optional[Callable[[dict], int]] = None,
):
    """
    创建 Supervisor 节点
    
    用于检测分析冲突和计算置信度。
    
    Args:
        conflict_detector: 冲突检测函数
        confidence_calculator: 置信度计算函数
    
    Returns:
        Supervisor 节点函数
    """
    async def supervisor(state: dict) -> dict:
        node_logger = logging.getLogger("node.supervisor")
        
        conflicts = []
        confidence = 60  # 默认置信度
        
        # 检测冲突
        if conflict_detector:
            try:
                conflicts = conflict_detector(state)
            except Exception as e:
                node_logger.error(f"Conflict detection failed: {e}")
        
        # 计算置信度
        if confidence_calculator:
            try:
                confidence = confidence_calculator(state)
            except Exception as e:
                node_logger.error(f"Confidence calculation failed: {e}")
        
        # 如果有冲突，降低置信度
        if conflicts:
            confidence = max(0, confidence - len(conflicts) * 10)
        
        node_logger.info(f"Supervisor: confidence={confidence}, conflicts={len(conflicts)}")
        
        return {
            "confidence": confidence,
            "conflicts": conflicts,
            "round_count": state.get("round_count", 0) + 1,
        }
    
    return supervisor
