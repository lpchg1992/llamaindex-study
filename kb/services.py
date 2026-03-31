"""
知识库服务层

提供统一的业务接口，API 和 CLI 都应该通过这里调用。
解耦业务逻辑和接口层。
"""

import asyncio
import time
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger
from llamaindex_study.vector_store import LanceDBVectorStore
from llamaindex_study.ollama_utils import (
    create_parallel_ollama_embedding,
    configure_global_embed_model,
    configure_llamaindex_for_siliconflow,
)
from kb.registry import get_storage_root, get_zotero_storage_root
from kb.deduplication import DeduplicationManager

logger = get_logger(__name__)


class VectorStoreService:
    """向量存储服务"""

    @staticmethod
    def get_vector_store(kb_id: str) -> LanceDBVectorStore:
        """获取知识库的向量存储"""
        from kb.registry import registry

        kb = registry.get(kb_id)
        if kb:
            persist_dir = kb.persist_dir
        else:
            settings = get_settings()
            if kb_id.startswith("zotero_"):
                persist_dir = Path(settings.zotero_persist_dir) / kb_id
            else:
                persist_dir = get_storage_root() / kb_id

        return LanceDBVectorStore(
            persist_dir=persist_dir,
            table_name=kb_id,
        )

    @staticmethod
    def get_persist_dir(kb_id: str) -> Path:
        """获取知识库持久化目录"""
        from kb.registry import registry

        kb = registry.get(kb_id)
        if kb:
            return kb.persist_dir

        settings = get_settings()
        if kb_id.startswith("zotero_"):
            return Path(settings.zotero_persist_dir) / kb_id
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
                result.append(
                    {
                        **v,
                        "exists": True,
                        "md_files": md_count,
                    }
                )
            else:
                result.append(
                    {
                        **v,
                        "exists": False,
                        "md_files": 0,
                    }
                )

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
            "*/image/*",
            "*/_resources/*",
            "*/.obsidian/*",
            "*/.trash/*",
            "*/Z_Copilot/*",
            "*/copilot-custom-prompts/*",
        ]
        importer.exclude_patterns = exclude_patterns

        if progress_callback:
            progress_callback(f"开始导入 Obsidian: {import_dir.name}")

        try:
            stats = importer.import_directory(
                directory=import_dir,
                vector_store=vs,
                embed_model=create_parallel_ollama_embedding(),
                progress=None,
                rebuild=rebuild,
                exclude_patterns=exclude_patterns,
                recursive=recursive,
            )

            if progress_callback:
                progress_callback(
                    f"完成！导入 {stats.get('files', 0)} 个文件，{stats.get('nodes', 0)} 个节点"
                )

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
        progress_file = (
            Path.home() / ".llamaindex" / f"zotero_{collection_id}_progress.json"
        )
        progress = ProcessingProgress.load(progress_file)

        if rebuild:
            vs.delete_table()
            progress = ProcessingProgress()

        try:
            stats = importer.import_collection(
                collection_id=collection_id,
                collection_name=collection_name,
                vector_store=vs,
                embed_model=create_parallel_ollama_embedding(),
                progress=progress,
                rebuild=rebuild,
            )

            progress_file.unlink(missing_ok=True)

            if progress_callback:
                progress_callback(
                    f"完成！导入 {stats.get('items', 0)} 篇文献，{stats.get('nodes', 0)} 个节点"
                )

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
                embed_model=create_parallel_ollama_embedding(),
            )

            if progress_callback:
                progress_callback(
                    f"完成！导入 {stats.get('files', 0)} 个文件，{stats.get('nodes', 0)} 个节点"
                )

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
        from kb.database import init_kb_meta_db

        kbs = registry.list_all()
        kb_meta_db = init_kb_meta_db()
        all_db_rows = {kb["kb_id"]: kb for kb in kb_meta_db.get_all()}
        result = []
        seen: set[str] = set()

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

            db_row = all_db_rows.get(kb.id, {})
            db_topics = db_row.get("topics", []) or []
            registry_topics = getattr(kb, "topics", []) or []
            all_topics = list(set(db_topics + registry_topics))

            result.append(
                {
                    "id": kb.id,
                    "name": kb.name,
                    "description": kb.description,
                    "source_type": db_row.get("source_type", "unknown"),
                    "status": "indexed" if row_count > 0 else "empty",
                    "row_count": row_count,
                    "topics": all_topics,
                }
            )
            seen.add(kb.id)

        for kb_id, kb_meta in all_db_rows.items():
            if kb_id in seen:
                continue
            persist_dir = Path(
                kb_meta.get("persist_path") or (get_storage_root() / kb_id)
            )
            info = {
                "id": kb_id,
                "name": kb_meta.get("name", kb_id),
                "description": kb_meta.get("description", ""),
                "source_type": kb_meta.get("source_type", "unknown"),
                "status": "empty",
                "row_count": 0,
                "topics": kb_meta.get("topics", []),
            }
            if persist_dir.exists():
                try:
                    vs = LanceDBVectorStore(persist_dir=persist_dir, table_name=kb_id)
                    stats = vs.get_stats()
                    info["status"] = (
                        "indexed" if stats.get("row_count", 0) > 0 else "empty"
                    )
                    info["row_count"] = stats.get("row_count", 0)
                except Exception:
                    info["status"] = "error"
            result.append(info)

        return result

    @staticmethod
    def get_info(kb_id: str) -> Optional[Dict[str, Any]]:
        """获取知识库详情"""
        from kb.registry import registry
        from kb.database import init_kb_meta_db

        kb = registry.get(kb_id)
        if kb:
            persist_dir = kb.persist_dir
            info = {
                "id": kb.id,
                "name": kb.name,
                "description": kb.description,
                "persist_dir": str(persist_dir),
            }
        else:
            kb_meta = init_kb_meta_db().get(kb_id)
            if not kb_meta:
                return None
            persist_dir = Path(
                kb_meta.get("persist_path") or (get_storage_root() / kb_id)
            )
            info = {
                "id": kb_id,
                "name": kb_meta.get("name", kb_id),
                "description": kb_meta.get("description", ""),
                "persist_dir": str(persist_dir),
            }

        if persist_dir.exists():
            try:
                vs = LanceDBVectorStore(persist_dir=persist_dir, table_name=kb_id)
                stats = vs.get_stats()
                info["status"] = "indexed" if stats.get("row_count", 0) > 0 else "empty"
                info["row_count"] = stats.get("row_count", 0)
                info["chunk_strategy"] = vs.get_chunk_strategy()
            except Exception:
                info["status"] = "error"
        else:
            info["status"] = "not_found"

        return info

    @staticmethod
    def sync_from_registry(kb_id: str, source_type: str = "obsidian") -> bool:
        from kb.registry import registry
        from kb.database import init_kb_meta_db

        kb = registry.get(kb_id)
        if not kb:
            return False

        init_kb_meta_db().upsert(
            kb_id=kb.id,
            name=kb.name,
            description=kb.description,
            source_type=source_type,
            persist_path=str(kb.persist_dir),
            tags=kb.tags,
            topics=[],
            source_paths=kb.source_paths,
            source_tags=kb.source_tags,
        )
        return True

    @staticmethod
    def create(kb_id: str, name: str, description: str = "") -> Dict[str, Any]:
        """创建知识库"""
        from kb.registry import registry
        from kb.database import init_kb_meta_db

        if registry.exists(kb_id) or init_kb_meta_db().get(kb_id):
            raise ValueError(f"知识库 {kb_id} 已存在")

        persist_dir = get_storage_root() / kb_id
        persist_dir.mkdir(parents=True, exist_ok=True)
        init_kb_meta_db().upsert(
            kb_id=kb_id,
            name=name or kb_id,
            description=description,
            source_type="manual",
            persist_path=str(persist_dir),
        )

        return {
            "id": kb_id,
            "name": name,
            "description": description,
            "status": "created",
        }

    @staticmethod
    def delete(kb_id: str) -> bool:
        """删除知识库（软删除 + 清理物理数据）"""
        from kb.registry import registry
        from kb.database import init_kb_meta_db

        info = KnowledgeBaseService.get_info(kb_id)
        if not info:
            return False

        # 1. 删除向量存储表
        persist_dir = Path(info["persist_dir"])
        vs = LanceDBVectorStore(persist_dir=persist_dir, table_name=kb_id)
        try:
            vs.delete_table()
        except Exception:
            pass

        # 2. 删除物理数据目录
        import shutil

        if persist_dir.exists():
            shutil.rmtree(persist_dir)

        # 3. 软删除：设置 is_active = 0（而不是硬删除）
        # 这样注册表不会从 KNOWLEDGE_BASES 回退加载已删除的 KB
        init_kb_meta_db().set_active(kb_id, is_active=False)

        # 4. 清除注册表缓存，强制重新加载
        registry._loaded = False
        registry._bases.clear()

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
        use_auto_merging: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        from llamaindex_study.config import get_settings

        configure_global_embed_model()
        settings = get_settings()

        vs = VectorStoreService.get_vector_store(kb_id)
        index = vs.load_index()

        if index is None:
            return []

        base_retriever = index.as_retriever(similarity_top_k=top_k * 3)

        _use_auto_merging = (
            use_auto_merging
            if use_auto_merging is not None
            else settings.use_auto_merging
        )

        if _use_auto_merging:
            try:
                from llama_index.core.retrievers import AutoMergingRetriever

                merger = AutoMergingRetriever(
                    base_retriever,
                    index.storage_context,
                    verbose=False,
                )
                retriever = merger
            except Exception:
                retriever = base_retriever
        else:
            retriever = base_retriever

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
    def search_multi(
        kb_ids: List[str],
        query: str,
        top_k: int = 5,
        use_auto_merging: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        configure_global_embed_model()

        all_results = []
        for kb_id in kb_ids:
            try:
                results = SearchService.search(
                    kb_id, query, top_k=top_k, use_auto_merging=use_auto_merging
                )
                for r in results:
                    r["kb_id"] = kb_id
                all_results.extend(results)
            except Exception:
                continue

        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return all_results[:top_k]

    @staticmethod
    def query(
        kb_id: str,
        query: str,
        mode: str = "vector",
        top_k: int = 5,
        use_hyde: Optional[bool] = None,
        use_multi_query: Optional[bool] = None,
        use_auto_merging: Optional[bool] = None,
        response_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """RAG 问答

        Args:
            kb_id: 知识库 ID
            query: 查询内容
            mode: 检索模式 (vector, hybrid)
            top_k: 返回结果数量
            use_hyde: 启用 HyDE（None=使用配置默认值）
            use_multi_query: 启用多查询转换（None=使用配置默认值）
            use_auto_merging: 启用 Auto-Merging（None=使用配置默认值）
            response_mode: 答案生成模式（None=使用配置默认值）
        """
        from llamaindex_study.query_engine import create_query_engine
        from llamaindex_study.config import get_settings

        configure_global_embed_model()
        settings = get_settings()

        query_engine = create_query_engine(
            kb_id,
            mode=mode,
            top_k=top_k,
            use_auto_merging=use_auto_merging
            if use_auto_merging is not None
            else settings.use_auto_merging,
            use_hyde=use_hyde if use_hyde is not None else settings.use_hyde,
            use_multi_query=use_multi_query
            if use_multi_query is not None
            else settings.use_multi_query,
            response_mode=response_mode or settings.response_mode,
        )
        response = query_engine.query(query)

        return {
            "response": str(response),
            "sources": [
                {"text": r.text[:200], "score": r.score} for r in response.source_nodes
            ],
        }


class QueryRouter:
    """查询路由服务 - 自动选择知识库"""

    @staticmethod
    def route(
        query: str,
        top_k: int = 5,
        exclude: Optional[List[str]] = None,
    ) -> List[str]:
        """根据查询内容路由到最相关的知识库

        Args:
            query: 用户查询
            top_k: 返回最相关的 top_k 个知识库
            exclude: 排除的知识库 ID 列表

        Returns:
            知识库 ID 列表
        """
        kbs = KnowledgeBaseService.list_all()
        exclude = exclude or []

        if not kbs:
            return []

        kbs = [kb for kb in kbs if kb["id"] not in exclude]

        if len(kbs) == 1:
            return [kbs[0]["id"]]

        kb_ids = QueryRouter._llm_route(query, kbs)

        if not kb_ids:
            kb_ids = QueryRouter._keyword_route(query, kbs)

        return kb_ids[:top_k]

    @staticmethod
    def _llm_route(query: str, kbs: List[Dict[str, Any]]) -> List[str]:
        try:
            import httpx

            settings = get_settings()

            kb_descriptions = []
            for kb in kbs:
                topics = kb.get("topics", [])
                topics_str = ", ".join(topics) if topics else "无"
                kb_descriptions.append(f"- {kb['id']}: {topics_str}")

            kb_list_text = "\n".join(kb_descriptions)

            prompt = f"""分析用户问题，从知识库列表中找出所有可能相关的知识库。

重要原则：
- 仅根据每个知识库的主题关键词（topics）进行判断
- 如果问题中的关键词与某知识库的主题高度重合，则选择该库
- 主题关键词完全不匹配的知识库不要选择
- 宁可精确匹配，也不要随意扩展

知识库列表：
{kb_list_text}

用户问题：{query}

请先分析问题中的关键词，然后与每个知识库的主题进行匹配，返回最相关的知识库 ID，用逗号分隔。

返回格式示例：kb1,kb2,kb3

请只返回 ID 列表，不要其他内容。"""

            resp = httpx.post(
                f"{settings.siliconflow_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.siliconflow_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.siliconflow_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 100,
                    "temperature": 0.3,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            result = data["choices"][0]["message"]["content"].strip()

            selected = [kb_id.strip() for kb_id in result.split(",")]

            valid_ids = {kb["id"] for kb in kbs}
            selected = [kb_id for kb_id in selected if kb_id in valid_ids]

            return selected

        except Exception as e:
            logger = get_logger(__name__)
            logger.warning(f"LLM 路由失败: {e}")
            return []

    @staticmethod
    def _keyword_route(query: str, kbs: List[Dict[str, Any]]) -> List[str]:
        """使用关键词匹配进行知识库路由（仅基于 topics）"""
        query_lower = query.lower()
        query_words = set(query_lower.replace(",", " ").split())

        scores: Dict[str, float] = {}

        for kb in kbs:
            kb_id = kb["id"]
            topics = kb.get("topics", [])
            if not topics:
                continue

            score = 0.0
            for word in query_words:
                if len(word) < 2:
                    continue
                for topic in topics:
                    topic_lower = topic.lower()
                    if word in topic_lower:
                        score += 1.0
                    if topic_lower in word:
                        score += 0.5

            if score > 0:
                scores[kb_id] = score

        if not scores:
            return []

        sorted_kbs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [kb_id for kb_id, _ in sorted_kbs]

    @staticmethod
    def search(
        query: str,
        top_k: int = 5,
        mode: str = "auto",
        exclude: Optional[List[str]] = None,
        use_auto_merging: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if mode == "all":
            all_kbs = KnowledgeBaseService.list_all()
            exclude = exclude or []
            kb_ids = [kb["id"] for kb in all_kbs if kb["id"] not in exclude]
        else:
            kb_ids = QueryRouter.route(query, exclude=exclude)

        if not kb_ids:
            return {"results": [], "kbs_queried": [], "query": query}

        all_results = []
        for kb_id in kb_ids:
            try:
                results = SearchService.search(
                    kb_id, query, top_k=top_k, use_auto_merging=use_auto_merging
                )
                for r in results:
                    r["kb_id"] = kb_id
                all_results.extend(results)
            except Exception:
                continue

        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

        return {
            "results": all_results[:top_k],
            "kbs_queried": kb_ids,
            "query": query,
        }

    @staticmethod
    def query(
        query: str,
        top_k: int = 5,
        mode: str = "auto",
        exclude: Optional[List[str]] = None,
        use_hyde: Optional[bool] = None,
        use_multi_query: Optional[bool] = None,
        use_auto_merging: Optional[bool] = None,
        response_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """自动路由 RAG 问答

        Args:
            query: 用户查询
            top_k: 每个知识库检索的数量
            mode: 检索模式 (auto=自动路由, all=所有知识库)
            exclude: 排除的知识库 ID 列表
            use_hyde: 启用 HyDE（None=使用配置默认值）
            use_multi_query: 启用多查询转换（None=使用配置默认值）
            use_auto_merging: 启用 Auto-Merging（None=使用配置默认值）
            response_mode: 答案生成模式（None=使用配置默认值）

        Returns:
            RAG 问答结果
        """
        if mode == "all":
            all_kbs = KnowledgeBaseService.list_all()
            exclude = exclude or []
            kb_ids = [kb["id"] for kb in all_kbs if kb["id"] not in exclude]
        else:
            kb_ids = QueryRouter.route(query, exclude=exclude)

        if not kb_ids:
            return {
                "response": "没有找到相关的知识库",
                "sources": [],
                "kbs_queried": [],
            }

        if len(kb_ids) == 1:
            return SearchService.query(
                kb_ids[0],
                query,
                top_k=top_k,
                use_hyde=use_hyde,
                use_multi_query=use_multi_query,
                use_auto_merging=use_auto_merging,
                response_mode=response_mode,
            )

        contexts = []
        sources = []

        for kb_id in kb_ids:
            try:
                result = SearchService.search(kb_id, query, top_k=top_k)
                for r in result:
                    contexts.append(f"[{kb_id}] {r['text']}")
                    sources.append(
                        {
                            "kb_id": kb_id,
                            "text": r["text"][:200],
                            "score": r.get("score", 0),
                        }
                    )
            except Exception:
                continue

        if not contexts:
            return {
                "response": "在所有知识库中都没有找到相关内容",
                "sources": [],
                "kbs_queried": kb_ids,
            }

        context_text = "\n\n".join(contexts[:10])

        prompt = f"""基于以下上下文信息回答用户问题。如果上下文中没有相关信息，请说明。

上下文：
{context_text}

用户问题：{query}

回答："""

        try:
            from llama_index.llms.openai import OpenAI

            settings = get_settings()
            configure_llamaindex_for_siliconflow()

            client = OpenAI(
                model=settings.siliconflow_model,
                api_key=settings.siliconflow_api_key,
                api_base=settings.siliconflow_base_url,
            )

            response = client.complete(prompt)
            answer = response.text.strip()

        except Exception as e:
            logger = get_logger(__name__)
            logger.warning(f"LLM 生成失败: {e}")
            answer = f"（在 {', '.join(kb_ids)} 中找到 {len(contexts)} 条相关内容）"

        return {
            "response": answer,
            "sources": sources[:top_k],
            "kbs_queried": kb_ids,
        }

    @staticmethod
    def query_multi(
        kb_ids: List[str],
        query: str,
        top_k: int = 5,
        use_hyde: Optional[bool] = None,
        use_multi_query: Optional[bool] = None,
        use_auto_merging: Optional[bool] = None,
        response_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not kb_ids:
            return {
                "response": "没有指定知识库",
                "sources": [],
                "kbs_queried": [],
            }

        if len(kb_ids) == 1:
            return SearchService.query(
                kb_ids[0],
                query,
                top_k=top_k,
                use_hyde=use_hyde,
                use_multi_query=use_multi_query,
                use_auto_merging=use_auto_merging,
                response_mode=response_mode,
            )

        contexts = []
        sources = []

        for kb_id in kb_ids:
            try:
                result = SearchService.search(
                    kb_id, query, top_k=top_k, use_auto_merging=use_auto_merging
                )
                for r in result:
                    contexts.append(f"[{kb_id}] {r['text']}")
                    sources.append(
                        {
                            "kb_id": kb_id,
                            "text": r["text"][:200],
                            "score": r.get("score", 0),
                        }
                    )
            except Exception:
                continue

        if not contexts:
            return {
                "response": "在所有知识库中都没有找到相关内容",
                "sources": [],
                "kbs_queried": kb_ids,
            }

        context_text = "\n\n".join(contexts[:10])

        prompt = f"""基于以下上下文信息回答用户问题。如果上下文中没有相关信息，请说明。

上下文：
{context_text}

用户问题：{query}

回答："""

        try:
            from llama_index.llms.openai import OpenAI

            settings = get_settings()
            configure_llamaindex_for_siliconflow()

            client = OpenAI(
                model=settings.siliconflow_model,
                api_key=settings.siliconflow_api_key,
                api_base=settings.siliconflow_base_url,
            )

            response = client.complete(prompt)
            answer = response.text.strip()

        except Exception as e:
            logger = get_logger(__name__)
            logger.warning(f"LLM 生成失败: {e}")
            answer = f"（在 {', '.join(kb_ids)} 中找到 {len(contexts)} 条相关内容）"

        return {
            "response": answer,
            "sources": sources[:top_k],
            "kbs_queried": kb_ids,
        }


class TaskService:
    """任务服务"""

    @staticmethod
    def submit(
        task_type: str, kb_id: str, params: Dict[str, Any], source: str = ""
    ) -> Dict[str, Any]:
        from kb.task_queue import TaskQueue

        queue = TaskQueue()
        task_id = queue.submit_task(
            task_type=task_type,
            kb_id=kb_id,
            params=params,
            source=source,
        )
        return {
            "task_id": task_id,
            "status": "pending",
            "kb_id": kb_id,
            "message": "任务已提交",
        }

    @staticmethod
    def list_tasks(
        kb_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        from kb.task_queue import TaskQueue, TaskStatus
        from kb.task_executor import task_executor, is_scheduler_running

        queue = TaskQueue()

        # Only detect orphans if scheduler is not running
        if not is_scheduler_running():
            running_tasks = queue.list_tasks(status=TaskStatus.RUNNING.value, limit=100)
            for task in running_tasks:
                if task.task_id not in task_executor._running_tasks:
                    queue.update_status(
                        task.task_id,
                        TaskStatus.FAILED.value,
                        "孤儿任务（执行进程已终止）",
                    )

        return [
            task.to_dict()
            for task in queue.list_tasks(kb_id=kb_id, status=status, limit=limit)
        ]

    @staticmethod
    def get_task(task_id: str) -> Optional[Dict[str, Any]]:
        from kb.task_queue import TaskQueue, TaskStatus
        from kb.task_executor import task_executor, is_scheduler_running

        queue = TaskQueue()
        task = queue.get_task(task_id)

        if task and task.status == TaskStatus.RUNNING.value:
            # Only mark as orphan if scheduler is not running AND task not in local _running_tasks
            # Scheduler runs in separate process, so its _running_tasks is different
            if (
                task_id not in task_executor._running_tasks
                and not is_scheduler_running()
            ):
                queue.update_status(
                    task_id,
                    TaskStatus.FAILED.value,
                    "孤儿任务（执行进程已终止）",
                )
                task = queue.get_task(task_id)

        return task.to_dict() if task else None

    @staticmethod
    def cancel(task_id: str) -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus
        from kb.task_executor import task_executor

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status == TaskStatus.CANCELLED.value:
            return {
                "status": "cancelled",
                "task_id": task_id,
                "message": "任务已取消",
            }

        if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
            return {
                "status": task.status,
                "task_id": task_id,
                "message": f"任务已完成，无法取消",
            }

        queue.update_status(task_id, TaskStatus.CANCELLED.value, "已取消")
        task_executor.cancel_task(task_id)

        return {
            "status": "cancelled",
            "task_id": task_id,
            "message": "已取消任务",
        }

    @staticmethod
    def cleanup_orphan_task(task_id: str) -> bool:
        from kb.task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        task = queue.get_task(task_id)

        if task and task.status == TaskStatus.RUNNING.value:
            queue.update_status(
                task_id,
                TaskStatus.FAILED.value,
                "孤儿任务（执行进程已终止）",
            )
            return True
        return False

    @staticmethod
    def pause(task_id: str) -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus
        from kb.task_executor import task_executor

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status != TaskStatus.RUNNING.value:
            return {
                "status": task.status,
                "task_id": task_id,
                "message": f"任务当前状态为 {task.status}，无法暂停",
            }

        queue.update_status(task_id, TaskStatus.PAUSED.value, "已暂停")
        task_executor.pause_task(task_id)
        return {
            "status": "paused",
            "task_id": task_id,
            "message": "任务已暂停",
        }

    @staticmethod
    def resume(task_id: str) -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus
        from kb.task_executor import task_executor

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status != TaskStatus.PAUSED.value:
            return {
                "status": task.status,
                "task_id": task_id,
                "message": f"任务当前状态为 {task.status}，无法恢复",
            }

        queue.update_status(task_id, TaskStatus.RUNNING.value, "继续执行")
        task_executor.resume_task(task_id)
        return {
            "status": "running",
            "task_id": task_id,
            "message": "任务已恢复",
        }

    @staticmethod
    def pause_all(status: str = "running") -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        tasks = queue.list_tasks(status=status)
        paused = []
        failed = []

        for task in tasks:
            if task.status == TaskStatus.RUNNING.value:
                queue.update_status(task.task_id, TaskStatus.PAUSED.value, "已暂停")
                paused.append(task.task_id)
            else:
                failed.append(task.task_id)

        return {
            "status": "completed",
            "paused": paused,
            "failed": failed,
            "message": f"已暂停 {len(paused)} 个任务，{len(failed)} 个无法暂停",
        }

    @staticmethod
    def resume_all() -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        tasks = queue.list_tasks(status="paused")
        resumed = []

        for task in tasks:
            queue.update_status(task.task_id, TaskStatus.RUNNING.value, "继续执行")
            resumed.append(task.task_id)

        return {
            "status": "completed",
            "resumed": resumed,
            "message": f"已恢复 {len(resumed)} 个任务",
        }

    @staticmethod
    def delete_all(status: str = "completed", cleanup: bool = False) -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        tasks = queue.list_tasks(status=status)
        deleted = []
        cleaned_results = []

        for task in tasks:
            try:
                if task.status == TaskStatus.RUNNING.value:
                    continue

                if cleanup:
                    sources = task.result.get("sources") if task.result else None
                    cleaned = TaskService._cleanup_task_data(
                        task.kb_id, task.task_type, sources=sources
                    )
                    cleaned_results.append(
                        {"task_id": task.task_id, "cleanup": cleaned}
                    )

                queue.delete_task(task.task_id)
                deleted.append(task.task_id)
            except Exception:
                pass

        result = {
            "status": "completed",
            "deleted": deleted,
            "message": f"已删除 {len(deleted)} 个任务",
        }

        if cleaned_results:
            result["cleaned"] = cleaned_results

        return result

    @staticmethod
    def cleanup_orphan_tasks(cleanup: bool = True) -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus
        from kb.task_executor import task_executor, is_scheduler_running

        queue = TaskQueue()
        tasks = queue.list_tasks(status="running")
        cleaned = []
        cleaned_data = []

        if not is_scheduler_running():
            for task in tasks:
                if task.task_id not in task_executor._running_tasks:
                    cleaned.append(task.task_id)
                    queue.update_status(
                        task.task_id,
                        TaskStatus.FAILED.value,
                        "孤儿任务（执行进程已终止）",
                    )

                    if cleanup:
                        sources = task.result.get("sources") if task.result else None
                        result = TaskService._cleanup_task_data(
                            task.kb_id, task.task_type, sources=sources
                        )
                        cleaned_data.append(
                            {"task_id": task.task_id, "cleanup": result}
                        )

        result = {
            "status": "completed",
            "cleaned": cleaned,
            "message": f"已清理 {len(cleaned)} 个孤儿任务",
        }

        if cleaned_data:
            result["cleaned_data"] = cleaned_data

        return result

    @staticmethod
    def delete(task_id: str, cleanup: bool = False) -> Dict[str, Any]:
        """删除任务（物理删除）

        Args:
            task_id: 任务ID
            cleanup: 是否清理关联的知识库数据
                    - True: 同时清空该知识库的 dedup 状态和向量数据
                    - False: 仅删除任务记录
        """
        from kb.task_queue import TaskQueue

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status == "running":
            raise ValueError(f"任务正在运行，无法删除: {task_id}")

        success = queue.delete_task(task_id)
        if not success:
            raise ValueError(f"删除失败: {task_id}")

        result = {"status": "deleted", "task_id": task_id, "message": "任务已删除"}

        if cleanup:
            sources = task.result.get("sources") if task.result else None
            cleaned = TaskService._cleanup_task_data(
                task.kb_id, task.task_type, sources=sources
            )
            result["cleanup"] = cleaned

        return result

    @staticmethod
    def _cleanup_task_data(
        kb_id: str, task_type: str, sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """清理任务产生的关联数据

        Args:
            kb_id: 知识库ID
            task_type: 任务类型
            sources: 要删除的源文件路径列表
        """
        from kb.deduplication import DeduplicationManager
        from kb.registry import get_storage_root

        cleaned = {"dedup_state": False, "vector_store": False, "deleted_nodes": 0}

        persist_dir = get_storage_root() / kb_id
        dedup_manager = DeduplicationManager(kb_id, persist_dir)

        if task_type == "rebuild":
            dedup_manager.clear()
            cleaned["dedup_state"] = True

            from kb.services import VectorStoreService

            vs = VectorStoreService.get_vector_store(kb_id)
            vs.delete_table()
            cleaned["vector_store"] = True
        elif sources:
            for source in sources:
                dedup_manager.remove_record(source)
            cleaned["dedup_state"] = True

            from kb.services import VectorStoreService

            vs = VectorStoreService.get_vector_store(kb_id)
            lance_store = vs._get_lance_vector_store()
            deleted = lance_store.delete_by_source(sources)
            cleaned["deleted_nodes"] = deleted
            cleaned["vector_store"] = deleted > 0

        return cleaned

    @staticmethod
    def run_task(task_id: str) -> Dict[str, Any]:
        from kb.task_executor import task_executor

        asyncio.run(task_executor.execute_task(task_id))
        task = TaskService.get_task(task_id)
        if task is None:
            raise ValueError(f"任务不存在: {task_id}")
        return task

    @staticmethod
    def wait_for_task(
        task_id: str, interval: float = 1.0, timeout: float = 0
    ) -> Dict[str, Any]:
        start = time.time()
        while True:
            task = TaskService.get_task(task_id)
            if task is None:
                raise ValueError(f"任务不存在: {task_id}")
            if task["status"] in {"completed", "failed", "cancelled"}:
                return task
            if timeout > 0 and time.time() - start >= timeout:
                return task
            time.sleep(interval)


class CategoryService:
    """分类规则服务"""

    @staticmethod
    def list_rules() -> Dict[str, Any]:
        from kb.database import init_category_rule_db

        rule_db = init_category_rule_db()
        rules = rule_db.get_all_rules()
        return {"rules": rules, "total": len(rules)}

    @staticmethod
    def sync_rules() -> Dict[str, Any]:
        from kb.obsidian_config import seed_mappings_to_db

        count = seed_mappings_to_db()
        return {
            "status": "success",
            "message": f"已同步 {count} 条分类规则到数据库",
            "count": count,
        }

    @staticmethod
    def add_rule(
        kb_id: str,
        rule_type: str,
        pattern: str,
        description: str = "",
        priority: int = 0,
    ) -> Dict[str, Any]:
        from kb.database import init_category_rule_db

        rule_db = init_category_rule_db()
        success = rule_db.add_rule(
            kb_id=kb_id,
            rule_type=rule_type,
            pattern=pattern,
            description=description,
            priority=priority,
        )
        return {
            "status": "success" if success else "error",
            "message": f"规则添加{'成功' if success else '失败'}",
        }

    @staticmethod
    def delete_rule(kb_id: str, rule_type: str, pattern: str) -> Dict[str, Any]:
        from kb.database import init_category_rule_db

        rule_db = init_category_rule_db()
        success = rule_db.delete_rule(kb_id, rule_type, pattern)
        return {
            "status": "success" if success else "error",
            "message": f"规则删除{'成功' if success else '失败'}",
        }

    @staticmethod
    def classify(
        folder_path: str, folder_description: str = "", use_llm: bool = True
    ) -> Dict[str, Any]:
        from kb.category_classifier import CategoryClassifier
        from kb.obsidian_config import find_kb_by_path

        matched_kbs = find_kb_by_path(folder_path)
        if matched_kbs and not use_llm:
            return {
                "kb_id": matched_kbs[0],
                "matched_by": "rule",
                "confidence": 1.0,
                "reason": f"文件夹路径匹配: {folder_path}",
            }

        if use_llm:
            try:
                classifier = CategoryClassifier()
                result = classifier.classify_folder_llm(
                    folder_path=folder_path,
                    folder_description=folder_description,
                )
                return {
                    "kb_id": result["kb_id"],
                    "matched_by": "llm",
                    "confidence": result["confidence"],
                    "reason": result["reason"],
                    "alternatives": matched_kbs if matched_kbs else None,
                }
            except Exception as e:
                return {
                    "error": f"LLM 分类失败: {str(e)}",
                    "alternatives": matched_kbs,
                }

        return {
            "kb_id": None,
            "matched_by": "none",
            "confidence": 0.0,
            "reason": "未找到匹配的知识库",
            "suggestion": "请手动指定知识库或使用 LLM 分类",
        }


class AdminService:
    """管理服务"""

    @staticmethod
    def list_tables() -> Dict[str, Any]:
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

        for root in [get_storage_root(), get_zotero_storage_root()]:
            if not root.exists():
                continue
            for child in root.iterdir():
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
        return KnowledgeBaseService.get_info(kb_id)

    @staticmethod
    def delete_table(kb_id: str) -> bool:
        return KnowledgeBaseService.delete(kb_id)
