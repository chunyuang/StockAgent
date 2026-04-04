
import asyncio
import sys
sys.path.append('/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import mongo_manager

async def main():
    print("===== MongoDB 存储的回测运行日志 =====")
    
    # 初始化MongoManager
    await mongo_manager.initialize()
    
    # 查询最新的2个回测任务
    tasks = await mongo_manager.find_many(
        'backtest_tasks',
        {},
        sort=[('created_at', -1)],
        limit=2
    )
    
    for i, task in enumerate(tasks):
        task_id = task.get('task_id', f'unknown_{i}')
        print(f"\n📌 任务 {i+1} | task_id: {task_id}")
        print(f"状态: {task.get('status', 'N/A')}")
        print(f"创建时间: {task.get('created_at', 'N/A')}")
        print(f"日志内容:")
        for log in task.get('logs', []):
            print(f"  {log}")
        print("-" * 80)
    
    print("\n✅ 查询完成！")

if __name__ == "__main__":
    asyncio.run(main())
