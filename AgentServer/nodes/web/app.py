"""
FastAPI 应用工厂

创建 Web 网关的 FastAPI 应用。
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
import uuid
import os
import logging

logger = logging.getLogger("web.app")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.settings import settings
from core.managers import (
    redis_manager,
    mongo_manager,
)

from .api import auth_router, user_router, task_router, stock_router, subscription_router, backtest_router, trading_router, system_router, scanner_router, strategy_config_router, datasource_router, factor_router, trading_archive_router
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
    
    # 初始化数据源路由器(必盈+掘金)
    try:
        from nodes.market_monitor.data_source_router import DataSourceRouter
        from src.data_sources.biying_adapter import BiyingAdapter
        
        ds_router = DataSourceRouter()
        
        # 必盈(免费版, 无IP限制, 涨停池核心)
        biying_licence = os.environ.get("BIYING_LICENCE", "E53CA0F0-3E85-4736-B22D-8FA41A5DB050")
        if biying_licence:
            biying = BiyingAdapter(licence=biying_licence)
            ds_router.register("biying", biying, priority=10)
        
        # 掘金(需终端, 当前不可用)
        # gm适配器待终端可用后接入
        
        # 初始化所有注册的数据源
        results = await ds_router.initialize_all()
        logger.info(f"[APP] 数据源初始化: {results}")
        
        # 将router注入API模块
        from nodes.web.api.datasource import set_router
        set_router(ds_router)
        
        # 存到app.state供其他模块使用
        app.state.data_source_router = ds_router
    except Exception as e:
        logger.warning(f"[APP] 数据源初始化失败(不影响其他功能): {e}")
    
    # 初始化 Redis→WebSocket 桥接
    try:
        from .websocket import manager as ws_manager
        from .redis_ws_bridge import init_bridge
        bridge = init_bridge(ws_manager)
        await bridge.start()
        logger.info("[APP] Redis→WS 桥接已启动")
    except Exception as e:
        logger.warning(f"[APP] Redis→WS 桥接启动失败(不影响其他功能): {e}")
    
    yield
    
    # ========== 关闭 ==========
    # 停止 Redis→WS 桥接
    try:
        from .redis_ws_bridge import get_bridge
        bridge = get_bridge()
        if bridge:
            await bridge.stop()
            logger.info("[APP] Redis→WS 桥接已停止")
    except Exception as e:
        logger.warning(f"[APP] Redis→WS 桥接停止异常: {e}")
    
    await mongo_manager.shutdown()
    await redis_manager.shutdown()


import math
import json as json_lib


from nodes.web.api.utils import sanitize_nan as _sanitize_nan


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    # 自定义JSON编码: NaN/inf → null
    from fastapi.responses import JSONResponse
    import json as _json
    
    class SafeJSONResponse(JSONResponse):
        def render(self, content) -> bytes:
            return _json.dumps(
                _sanitize_nan(content),
                ensure_ascii=False,
                allow_nan=False,
                default=str,
            ).encode("utf-8")
    
    app = FastAPI(
        title="StockAgent API",
        description="AI 驱动的股票分析智能体 API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        default_response_class=SafeJSONResponse,
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
        """处理前端SPA路由 + 防止浏览器缓存旧页面"""
        response = await call_next(request)
        # HTML和JS/CSS都不缓存（Vite hash是确定性的，改内容hash可能不变）
        if request.url.path == "/" or request.url.path.endswith(".html") or request.url.path.endswith(".js") or request.url.path.endswith(".css"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        if response.status_code == 404 and not request.url.path.startswith("/api/"):
            # 检查是否是前端路由（无文件扩展名）
            path = request.url.path
            if "." not in path.split("/")[-1]:
                # 返回index.html让前端路由处理
                from starlette.responses import FileResponse
                # 前端SPA fallback: 返回index.html让前端路由处理
                static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../frontend/dist")
                index_path = os.path.join(static_dir, "index.html")
                if os.path.exists(index_path):
                    from starlette.responses import Response
                    with open(index_path, "rb") as f:
                        html_content = f.read()
                    return Response(
                        content=html_content,
                        media_type="text/html",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
                    )
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
    app.include_router(scanner_router, prefix="/api/v1", tags=["市场监听"])
    app.include_router(strategy_config_router, tags=["策略配置"])
    app.include_router(datasource_router, prefix="/api/v1", tags=["数据源管理"])
    app.include_router(factor_router, prefix="/api/v1", tags=["因子管理"])
    app.include_router(trading_archive_router, prefix="/api/v1", tags=["交易归档"])
    from .api.admin_db import router as admin_db_router
    app.include_router(admin_db_router, prefix="/api/v1", tags=["数据库管理"])
    # 【v2.9.97】统一数据层 - 8个UI共用
    from .api.unified import router as unified_router
    app.include_router(unified_router, prefix="/api/v1", tags=["统一数据层"])


    
    # WebSocket 路由
    app.include_router(websocket_router)
    
    # 静态文件挂载 - 统一读 frontend/dist/
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../frontend/dist")
    if os.path.exists(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    
    return app
