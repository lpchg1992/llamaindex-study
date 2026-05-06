from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

from rag.logger import get_logger
from kb_core.registry import get_storage_root

logger = get_logger(__name__)

from .knowledge_base import KnowledgeBaseService

class AdminService:
    """管理服务"""

    @staticmethod
    def list_tables() -> Dict[str, Any]:
        """列出所有知识库的表信息
        
        包括已注册的知识库和存储目录中存在但未注册的知识库。
        
        Returns:
            知识库表列表
        """
        tables: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for kb in KnowledgeBaseService.list_all():
            info = KnowledgeBaseService.get_info(kb["id"])
            if not info:
                continue
            persist_dir = Path(info["persist_dir"])
            tables.append(
                {
                    "kb_id": kb["id"],
                    "path": str(persist_dir),
                    "status": info.get("status", "unknown"),
                    "row_count": info.get("row_count", 0),
                }
            )
            seen.add(kb["id"])

        for child in get_storage_root().iterdir():
            if not child.is_dir() or child.name in seen:
                continue
            tables.append(
                {
                    "kb_id": child.name,
                    "path": str(child),
                    "status": "unregistered",
                    "row_count": None,
                }
            )

        return {"tables": tables}

    @staticmethod
    def get_table_info(kb_id: str) -> Optional[Dict[str, Any]]:
        """获取知识库表详情
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            知识库详细信息
        """
        return KnowledgeBaseService.get_info(kb_id)

    @staticmethod
    def delete_table(kb_id: str) -> bool:
        """删除知识库（从 AdminService）
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            是否成功
        """
        return KnowledgeBaseService.delete(kb_id)

# ==================== 一致性校验与修复 ====================

# =============================================================================
