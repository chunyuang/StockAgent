"""
FastAPI 应用工厂

创建 Web 网关的 FastAPI 应用。
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
import uuid
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.exceptions import HTTPException

from core.settings import settings
from core.managers import (
    redis_manager,
    mongo_manager,
)

from .api import auth_router, user_router, task_router, stock_router, market_router, subscription_router, backtest_router, trading_router
from .websocket import websocket_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    应用生命周期管理
    
    按依赖顺序初始化和关闭管理器。
    """
    # ========== 启动 ==========
    # 初始化必要的管理器 (Web 节点只需要 Redis 和 Mongo)
    await redis_manager.initialize()
    await mongo_manager.initialize()
    
    yield
    
    # ========== 关闭 ==========
    await mongo_manager.shutdown()
    await redis_manager.shutdown()


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title="StockAgent API",
        description="AI 驱动的股票分析智能体 API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )
    
    # ==================== 中间件 ====================
    
    # CORS - 允许所有来源方便开发调试
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Trace ID 中间件
    @app.middleware("http")
    async def trace_id_middleware(request: Request, call_next):
        """为每个请求注入 trace_id"""
        trace_id = request.headers.get("X-Trace-ID") or uuid.uuid4().hex
        request.state.trace_id = trace_id
        
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        
        return response
    
    # ==================== 路由 ====================
    

    
    # 健康检查
    @app.get("/health")
    async def health():
        """健康检查"""
        from core.managers import health_check_all
        
        manager_status = await health_check_all()
        is_healthy = all(manager_status.values())
        
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "managers": manager_status,
        }
    
    # API 路由
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["认证"])
    app.include_router(user_router, prefix="/api/v1/users", tags=["用户"])
    app.include_router(task_router, prefix="/api/v1/tasks", tags=["任务"])
    app.include_router(stock_router, prefix="/api/v1/stocks", tags=["股票"])
    app.include_router(market_router, prefix="/api/v1", tags=["市场分析"])
    app.include_router(subscription_router, prefix="/api/v1/strategy/subscriptions", tags=["策略订阅"])
    app.include_router(backtest_router, prefix="/api/v1", tags=["量化回测"])
    app.include_router(trading_router, prefix="/api/v1", tags=["实盘交易"])
    
    # WebSocket 路由
    app.include_router(websocket_router)
    
    # 静态文件挂载 - 前端资源 (html=True自动处理SPA路由，找不到文件返回index.html)
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../static")
    if os.path.exists(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    
    return app
