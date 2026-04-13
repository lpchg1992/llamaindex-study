"""
WebSocket 连接管理器

管理 WebSocket 连接，支持：
- 任务进度实时推送
- 任务完成/失败通知
"""

import asyncio
import json
from typing import Dict, Set

from fastapi import WebSocket

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


class WebSocketManager:
    """Manages WebSocket client connections for real-time task updates.

    Singleton. Supports both task-specific connections (per task_id) and
    global connections (receive all updates). Automatically removes dead
    connections on send failure.

    Thread-safe via asyncio.Lock.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the manager with empty connection maps."""
        if self._initialized:
            return
        self._initialized = True

        # task_id -> set of WebSocket connections
        self._task_connections: Dict[str, Set[WebSocket]] = {}

        # 全局连接（接收所有任务更新）
        self._global_connections: Set[WebSocket] = set()

        # 锁
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, task_id: str = None):
        """连接 WebSocket"""
        await websocket.accept()
        
        async with self._lock:
            if task_id:
                if task_id not in self._task_connections:
                    self._task_connections[task_id] = set()
                self._task_connections[task_id].add(websocket)
            else:
                self._global_connections.add(websocket)
    
    async def disconnect(self, websocket: WebSocket, task_id: str = None):
        """断开 WebSocket"""
        async with self._lock:
            if task_id and task_id in self._task_connections:
                self._task_connections[task_id].discard(websocket)
                if not self._task_connections[task_id]:
                    del self._task_connections[task_id]
            else:
                self._global_connections.discard(websocket)
    
    async def send_task_update(self, task_id: str, data: dict):
        """Send a task update message to all connected clients.

        Delivers to both task-specific subscribers and global subscribers.
        Silently drops dead connections without raising.

        Args:
            task_id: Task identifier for routing
            data: Update payload dict
        """
        message = json.dumps({
            "type": "task_update",
            "task_id": task_id,
            "data": data,
        })
        
        async with self._lock:
            # 发送到任务专属连接
            if task_id in self._task_connections:
                dead_connections = set()
                for ws in self._task_connections[task_id]:
                    try:
                        await ws.send_text(message)
                    except Exception:
                        dead_connections.add(ws)
                
                # 清理死连接
                for ws in dead_connections:
                    self._task_connections[task_id].discard(ws)
            
            # 发送到全局连接
            dead_connections = set()
            for ws in self._global_connections:
                try:
                    await ws.send_text(message)
                except Exception:
                    dead_connections.add(ws)
            
            for ws in dead_connections:
                self._global_connections.discard(ws)
    
    async def broadcast(self, message: str):
        """Broadcast a raw string message to all global connections.

        Args:
            message: Raw JSON string to broadcast
        """
        async with self._lock:
            dead = set()
            for ws in self._global_connections:
                try:
                    await ws.send_text(message)
                except Exception:
                    dead.add(ws)
            
            for ws in dead:
                self._global_connections.discard(ws)
    
    def get_connection_count(self) -> int:
        """获取连接数"""
        return len(self._global_connections) + sum(
            len(conns) for conns in self._task_connections.values()
        )


# 全局实例
ws_manager = WebSocketManager()
