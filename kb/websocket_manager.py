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


class WebSocketManager:
    """
    WebSocket 连接管理器
    
    管理多个客户端连接，按 task_id 分组推送消息
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
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
        """发送任务更新"""
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
                    except:
                        dead_connections.add(ws)
                
                # 清理死连接
                for ws in dead_connections:
                    self._task_connections[task_id].discard(ws)
            
            # 发送到全局连接
            dead_connections = set()
            for ws in self._global_connections:
                try:
                    await ws.send_text(message)
                except:
                    dead_connections.add(ws)
            
            for ws in dead_connections:
                self._global_connections.discard(ws)
    
    async def broadcast(self, message: str):
        """广播消息到所有连接"""
        async with self._lock:
            dead = set()
            for ws in self._global_connections:
                try:
                    await ws.send_text(message)
                except:
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
