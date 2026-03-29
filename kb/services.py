"""
知识库服务层

提供统一的业务接口，API 和 CLI 都应该通过这里调用。
解耦业务逻辑和接口层。
"""

import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

from llamaindex_study.logger import get_logger
from llamaindex_study.vector_store import LanceDBVectorStore
from llamaindex_study.ollama_utils import create_ollama_embedding, configure_global_embed_model
from kb.registry import get_storage_root
from kb.deduplication import DeduplicationManager

logger = get_logger(__name__)


class VectorStoreService:
    """向量存储服务"""
    
    @staticmethod
    def get_vector_store(kb_id: str) -> LanceDBVectorStore:
        """获取知识库的向量存储
        
        Obsidian 知识库使用 get_storage_root()
        Zotero 知识库使用 ZOTERO_PERSIST_DIR
        """
        import os
        
        # 检查是否是 Zotero 知识库（数据存在于 ZOTERO_PERSIST_DIR）
        zotero_root = os.getenv("ZOTERO_PERSIST_DIR", "/Volumes/online/llamaindex/zotero")
        zotero_path = Path(zotero_root) / kb_id
        
        if zotero_path.exists():
            # Zotero 知识库
            return LanceDBVectorStore(
                persist_dir=zotero_path,
                table_name=kb_id,
            )
        
        # 默认使用 Obsidian 存储
        persist_dir = get_storage_root() / kb_id
        return LanceDBVectorStore(
            persist_dir=persist_dir,
            table_name=kb_id,
        )
    
    @staticmethod
    def get_persist_dir(kb_id: str) -> Path:
        """获取知识库持久化目录"""
        import os
        
        zotero_root = os.getenv("ZOTERO_PERSIST_DIR", "/Volumes/online/llamaindex/zotero")
        zotero_path = Path(zotero_root) / kb_id
        
        if zotero_path.exists():
            return zotero_path
        
        return get_storage_root() / kb_id


