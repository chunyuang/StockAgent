# Stock Agent - 分布式多模态智能体系统

AI 驱动的股票分析智能体，采用分布式架构设计，支持动态扩容。

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Stock Agent Cluster                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐     ┌─────────────────────────────────────────────────┐   │
│  │  Frontend   │────▶│              Web Gateway Node                   │   │
│  │  (Vue 3)    │◀────│  - REST API / WebSocket                         │   │
│  └─────────────┘     │  - JWT Auth / Task Dispatcher (负载均衡)         │   │
│                      └──────────────────┬──────────────────────────────┘   │
│                                         │                                   │
│                                         ▼                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                        Message Bus (Redis)                            │  │
│  │  - Task Queue (agent:tasks)                                           │  │
│  │  - Result Pub/Sub (agent:results:*)                                   │  │
│  │  - Node Registry (agent:nodes:*) - TTL 15s                            │  │
│  └─────────────────────────────┬────────────────────────────────────────┘  │
│                                │                                            │
│        ┌───────────────────────┼───────────────────────┐                   │
│        ▼                       ▼                       ▼                   │
│  ┌───────────────┐     ┌───────────────┐     ┌───────────────────────┐    │
│  │ Data Sync     │     │ MCP Service   │     │ Inference Agents      │    │
│  │ Node          │     │ Node          │     │ (可动态扩容)            │    │
│  │               │────▶│               │◀────│                       │    │
│  │ - Scheduler   │     │ - Tool Server │     │ Agent-1 │ Agent-2     │    │
│  │ - Collectors  │     │ - 令牌桶限流   │     │ Agent-3 │ Agent-N ... │    │
│  └───────────────┘     └───────────────┘     └───────────────────────┘    │
│                                                                             │
│                      ┌──────────────────────────────────────────────────┐  │
│                      │                Storage Layer                      │  │
│                      │  MongoDB │ Milvus (向量) │ Redis (缓存)           │  │
│                      └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 📁 项目结构

```
AgentServer/
├── core/                       # 核心基础设施
│   ├── settings.py             # 全局配置 (Pydantic Settings)
│   ├── base.py                 # 基类定义 (BaseTool, BaseCollector)
│   ├── protocols.py            # 消息协议 (AgentTask, AgentResponse + TraceID)
│   └── managers/               # 资源管理器 (全局单例模式)
│       ├── __init__.py         # 导出所有单例
│       ├── redis_manager.py    # Redis 单例
│       ├── mongo_manager.py    # MongoDB 单例
│       ├── tushare_manager.py  # Tushare 单例 (令牌桶限流)
│       ├── llm_manager.py      # LLM 单例
│       └── milvus_manager.py   # Milvus 单例
│
├── nodes/                      # 分布式节点
│   ├── base.py                 # 节点基类 (心跳机制: 5s/15s TTL)
│   ├── web/                    # Web 网关节点
│   │   ├── app.py              # FastAPI 应用 (lifespan 初始化)
│   │   ├── api/                # REST API
│   │   │   ├── auth.py         # 认证
│   │   │   ├── user.py         # 用户
│   │   │   ├── task.py         # 任务派发 (负载均衡)
│   │   │   └── stock.py        # 股票数据
│   │   └── websocket.py        # WebSocket 推送
│   ├── data_sync/              # 数据同步节点
│   │   ├── node.py             # 节点实现
│   │   └── collectors/         # 数据采集器 (使用全局单例)
│   ├── mcp/                    # MCP 服务节点
│   │   ├── node.py             # 节点实现
│   │   └── tools/              # MCP 工具集
│   └── inference/              # 分析智能体节点
│       ├── node.py             # 节点实现
│       └── graph/              # LangGraph 工作流
│
├── common/                     # 公共模块
│   ├── logger/                 # 日志配置
│   ├── models/                 # MongoDB 模型
│   └── utils/                  # 工具函数
│
├── main.py                     # 统一入口 (根据 NODE_TYPE 启动)
├── env.example                 # 环境变量示例
└── requirements.txt            # 依赖
```

## 🔧 核心设计

### 1. 资源管理器 (单例模式)

所有外部服务通过全局单例访问，禁止直接 import 外部库：

