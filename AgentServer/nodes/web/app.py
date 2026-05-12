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

from core.settings import settings
from core.managers import (
    redis_manager,
    mongo_manager,
)

from .api import auth_router, user_router, task_router, stock_router, subscription_router, backtest_router, trading_router, system_router, scheduler_router
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
        docs_url="/docs",
        redoc_url="/redoc",
    )
    
    # ==================== 中间件 ====================
    
    # CORS - 从配置读取允许来源
    cors_origins_str = settings.web.cors_origins.strip()
    if cors_origins_str:
        allow_origins = [origin.strip() for origin in cors_origins_str.split(',') if origin.strip()]
    else:
        # 开发环境默认允许所有来源
        allow_origins = ["*"] if settings.debug else []
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # SPA Fallback 中间件 - 非API/非静态文件请求返回index.html
    @app.middleware("http")
    async def spa_fallback_middleware(request: Request, call_next):
        """处理前端SPA路由：非API请求且不是静态文件时返回index.html"""
        response = await call_next(request)
        if response.status_code == 404 and not request.url.path.startswith("/api/"):
            # 检查是否是前端路由（无文件扩展名）
            path = request.url.path
            if "." not in path.split("/")[-1]:
                # 返回index.html让前端路由处理
                from starlette.responses import FileResponse
                static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../static")
                index_path = os.path.join(static_dir, "index.html")
                if os.path.exists(index_path):
                    return FileResponse(index_path, media_type="text/html")
        return response

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
    
    @app.get("/healthz")
    async def healthz():
        """K8s liveness probe - 快速健康检查"""
        return {"status": "ok"}
    
    @app.get("/ready")
    async def ready():
        """K8s readiness probe - 检查依赖是否就绪"""
        from core.managers import health_check_all
        manager_status = await health_check_all()
        is_ready = all(manager_status.values())
        if is_ready:
            return {"status": "ready", "managers": manager_status}
        return {"status": "not_ready", "managers": manager_status}
    
    # API 路由
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["认证"])
    app.include_router(user_router, prefix="/api/v1/users", tags=["用户"])
    app.include_router(task_router, prefix="/api/v1/tasks", tags=["任务"])
    app.include_router(stock_router, prefix="/api/v1/stocks", tags=["股票"])
    # market_router removed: 行情分析/板块分析/热点追踪已从前端移除
    app.include_router(subscription_router, prefix="/api/v1/strategy/subscriptions", tags=["策略订阅"])
    app.include_router(backtest_router, prefix="/api/v1", tags=["量化回测"])
    app.include_router(trading_router, prefix="/api/v1", tags=["实盘交易"])
    app.include_router(system_router, prefix="/api/v1", tags=["系统状态和配置"])
    app.include_router(scheduler_router, prefix="/api/v1", tags=["调度器管理"])
    from .api.admin_db import router as admin_db_router
    app.include_router(admin_db_router, prefix="/api/v1", tags=["数据库管理"])


    
    # WebSocket 路由
    app.include_router(websocket_router)
    
    # 静态文件挂载 - 前端资源 (html=True自动处理SPA路由，找不到文件返回index.html)
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../static")
    if os.path.exists(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    
    return app