class ObsidianService:
    """Obsidian 导入服务"""
    
    @staticmethod
    def get_vaults() -> List[Dict[str, Any]]:
        """获取可用的 Obsidian Vault 列表"""
        vaults = [
            {
                "name": "默认",
                "path": str(Path.home() / "Documents" / "Obsidian Vault"),
            },
            {
                "name": "坚果云同步",
                "path": "/Volumes/online/nutsync/Obsidian Vault",
            },
        ]
        
        result = []
        for v in vaults:
            path = Path(v["path"])
            if path.exists():
                md_count = len(list(path.rglob("*.md")))
                result.append({
                    **v,
                    "exists": True,
                    "md_files": md_count,
                })
            else:
                result.append({
                    **v,
                    "exists": False,
                    "md_files": 0,
                })
        
        return result
    
    @staticmethod
    def get_vault_info(vault_name: str) -> Optional[Dict[str, Any]]:
        """获取 Vault 信息"""
        if vault_name == "默认":
            vault_path = Path.home() / "Documents" / "Obsidian Vault"
        elif vault_name == "坚果云同步":
            vault_path = Path("/Volumes/online/nutsync/Obsidian Vault")
        else:
            return None
        
        if not vault_path.exists():
            return None
        
        folders = {}
        for item in vault_path.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                md_count = len(list(item.rglob("*.md")))
                if md_count > 0:
                    folders[item.name] = md_count
        
        return {
            "name": vault_name,
            "path": str(vault_path),
            "total_md_files": len(list(vault_path.rglob("*.md"))),
            "folders": folders,
        }
    
    @staticmethod
    def import_vault(
        kb_id: str,
        vault_path: str,
        folder_path: Optional[str] = None,
        recursive: bool = True,
        exclude_patterns: Optional[List[str]] = None,
        rebuild: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        导入 Obsidian 笔记
        
        Args:
            kb_id: 知识库 ID
            vault_path: Vault 根路径
            folder_path: 子文件夹路径
            recursive: 是否递归
            exclude_patterns: 排除模式
            rebuild: 是否重建
            progress_callback: 进度回调
            
        Returns:
            导入统计
        """
        from kb.obsidian_processor import ObsidianImporter
        from kb.document_processor import DocumentProcessorConfig
        
        vault_path = Path(vault_path)
        if not vault_path.exists():
            raise ValueError(f"Vault 路径不存在: {vault_path}")
        
        import_dir = vault_path
        if folder_path:
            import_dir = vault_path / folder_path
            if not import_dir.exists():
                raise ValueError(f"文件夹不存在: {import_dir}")
        
        # 获取向量存储
        vs = VectorStoreService.get_vector_store(kb_id)
        persist_dir = VectorStoreService.get_persist_dir(kb_id)
        
        # 创建导入器
        importer = ObsidianImporter(
            vault_root=vault_path,
            kb_id=kb_id,
            persist_dir=persist_dir,
        )
        
        exclude_patterns = exclude_patterns or [
            "*/image/*", "*/_resources/*", "*/.obsidian/*",
            "*/.trash/*", "*/Z_Copilot/*", "*/copilot-custom-prompts/*"
        ]
        importer.exclude_patterns = exclude_patterns
        
        if progress_callback:
            progress_callback(f"开始导入 Obsidian: {import_dir.name}")
        
        try:
            stats = importer.import_directory(
                directory=import_dir,
                vector_store=vs,
                embed_model=create_ollama_embedding(),
                progress=None,
                rebuild=rebuild,
                exclude_patterns=exclude_patterns,
                recursive=recursive,
            )
            
            if progress_callback:
                progress_callback(f"完成！导入 {stats.get('files', 0)} 个文件，{stats.get('nodes', 0)} 个节点")
            
            return stats
            
        finally:
            pass  # ObsidianImporter 不需要关闭


class ZoteroService:
    """Zotero 导入服务"""
    
    @staticmethod
    def list_collections() -> List[Dict[str, Any]]:
        """列出所有收藏夹"""
        from kb.zotero_processor import ZoteroImporter
        
        importer = ZoteroImporter()
        collections = importer.get_collections()
        importer.close()
        
        return collections
    
    @staticmethod
    def search_collections(q: str) -> List[Dict[str, Any]]:
        """搜索收藏夹"""
        from kb.zotero_processor import ZoteroImporter
        
        importer = ZoteroImporter()
        results = importer.search_collections(q)
        importer.close()
        
        return results
    
    @staticmethod
    def import_collection(
        kb_id: str,
        collection_id: Optional[str] = None,
        collection_name: Optional[str] = None,
        rebuild: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        导入 Zotero 收藏夹
        
        Args:
            kb_id: 知识库 ID
            collection_id: 收藏夹 ID
            collection_name: 收藏夹名称（用于查找 ID）
            rebuild: 是否重建
            progress_callback: 进度回调
            
        Returns:
            导入统计
        """
        from kb.zotero_processor import ZoteroImporter
        from kb.document_processor import DocumentProcessorConfig, ProcessingProgress
        
        importer = ZoteroImporter()
        
        # 解析收藏夹 ID
        if not collection_id and collection_name:
            result = importer.get_collection_by_name(collection_name)
            if result and "collectionID" in result:
                collection_id = result["collectionID"]
                collection_name = result.get("collectionName", collection_name)
            elif result and "multiple" in result:
                importer.close()
                raise ValueError(f"名称模糊，存在多个匹配，请用 collection_id 精确指定")
            else:
                importer.close()
                raise ValueError(f"未找到收藏夹: {collection_name}")
        
        if not collection_id:
            importer.close()
            raise ValueError("未指定收藏夹 ID 或名称")
        
        if progress_callback:
            progress_callback(f"开始导入 Zotero: {collection_name}")
        
        # 获取向量存储
        vs = VectorStoreService.get_vector_store(kb_id)
        
        # 进度文件
        progress_file = Path.home() / ".llamaindex" / f"zotero_{collection_id}_progress.json"
        progress = ProcessingProgress.load(progress_file)
        
        if rebuild:
            vs.delete_table()
            progress = ProcessingProgress()
        
        try:
            stats = importer.import_collection(
                collection_id=collection_id,
                collection_name=collection_name,
                vector_store=vs,
                embed_model=create_ollama_embedding(),
                progress=progress,
                rebuild=rebuild,
            )
            
            progress_file.unlink(missing_ok=True)
            
            if progress_callback:
                progress_callback(f"完成！导入 {stats.get('items', 0)} 篇文献，{stats.get('nodes', 0)} 个节点")
            
            return stats
            
        finally:
            importer.close()


class GenericService:
    """通用文件导入服务"""
    
    @staticmethod
    def import_file(
        kb_id: str,
        path: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        导入单个文件
        
        Args:
            kb_id: 知识库 ID
            path: 文件路径
            progress_callback: 进度回调
            
        Returns:
            导入统计
        """
        from kb.generic_processor import GenericImporter
        
        file_path = Path(path)
        if not file_path.exists():
            raise ValueError(f"文件不存在: {path}")
        
        vs = VectorStoreService.get_vector_store(kb_id)
        importer = GenericImporter()
        
        if progress_callback:
            progress_callback(f"开始导入: {file_path.name}")
        
        try:
            stats = importer.process_file(
                path=file_path,
                vector_store=vs,
                embed_model=create_ollama_embedding(),
            )
            
            if progress_callback:
                progress_callback(f"完成！导入 {stats.get('files', 0)} 个文件，{stats.get('nodes', 0)} 个节点")
            
            return stats
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"导入失败: {e}")
            raise


class KnowledgeBaseService:
    """知识库管理服务"""
    
    @staticmethod
    def list_all() -> List[Dict[str, Any]]:
        """列出所有知识库"""
        from kb.registry import registry
        
        kbs = registry.list_all()
        result = []
        
        for kb in kbs:
            persist_dir = kb.persist_dir
            exists = persist_dir.exists()
            
            row_count = 0
            if exists:
                try:
                    vs = VectorStoreService.get_vector_store(kb.id)
                    stats = vs.get_stats()
                    row_count = stats.get("row_count", 0)
                except Exception:
                    pass
            
            result.append({
                "id": kb.id,
                "name": kb.name,
                "description": kb.description,
                "status": "indexed" if row_count > 0 else "empty",
                "row_count": row_count,
            })
        
        return result
    
    @staticmethod
    def get_info(kb_id: str) -> Optional[Dict[str, Any]]:
        """获取知识库详情"""
        from kb.registry import registry
        
        kb = registry.get(kb_id)
        if not kb:
            return None
        
        persist_dir = kb.persist_dir
        
        info = {
            "id": kb.id,
            "name": kb.name,
            "description": kb.description,
            "persist_dir": str(persist_dir),
        }
        
        if persist_dir.exists():
            try:
                vs = VectorStoreService.get_vector_store(kb_id)
                stats = vs.get_stats()
                info["status"] = "indexed" if stats.get("row_count", 0) > 0 else "empty"
                info["row_count"] = stats.get("row_count", 0)
            except Exception:
                info["status"] = "error"
        else:
            info["status"] = "not_found"
        
        return info
    
    @staticmethod
    def create(kb_id: str, name: str, description: str = "") -> Dict[str, Any]:
        """创建知识库"""
        from kb.registry import registry
        
        if registry.exists(kb_id):
            raise ValueError(f"知识库 {kb_id} 已存在")
        
        persist_dir = get_storage_root() / kb_id
        persist_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建空的向量存储
        vs = VectorStoreService.get_vector_store(kb_id)
        
        return {
            "id": kb_id,
            "name": name,
            "description": description,
            "status": "created",
        }
    
    @staticmethod
    def delete(kb_id: str) -> bool:
        """删除知识库"""
        persist_dir = get_storage_root() / kb_id
        
        if not persist_dir.exists():
            return False
        
        vs = VectorStoreService.get_vector_store(kb_id)
        vs.delete_table()
        
        import shutil
        shutil.rmtree(persist_dir)
        
        return True
    
    @staticmethod
    def rebuild(kb_id: str) -> bool:
        """重建知识库"""
        vs = VectorStoreService.get_vector_store(kb_id)
        vs.delete_table()
        return True


class SearchService:
    """搜索服务"""
    
    @staticmethod
    def search(
        kb_id: str,
        query: str,
        top_k: int = 5,
        with_metadata: bool = True,
    ) -> List[Dict[str, Any]]:
        """向量检索"""
        configure_global_embed_model()
        
        vs = VectorStoreService.get_vector_store(kb_id)
        index = vs.load_index()
        
        if index is None:
            return []
        
        retriever = index.as_retriever(similarity_top_k=top_k)
        results = retriever.retrieve(query)
        
        return [
            {
                "text": r.text[:500],
                "score": r.score,
                "metadata": r.metadata or {},
            }
            for r in results[:top_k]
        ]
    
    @staticmethod
    def query(
        kb_id: str,
        query: str,
        mode: str = "hybrid",
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """RAG 问答"""
        from llamaindex_study.query_engine import create_query_engine
        
        configure_global_embed_model()
        
        query_engine = create_query_engine(kb_id, mode=mode, top_k=top_k)
        response = query_engine.query(query)
        
        return {
            "response": str(response),
            "sources": [
                {"text": r.text[:200], "score": r.score}
                for r in response.source_nodes
            ],
        }
