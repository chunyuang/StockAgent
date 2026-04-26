"""
WebSocket 端点（集成 Redis Pub/Sub 日志推送）

改进点：
1. Redis Pub/Sub 订阅 → 即时推送日志到前端（替代MongoDB轮询）
2. 客户端订阅task时，从MongoDB/内存缓存补发历史日志
3. 支持 backtest:status / backtest:progress 频道的状态和进度推送

使用方式：
  # 在 app.py lifespan 中初始化桥接
  from nodes.web.redis_ws_bridge import init_bridge
  bridge = init_bridge(manager)
  await bridge.start()

  # 在关闭时
  await bridge.stop()
"""

import json
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError, jwt

from core.settings import settings


router = APIRouter()


# 连接管理
class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        # user_id -> [websocket, ...]
        self._connections: Dict[str, Set[WebSocket]] = {}
        # task_id -> [user_id, ...]
        self._task_subscribers: Dict[str, Set[str]] = {}
        # scheduler 订阅者: user_id -> [websocket, ...]
        self._scheduler_subscribers: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        """连接"""
        await websocket.accept()

        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        """断开连接"""
        if user_id in self._connections:
            self._connections[user_id].discard(websocket)
            if not self._connections[user_id]:
                del self._connections[user_id]
        # 清理 scheduler 订阅
        if user_id in self._scheduler_subscribers:
            self._scheduler_subscribers[user_id].discard(websocket)
            if not self._scheduler_subscribers[user_id]:
                del self._scheduler_subscribers[user_id]

    async def send_to_user(self, user_id: str, message: dict) -> None:
        """发送消息给用户"""
        if user_id in self._connections:
            for ws in list(self._connections[user_id]):
                try:
                    await ws.send_json(message)
                except Exception:
                    self._connections[user_id].discard(ws)

    def subscribe_task(self, user_id: str, task_id: str) -> None:
        """订阅任务"""
        if task_id not in self._task_subscribers:
            self._task_subscribers[task_id] = set()
        self._task_subscribers[task_id].add(user_id)

    def unsubscribe_task(self, user_id: str, task_id: str) -> None:
        """取消订阅"""
        if task_id in self._task_subscribers:
            self._task_subscribers[task_id].discard(user_id)

    async def broadcast_task_update(self, task_id: str, message: dict) -> None:
        """广播任务更新"""
        if task_id in self._task_subscribers:
            for user_id in list(self._task_subscribers[task_id]):
                await self.send_to_user(user_id, message)

    async def broadcast_scheduler_event(self, message: dict) -> None:
        """广播调度器事件到所有订阅了 scheduler 的客户端"""
        for user_id, ws_set in list(self._scheduler_subscribers.items()):
            for ws in list(ws_set):
                try:
                    await ws.send_json(message)
                except Exception:
                    ws_set.discard(ws)

    def subscribe_scheduler(self, user_id: str, websocket: WebSocket) -> None:
        """订阅调度器事件"""
        if user_id not in self._scheduler_subscribers:
            self._scheduler_subscribers[user_id] = set()
        self._scheduler_subscribers[user_id].add(websocket)

    def unsubscribe_scheduler(self, user_id: str, websocket: WebSocket) -> None:
        """取消订阅调度器事件"""
        if user_id in self._scheduler_subscribers:
            self._scheduler_subscribers[user_id].discard(websocket)


manager = ConnectionManager()


def verify_token(token: str) -> str:
    """验证 Token 并返回 user_id"""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        user_id = payload.get("sub")
        if user_id:
            return user_id
    except JWTError:
        pass
    return ""


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None),
):
    """WebSocket 端点"""
    # 验证 Token，可选验证，测试环境默认使用test_user_001
    user_id = "test_user_001"
    if token:
        user_id = verify_token(token)
        if not user_id:
            user_id = "test_user_001"

    # 连接
    await manager.connect(websocket, user_id)

    # 发送连接确认
    await websocket.send_json({
        "type": "connected",
        "user_id": user_id,
    })

    try:
        while True:
            # 接收消息
            data = await websocket.receive_text()
            message = json.loads(data)

            msg_type = message.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "subscribe":
                task_id = message.get("task_id")
                if task_id:
                    manager.subscribe_task(user_id, task_id)
                    await websocket.send_json({
                        "type": "subscribed",
                        "task_id": task_id,
                    })

                    # ===== 核心改进：订阅时补发历史日志 =====
                    # 获取 RedisWSBridge 实例，补发该 task 的历史日志
                    from nodes.web.redis_ws_bridge import get_bridge
                    bridge = get_bridge()
                    if bridge and bridge.is_running:
                        await bridge.catchup_logs(task_id, websocket)

            elif msg_type == "unsubscribe":
                task_id = message.get("task_id")
                if task_id:
                    manager.unsubscribe_task(user_id, task_id)

            elif msg_type == "subscribe_scheduler":
                # 订阅调度器事件
                manager.subscribe_scheduler(user_id, websocket)
                await websocket.send_json({
                    "type": "subscribed_scheduler",
                })

            elif msg_type == "unsubscribe_scheduler":
                # 取消订阅调度器事件
                manager.unsubscribe_scheduler(user_id, websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)


# 导出路由
websocket_router = router