```python
from core.managers import redis_manager, mongo_manager, tushare_manager

# 在 lifespan 或节点启动时初始化
await redis_manager.initialize()
await mongo_manager.initialize()

# 直接使用
await redis_manager.enqueue_task(task_data)
data = await tushare_manager.get_daily("000001.SZ")
```

### 2. 心跳机制

节点每 5 秒向 Redis 写入心跳，TTL 15 秒：

```python
# Key: agent:nodes:{node_id}
# 内容: NodeInfo (node_type, status, current_tasks, max_tasks, ...)
await redis_manager.register_node(node_id, node_info, ttl=15)
```

### 3. 任务派发 (负载均衡)

派发任务前查询活跃节点，选择负载最低的：

```python
nodes = await redis_manager.get_all_nodes(node_type="inference")
available = [n for n in nodes if n["status"] != "busy"]
best_node = min(available, key=lambda n: n["current_tasks"] / n["max_tasks"])
```

### 4. TraceID 透传

所有任务和日志都包含 trace_id：

```python
task = AgentTask(
    trace_id=request.state.trace_id,  # 从 HTTP 请求传入
    task_type=TaskType.STOCK_ANALYSIS,
    ...
)

# 日志输出
# 2024-01-01 10:00:00 | INFO | node.web-abc123 | trace_id=xxxx | Processing task...
```

### 5. 令牌桶限流 (Tushare)

```python
class TushareManager:
    def __init__(self):
        # rate_limit=200/min -> 3.33/sec
        self._bucket = TokenBucket(rate=3.33, capacity=10)
    
    async def _call_api(self, api_name, **kwargs):
        await self._bucket.wait_and_acquire()  # 等待令牌
        return await loop.run_in_executor(...)
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制示例配置
cp env.example .env

# 编辑配置 (Windows: notepad .env)
vim .env
```

> ⚠️ **重要**: 必须配置 `TUSHARE_TOKEN` 和 `LLM_API_KEY` 才能正常运行！

必要配置：

```env
# Tushare (必须)
TUSHARE_TOKEN=your_tushare_token

# LLM (必须)
LLM_PROVIDER=dashscope
LLM_API_KEY=your_api_key

# 数据库 (可使用默认值)
REDIS_HOST=localhost
MONGO_HOST=localhost
MILVUS_HOST=localhost
```

### 3. 启动服务

#### 使用 Docker Compose (推荐)

```bash
cd deploy
docker-compose up -d
```

#### 手动启动

```bash
# 启动基础设施
docker run -d -p 27017:27017 mongo
docker run -d -p 6379:6379 redis
docker run -d -p 19530:19530 milvusdb/milvus:latest

# 启动 Web 节点
NODE_TYPE=web python main.py

# 启动数据同步节点 (另一个终端)
NODE_TYPE=data_sync python main.py

# 启动 MCP 节点 (另一个终端)
NODE_TYPE=mcp python main.py

# 启动推理节点 (另一个终端, 可启动多个)
NODE_TYPE=inference python main.py
```

### 4. 访问服务

- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

## 📊 动态扩容

推理节点支持动态扩容：

```bash
# 启动更多推理节点
NODE_TYPE=inference MAX_CONCURRENT_TASKS=10 python main.py

# 或使用 Docker
docker run -e NODE_TYPE=inference -e MAX_CONCURRENT_TASKS=10 stock-agent
```

节点会自动注册到 Redis，Web 网关会自动发现并进行负载均衡分发。

## 🔍 可观测性

### 日志格式 (带 TraceID)

```
2024-01-01 10:00:00 | INFO | node.web-abc123 | trace_id=xxxx | Processing task...
```

### Loki 集成

```env
OBS_LOKI_ENABLED=true
OBS_LOKI_URL=http://loki:3100/loki/api/v1/push
```

### Arize Phoenix 追踪

```env
OBS_PHOENIX_ENABLED=true
OBS_PHOENIX_PROJECT=stock-agent
```

## 📝 License

MIT



db.createUser({
  user: "admin",
  pwd: "5201314a",
  roles: [
    { role: "readWrite", db: "stock_agent" }
  ]
})