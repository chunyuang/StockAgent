"""
LangGraph 图构建器

提供简化的 API 来构建 LangGraph 工作流。
"""

import logging
from typing import Callable, Dict, List, Type, Any, Union
from langgraph.graph import StateGraph, END, START


logger = logging.getLogger(__name__)


class GraphBuilder:
    """
    通用 LangGraph 构建器
    
    封装 StateGraph 的创建和编译，提供简化的 API。
    
    Example:
        builder = GraphBuilder(ReviewState)
        
        # 添加节点
        builder.add_node("market", market_node)
        builder.add_node("sector", sector_node)
        builder.add_node("limit", limit_node)
        
        # 添加边
        builder.add_edge(START, "market")
        builder.add_parallel(["sector", "limit"], after="market", before="merge")
        builder.add_edge("merge", END)
        
        # 编译
        graph = builder.compile()
        
        # 运行
        result = await graph.ainvoke({"trade_date": "20260305"})
    """
    
    def __init__(self, state_class: Type):
        """
        初始化图构建器
        
        Args:
            state_class: 状态类型（TypedDict 子类）
        """
        self.graph = StateGraph(state_class)
        self.state_class = state_class
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._nodes: List[str] = []
        
    def add_node(self, name: str, func: Callable) -> "GraphBuilder":
        """
        添加节点
        
        Args:
            name: 节点名称
            func: 节点函数（同步或异步）
        
        Returns:
            self（支持链式调用）
        """
        self.graph.add_node(name, func)
        self._nodes.append(name)
        self.logger.debug(f"Added node: {name}")
        return self
        
    def add_edge(self, source: str, target: str) -> "GraphBuilder":
        """
        添加边
        
        Args:
            source: 源节点（可使用 START）
            target: 目标节点（可使用 END）
        
        Returns:
            self
        """
        self.graph.add_edge(source, target)
        self.logger.debug(f"Added edge: {source} -> {target}")
        return self
        
    def add_conditional(
        self, 
        source: str, 
        condition: Callable, 
        mapping: Dict[str, str],
    ) -> "GraphBuilder":
        """
        添加条件边
        
        Args:
            source: 源节点
            condition: 条件函数，返回映射的 key
            mapping: 条件值到目标节点的映射
        
        Returns:
            self
            
        Example:
            def check_confidence(state):
                return "report" if state["confidence"] >= 60 else "refine"
            
            builder.add_conditional("check", check_confidence, {
                "report": "report_node",
                "refine": "refine_node",
            })
        """
        self.graph.add_conditional_edges(source, condition, mapping)
        self.logger.debug(f"Added conditional edge from {source}: {list(mapping.keys())}")
        return self
        
    def add_parallel(
        self, 
        nodes: List[str], 
        after: str, 
        before: str,
    ) -> "GraphBuilder":
        """
        添加并行节点（扇出-扇入模式）
        
        从 after 节点扇出到多个并行节点，然后汇聚到 before 节点。
        
        Args:
            nodes: 并行执行的节点列表
            after: 并行前的节点
            before: 并行后汇聚的节点
        
        Returns:
            self
            
        Example:
            # market -> [sector, limit] -> linkage
            builder.add_parallel(["sector", "limit"], after="market", before="linkage")
        """
        for node in nodes:
            self.graph.add_edge(after, node)
            self.graph.add_edge(node, before)
        
        self.logger.debug(f"Added parallel: {after} -> {nodes} -> {before}")
        return self
    
    def set_entry_point(self, node: str) -> "GraphBuilder":
        """
        设置入口节点
        
        Args:
            node: 入口节点名称
        
        Returns:
            self
        """
        self.graph.set_entry_point(node)
        self.logger.debug(f"Set entry point: {node}")
        return self
    
    def set_finish_point(self, node: str) -> "GraphBuilder":
        """
        设置结束节点
        
        Args:
            node: 结束节点名称
        
        Returns:
            self
        """
        self.graph.set_finish_point(node)
        self.logger.debug(f"Set finish point: {node}")
        return self
        
    def compile(self, **kwargs):
        """
        编译图
        
        Args:
            **kwargs: 传递给 compile() 的额外参数
        
        Returns:
            编译后的 CompiledGraph
        """
        compiled = self.graph.compile(**kwargs)
        self.logger.info(f"Compiled graph with {len(self._nodes)} nodes")
        return compiled
    
    def get_graph_structure(self) -> Dict[str, Any]:
        """
        获取图结构（用于调试和可视化）
        
        Returns:
            图结构信息
        """
        return {
            "state_class": self.state_class.__name__,
            "nodes": self._nodes,
        }
