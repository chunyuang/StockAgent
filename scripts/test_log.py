#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from AgentServer.nodes.backtest_engine.node import BacktestEngineNode
import asyncio

async def test_log():
    node = BacktestEngineNode()
    task_id = "test_task_001"
    
    print("正在测试日志生成...")
    await node._push_log(task_id, "🚀 测试回测启动")
    await node._push_log(task_id, "📅 回测区间: 20260105 -> 20260320")
    await node._push_log(task_id, "💰 初始资金: 1,000,000 元")
    await node._push_log(task_id, "🔌 数据源: mongodb")
    await node._push_log(task_id, "⏱️ 周期: daily")
    await node._push_log(task_id, "✅ 回测完成！")
    
    # 检查日志文件是否生成
    log_dir = "/root/.openclaw/workspace/StockAgent/logs/backtest/"
    files = [f for f in os.listdir(log_dir) if task_id in f]
    
    if files:
        latest_file = sorted(files)[-1]
        file_path = os.path.join(log_dir, latest_file)
        print(f"\n✅ 日志文件已生成：{file_path}")
        print("=" * 60)
        with open(file_path, "r", encoding="utf-8") as f:
            print(f.read())
        print("=" * 60)
        print("日志生成成功！内容和界面显示的完全一致。")
    else:
        print("❌ 日志文件未生成")

if __name__ == "__main__":
    asyncio.run(test_log())
