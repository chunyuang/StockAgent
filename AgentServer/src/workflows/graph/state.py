"""
LangGraph 状态定义

定义各种工作流的状态类型。
"""

from typing import TypedDict, Optional, List, Annotated
from operator import add


class BaseWorkflowState(TypedDict, total=False):
    """
    工作流基础状态
    
    所有工作流状态都应继承此基础类型。
    """
    errors: Annotated[List[str], add]  # 错误列表（累加）
    round_count: int                    # 迭代轮次
    confidence: int                     # 置信度分数 (0-100)


class ReviewState(BaseWorkflowState):
    """
    复盘工作流状态
    
    包含各维度分析结果和最终报告。
    
    Attributes:
        trade_date: 交易日期
        market_result: 大盘分析结果
        sector_result: 板块分析结果
        limit_result: 涨停分析结果
        linkage_result: 个股联动分析结果
        sentiment_result: 情绪周期分析结果
        report: 最终报告内容
        conflicts: 分析冲突列表
    """
    trade_date: str
    
    # 各维度分析结果
    market_result: Optional[dict]
    sector_result: Optional[dict]
    limit_result: Optional[dict]
    linkage_result: Optional[dict]
    sentiment_result: Optional[dict]
    
    # 最终报告
    report: Optional[str]
    
    # 冲突检测
    conflicts: List[str]


class StockAnalysisState(BaseWorkflowState):
    """
    股票分析工作流状态
    
    用于个股深度分析。
    """
    ts_code: str
    stock_name: Optional[str]
    
    # 分析结果
    fundamental_result: Optional[dict]
    technical_result: Optional[dict]
    news_result: Optional[dict]
    
    # 综合分析
    analysis_result: Optional[dict]
    report: Optional[str]
