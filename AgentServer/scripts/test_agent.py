"""
测试 Agent 系统

测试工具注册、Agent 执行、工作流等功能。

用法:
    cd AgentServer
    python scripts/test_agent.py --test tools      # 测试工具
    python scripts/test_agent.py --test agent      # 测试 Agent
    python scripts/test_agent.py --test workflow   # 测试工作流
    python scripts/test_agent.py --stock 600519.SH # 分析指定股票
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


async def test_tools():
    """测试工具注册和执行"""
    print("\n" + "=" * 70)
    print("测试工具注册中心")
    print("=" * 70 + "\n")
    
    from src.tools import tool_registry
    
    # 导入工具模块（触发注册）
    
    # 列出所有工具
    tools = tool_registry.list_all()
    print(f"已注册工具: {len(tools)} 个")
    for name in tools:
        tool = tool_registry.get(name)
        print(f"  - {name}: {tool.description[:50]}...")
    
    # 测试工具执行
    print("\n" + "-" * 70)
    print("测试工具执行")
    print("-" * 70 + "\n")
    
    # 初始化 MongoDB
    from core.managers import mongo_manager
    await mongo_manager.initialize()
    
    # 测试 get_stock_info
    print("测试 get_stock_info('600519.SH')...")
    result = await tool_registry.execute("get_stock_info", stock_code="600519.SH")
    print(f"  结果: {result}")
    
    # 测试 get_daily_kline
    print("\n测试 get_daily_kline('600519.SH', days=5)...")
    result = await tool_registry.execute("get_daily_kline", stock_code="600519.SH", days=5)
    print(f"  数据条数: {result.get('count', 0)}")
    
    # 测试 calculate_technical_indicators
    print("\n测试 calculate_technical_indicators('600519.SH')...")
    result = await tool_registry.execute(
        "calculate_technical_indicators",
        stock_code="600519.SH",
        indicators=["ma", "macd", "rsi"],
    )
    print(f"  指标: {result.get('indicators', {})}")
    
    print("\n✓ 工具测试完成")


async def test_agent(stock_code: str = "600519.SH"):
    """测试股票分析 Agent"""
    print("\n" + "=" * 70)
    print(f"测试股票分析 Agent - {stock_code}")
    print("=" * 70 + "\n")
    
    # 初始化
    from core.managers import mongo_manager
    from src.llm import llm_service
    from src.tools import tool_registry
    from src.agents import StockAnalyzerAgent, AgentConfig
    
    await mongo_manager.initialize()
    await llm_service.initialize()
    
    # 导入工具
    
    # 创建 Agent
    config = AgentConfig(
        max_steps=8,
        verbose=True,
    )
    agent = StockAnalyzerAgent(llm_service, tool_registry, config)
    
    print(f"Agent: {agent.name}")
    print(f"可用工具: {agent.available_tools}")
    print("\n开始分析...\n")
    
    # 执行分析
    result = await agent.run(f"详细分析股票 {stock_code}")
    
    print("\n" + "-" * 70)
    print("分析结果")
    print("-" * 70 + "\n")
    
    print(f"成功: {result.success}")
    print(f"步数: {result.total_steps}")
    print(f"耗时: {result.elapsed_ms:.0f}ms")
    print(f"工具调用: {len(result.tool_calls)} 次")
    
    if result.tool_calls:
        print("\n工具调用记录:")
        for tc in result.tool_calls:
            status = "✓" if tc.success else "✗"
            print(f"  {status} {tc.name} ({tc.elapsed_ms:.0f}ms)")
    
    if result.data:
        print("\n结构化数据:")
        import json
        print(json.dumps(result.data, ensure_ascii=False, indent=2))
    else:
        print("\n分析内容:")
        print(result.content[:1000] if result.content else "(无内容)")
    
    if result.error:
        print(f"\n错误: {result.error}")
    
    print("\n✓ Agent 测试完成")


async def test_workflow(stock_code: str = "600519.SH"):
    """测试工作流"""
    print("\n" + "=" * 70)
    print(f"测试股票深度分析工作流 - {stock_code}")
    print("=" * 70 + "\n")
    
    # 初始化
    from core.managers import mongo_manager
    from src.llm import llm_service
    from src.tools import tool_registry
    from src.agents import StockAnalyzerAgent, ReportWriterAgent, AgentConfig
    from src.workflows import StockDeepDiveWorkflow
    
    await mongo_manager.initialize()
    await llm_service.initialize()
    
    # 导入工具
    
    # 创建 Agents
    config = AgentConfig(max_steps=8)
    agents = {
        "stock_analyzer": StockAnalyzerAgent(llm_service, tool_registry, config),
        "report_writer": ReportWriterAgent(llm_service, tool_registry, config),
    }
    
    # 创建工作流
    workflow = StockDeepDiveWorkflow(agents)
    
    print(f"工作流: {workflow.name}")
    print(f"描述: {workflow.description}")
    print("\n开始执行...\n")
    
    # 执行
    result = await workflow.execute({"stock_code": stock_code})
    
    print("\n" + "-" * 70)
    print("执行结果")
    print("-" * 70 + "\n")
    
    print(f"成功: {result.success}")
    print(f"步数: {result.total_steps}")
    print(f"耗时: {result.elapsed_ms:.0f}ms")
    
    if result.steps:
        print("\n步骤记录:")
        for step in result.steps:
            status = "✓" if step.status == "success" else "✗"
            print(f"  {status} {step.name} ({step.agent_name}) - {step.elapsed_ms:.0f}ms")
    
    if result.data.get("report"):
        print("\n生成的报告:")
        print("-" * 50)
        print(result.data["report"][:2000])
        if len(result.data["report"]) > 2000:
            print(f"\n... (共 {len(result.data['report'])} 字符)")
    
    if result.error:
        print(f"\n错误: {result.error}")
    
    print("\n✓ 工作流测试完成")


async def test_router():
    """测试路由器"""
    print("\n" + "=" * 70)
    print("测试 Agent 路由器")
    print("=" * 70 + "\n")
    
    from src.llm import llm_service
    from src.tools import tool_registry
    from src.agents import StockAnalyzerAgent, ReportWriterAgent, AgentConfig
    from src.workflows import StockDeepDiveWorkflow
    from src.orchestrator import AgentRouter
    
    await llm_service.initialize()
    
    # 创建 Agents 和 Workflows
    config = AgentConfig(max_steps=8)
    agents = {
        "stock_analyzer": StockAnalyzerAgent(llm_service, tool_registry, config),
        "report_writer": ReportWriterAgent(llm_service, tool_registry, config),
    }
    workflows = {
        "stock_deep_dive": StockDeepDiveWorkflow(agents),
    }
    
    # 创建路由器
    router = AgentRouter(agents, workflows, llm_service)
    
    # 测试路由
    test_tasks = [
        "分析股票600519",
        "深度分析贵州茅台",
        "生成分析报告",
        "看看比亚迪最近怎么样",
    ]
    
    print("路由测试:")
    for task in test_tasks:
        handler = await router.route(task)
        handler_type = "Workflow" if hasattr(handler, "execute") else "Agent"
        handler_name = handler.name if handler else "None"
        print(f"  '{task}' → {handler_type}: {handler_name}")
    
    print("\n可用资源:")
    available = router.list_available()
    print(f"  Agents: {[a['name'] for a in available['agents']]}")
    print(f"  Workflows: {[w['name'] for w in available['workflows']]}")
    
    print("\n✓ 路由器测试完成")


def main():
    parser = argparse.ArgumentParser(description="测试 Agent 系统")
    parser.add_argument(
        "--test",
        choices=["tools", "agent", "workflow", "router", "all"],
        default="tools",
        help="测试类型",
    )
    parser.add_argument(
        "--stock",
        type=str,
        default="600519.SH",
        help="测试股票代码",
    )
    
    args = parser.parse_args()
    
    if args.test == "tools":
        asyncio.run(test_tools())
    elif args.test == "agent":
        asyncio.run(test_agent(args.stock))
    elif args.test == "workflow":
        asyncio.run(test_workflow(args.stock))
    elif args.test == "router":
        asyncio.run(test_router())
    elif args.test == "all":
        asyncio.run(test_tools())
        asyncio.run(test_router())
        asyncio.run(test_agent(args.stock))


if __name__ == "__main__":
    main()
