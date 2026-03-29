"""
任务级锁管理器

用于保护共享资源（去重数据库）的并发访问
"""

import asyncio
from typing import Optional

# 全局锁
_dedup_lock: Optional[asyncio.Semaphore] = None


def get_dedup_lock() -> asyncio.Semaphore:
    """获取去重数据库锁（全局单例）"""
    global _dedup_lock
    if _dedup_lock is None:
        _dedup_lock = asyncio.Semaphore(1)
    return _dedup_lock


class DedupLock:
    """去重数据库锁的异步上下文管理器"""
    
    def __init__(self):
        self.lock = get_dedup_lock()
    
    async def __aenter__(self):
        await self.lock.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.lock.release()
        return False
