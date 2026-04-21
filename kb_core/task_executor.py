"""
任务执行器

支持本地和远程 Ollama 并行处理。

================================================================================
任务执行流程 (Task Execution Flow)
================================================================================

入口: TaskExecutor.execute_task(task_id)
    │
    ├─ 验证任务状态 (必须为 PENDING)
    ├─ 创建取消/暂停事件
    └─ 分发到对应处理器:

  ┌──────────────────────────────────────────────────────────────────────────────┐
  │ task_type          │ 处理器                    │ 用途                      │
  ├──────────────────────────────────────────────────────────────────────────────┤
  │ zotero             │ _execute_zotero()         │ Zotero 文献导入            │
  │ obsidian           │ _execute_obsidian()       │ Obsidian 笔记导入          │
  │ obsidian_folder    │ _execute_obsidian()       │ Obsidian 文件夹导入        │
  │ generic            │ _execute_generic()        │ 通用文件导入               │
  │ selective          │ _execute_selective()      │ 选择性混合导入             │
  │ initialize         │ _execute_initialize()     │ 知识库初始化               │
  │ revector           │ _execute_revector()       │ 重新向量化                 │
  │ check_mark_failed  │ _execute_check_mark_failed() │ 检查缺失向量            │
  └──────────────────────────────────────────────────────────────────────────────┘

================================================================================
模型调用链路 (Model Invocation Chain)
================================================================================

  TaskExecutor._execute_*(task)
      │
      ├─ get_parallel_processor()
      │       │
      │       └─→ ParallelEmbeddingProcessor (单例, kb_processing/parallel_embedding.py)
      │               │
      │               ├─ _load_embedding_endpoints()
      │               │       ├─ ModelRegistry.get_by_type("embedding")  ← 从DB加载
      │               │       ├─ VendorDB.get(vendor_id)                  ← 从DB加载
      │               │       └─ SiliconFlow fallback (云端)
      │               │
      │               └─ process_batch_streaming(texts) 或 process_batch(texts)
      │                       │
      │                       └─→ 自适应负载均衡
      │                               ├─ Healthy Ollama endpoints (并行)
      │                               └─ SiliconFlow fallback (云端)
      │
      └─ create_ollama_embedding()  → OllamaEmbedder (rag/ollama_utils.py)
              ├─ 503 重试 + 指数退避
              ├─ 熔断器 (CircuitBreaker)
              └─ 请求队列 (OllamaRequestQueue)

================================================================================
导入链路 (Import Chain)
================================================================================

1. Obsidian 导入 (_execute_obsidian):
   文件扫描 → 读取文本 → LlamaDocument → NodeParser → ParallelEmbedding
     → LanceDB 写入 → Document DB 记录 → Topics 更新

2. Zotero 导入 (_execute_zotero):
   线程中运行: ZoteroImporter.import_collection()
     → PDF/附件下载 → 文本提取 → NodeParser → ParallelEmbedding
       → LanceDB 写入 → Document DB 记录 → Progress 更新

3. 通用文件导入 (_execute_generic):
   文件发现 → DocumentProcessor.process_file() → NodeParser → ParallelEmbedding
     → LanceDB 写入 → Document DB 记录

4. 选择性导入 (_execute_selective):
   按 item 类型分发:
   ├─ collection → ZoteroService.import_collection()
   ├─ item      → ZoteroService.import_item()
   ├─ folder    → ObsidianService.import_vault()
   └─ file      → GenericService.import_file()

================================================================================
环境变量依赖
================================================================================

直接从 .env 读取 (task_executor.py):
  CHUNK_SIZE, CHUNK_OVERLAP, PROGRESS_UPDATE_INTERVAL,
  MAX_CONCURRENT_TASKS, HEARTBEAT_INTERVAL, STALE_TASK_TIMEOUT

通过 Settings 间接读取 (rag/config.py):
  chunk_strategy, use_hyde, use_auto_merging, hybrid_search_* 等

模型配置 (从数据库读取，CLI 管理):
  vendor add ollama --api-base=http://localhost:11434
  model add ollama/bge-m3 --vendor ollama --type embedding

详细配置见: .env.example
"""

import asyncio
import queue
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from rag.logger import get_logger
from rag.config import get_settings

logger = get_logger(__name__)

# 配置常量（从 Settings 统一读取）
settings = get_settings()
CHUNK_SIZE = settings.chunk_size
CHUNK_OVERLAP = settings.chunk_overlap
PROGRESS_UPDATE_INTERVAL = settings.progress_update_interval
DEFAULT_MAX_CONCURRENT = settings.max_concurrent_tasks
HEARTBEAT_INTERVAL = settings.heartbeat_interval
STALE_TASK_TIMEOUT = settings.stale_task_timeout

from .task_queue import Task, TaskQueue, TaskStatus

if TYPE_CHECKING:
    from rag.vector_store import LanceDBVectorStore
    from kb_processing.parallel_embedding import EmbeddingResult


# =============================================================================
# 任务类型处理器注册表
# =============================================================================

class TaskHandlerRegistry:
    """任务处理器注册表 - 便于以后拆分为独立文件"""

    _handlers: Dict[str, str] = {
        "zotero": "_execute_zotero",
        "obsidian": "_execute_obsidian",
        "obsidian_folder": "_execute_obsidian",
        "generic": "_execute_generic",
        "initialize": "_execute_initialize",
        "selective": "_execute_selective",
        "revector": "_execute_revector",
        "check_mark_failed": "_execute_check_mark_failed",
    }

    @classmethod
    def get_handler_method(cls, task_type: str) -> str:
        if task_type not in cls._handlers:
            raise ValueError(f"Unknown task type: {task_type}")
        return cls._handlers[task_type]


# =============================================================================
# TaskExecutor
# =============================================================================

class TaskExecutor:
    """任务执行器 - 支持本地/远程 Ollama 并行处理"""

    def __init__(self) -> None:
        from .task_queue import TaskQueue

        self.queue: TaskQueue = TaskQueue()
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}
        self._pause_events: Dict[str, asyncio.Event] = {}
        self._paused_flags: Dict[str, bool] = {}

    async def execute_task(self, task_id: str) -> None:
        """执行任务"""

        task = self.queue.get_task(task_id)
        if not task:
            logger.warning(f"任务不存在: {task_id}")
            return

        if task.status != TaskStatus.PENDING.value:
            logger.debug(f"任务状态不是 pending: {task_id} ({task.status})")
            return

        self._cancel_events[task_id] = asyncio.Event()
        self._pause_events[task_id] = asyncio.Event()
        self._paused_flags[task_id] = False

        try:
            self.queue.start_task(task_id)
            await asyncio.sleep(0)
            if (
                self._cancel_events.get(task_id)
                and self._cancel_events[task_id].is_set()
            ):
                raise asyncio.CancelledError("取消已请求")
            if self._pause_events.get(task_id) and self._pause_events[task_id].is_set():
                while (
                    self._pause_events.get(task_id)
                    and self._pause_events[task_id].is_set()
                ):
                    await asyncio.sleep(0.5)
            await self._update_heartbeat(task_id)
            await self._notify_progress(task_id)

            handler_method = TaskHandlerRegistry.get_handler_method(task.task_type)
            await getattr(self, handler_method)(task)

        except asyncio.CancelledError:
            self.queue.complete_task(task_id, error="任务被取消")
            logger.info(f"任务已取消: {task_id}")
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"任务执行失败: {task_id} - {error_msg}", exc_info=True)
            self.queue.complete_task(task_id, error=error_msg)
        finally:
            self._running_tasks.pop(task_id, None)
            self._cancel_events.pop(task_id, None)
            self._pause_events.pop(task_id, None)
            self._paused_flags.pop(task_id, None)

    async def _notify_progress(self, task_id: str) -> None:
        """通知进度更新"""
        try:
            task = self.queue.get_task(task_id)
            if task:
                from kb_core.websocket_manager import ws_manager

                await ws_manager.send_task_update(task_id, task.to_dict())
        except Exception as e:
            logger.debug(f"进度通知失败: {e}")

    async def _update_and_notify(self, task_id: str, **kwargs) -> None:
        self.queue.update_progress(task_id, **kwargs)
        await self._notify_progress(task_id)

    async def _update_heartbeat(self, task_id: str) -> None:
        """更新任务心跳"""
        try:
            self.queue.update_heartbeat(task_id)
        except Exception as e:
            logger.debug(f"心跳更新失败: {e}")

    async def _check_cancelled(self, task_id: str) -> bool:
        """检查是否取消"""
        if task_id in self._cancel_events:
            if self._cancel_events[task_id].is_set():
                return True

        task = self.queue.get_task(task_id)
        if task and task.status == "cancelled":
            return True

        return False

    async def _check_paused(self, task_id: str) -> bool:
        """检查是否暂停，如果暂停则等待恢复或取消"""
        task = self.queue.get_task(task_id)
        if task and task.status == "cancelled":
            if task_id in self._paused_flags:
                self._paused_flags[task_id] = False
            return True

        if task and task.status == "paused":
            if task_id not in self._pause_events:
                self._pause_events[task_id] = asyncio.Event()
                self._pause_events[task_id].set()
            if task_id not in self._paused_flags:
                self._paused_flags[task_id] = False

        if task_id not in self._pause_events:
            return False

        if not self._pause_events[task_id].is_set():
            return False

        self._paused_flags[task_id] = True

        while self._pause_events[task_id].is_set():
            task = self.queue.get_task(task_id)
            if task and task.status == "cancelled":
                self._paused_flags[task_id] = False
                return True
            if (
                self._cancel_events.get(task_id)
                and self._cancel_events[task_id].is_set()
            ):
                self._paused_flags[task_id] = False
                return True
            await asyncio.sleep(0.5)

        self._paused_flags[task_id] = False
        self.queue.update_status(task_id, "running", "继续执行")
        return False

    def _save_partial_progress(
        self,
        task_id: str,
        kb_id: str,
        processed_sources: List[str],
        processed_files: int,
        processed_chunks: int,
        error_msg: str = "任务已取消（部分数据已处理）",
    ) -> None:
        """保存部分进度，用于取消/失败时"""
        self.queue.complete_task(
            task_id,
            result={
                "sources": processed_sources,
                "partial": True,
                "partial_sources": processed_sources,
                "processed_files": processed_files,
                "processed_chunks": processed_chunks,
            },
            error=error_msg,
        )

    def _get_vector_store(self, kb_id: str) -> "LanceDBVectorStore":
        """获取向量存储（使用服务层）"""
        from .services import VectorStoreService

        return VectorStoreService.get_vector_store(kb_id)

    def _get_vault_root(self) -> Path:
        """获取 Vault 根目录"""
        from kb_core.registry import get_vault_root

        return get_vault_root()

    def _update_kb_topics(self, kb_id: str, has_new_docs: bool = True) -> None:
        """按需更新知识库 topics"""
        try:
            from kb_analysis.topic_analyzer import analyze_and_update_topics

            topics = analyze_and_update_topics(kb_id, has_new_docs=has_new_docs)
            if topics:
                logger.info(f"KB {kb_id} topics 已处理: {len(topics)} 个")
        except Exception as e:
            logger.warning(f"更新 KB topics 失败 {kb_id}: {e}")

    def _should_refresh_topics(self, params: Dict[str, Any]) -> bool:
        """检查是否应该刷新 topics
        
        Args:
            params: 任务参数字典
            
        Returns:
            是否刷新
        """
        return bool(params.get("refresh_topics", True))

    # ==================== Obsidian 导入 ====================

    async def _execute_obsidian(self, task: "Task") -> None:
        """
        执行 Obsidian 导入（并行多端点版本）

        架构：
        - documents 表：串行访问（保护共享资源）
        - Embedding：并行处理（本地+远程同时工作）
        - LanceDB 写入：串行（通过 WriteQueue）
        """
        from kb_core.registry import KnowledgeBaseRegistry
        from .database import init_document_db
        from llama_index.core.schema import Document as LlamaDocument
        from kb_processing.parallel_embedding import get_parallel_processor
        from rag.config import get_settings

        kb_id = task.kb_id
        params = task.params
        rebuild = params.get("rebuild", False)

        await self._update_and_notify(task.task_id, message=f"开始导入: {kb_id}")

        registry = KnowledgeBaseRegistry()
        kb = registry.get(kb_id)
        vault_root = (
            Path(params.get("vault_path")).expanduser()
            if params.get("vault_path")
            else self._get_vault_root()
        )
        folder_path = params.get("folder_path") or params.get("folder")
        recursive = params.get("recursive", True)
        if not kb and not folder_path:
            raise ValueError(f"知识库不存在且未提供 folder_path: {kb_id}")
        persist_dir = (
            Path(params.get("persist_dir")).expanduser()
            if params.get("persist_dir")
            else self._get_vector_store(kb_id).persist_dir
        )

        vs = self._get_vector_store(kb_id)
        doc_db = init_document_db()

        if rebuild:
            try:
                vs.delete_table()
                await self._update_and_notify(task.task_id, message="已清空旧数据")
            except Exception as e:
                logger.warning(f"清空旧数据失败: {e}")

        all_files: List[Path] = []
        if folder_path:
            source_paths = [vault_root / folder_path]
        else:
            source_paths = kb.source_paths_abs(vault_root)

        for source_path in source_paths:
            if source_path.exists():
                pattern = (
                    source_path.rglob("*.md") if recursive else source_path.glob("*.md")
                )
                all_files.extend(pattern)

        await self._update_and_notify(
            task.task_id,
            total=len(all_files),
            message=f"扫描到 {len(all_files)} 个文件",
        )

        files_to_process: List[Tuple[str, Path]] = []
        hash_tool = None
        try:
            from kb_processing.document_processor import DocumentProcessor

            hash_tool = DocumentProcessor().compute_file_hash
        except Exception:
            pass

        for file_path in all_files:
            try:
                rel_path = str(file_path.relative_to(vault_root))
            except ValueError:
                rel_path = str(file_path)

            existing = doc_db.get_by_source_path(kb_id, str(file_path))
            if not existing:
                files_to_process.append((rel_path, file_path))
            elif rebuild:
                files_to_process.append((rel_path, file_path))
            else:
                current_hash = ""
                if hash_tool:
                    try:
                        current_hash = hash_tool(str(file_path))
                    except Exception:
                        pass
                if existing.get("file_hash") != current_hash:
                    files_to_process.append((rel_path, file_path))

        if not files_to_process:
            self.queue.complete_task(task.task_id, result={"message": "没有变更"})
            return

        await self._update_and_notify(
            task.task_id, message=f"待处理 {len(files_to_process)} 个文件"
        )

        lance_store = vs._get_lance_vector_store()
        from kb_processing.document_processor import get_node_parser
        settings = get_settings()
        node_parser = get_node_parser(
            strategy=settings.chunk_strategy,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            hierarchical_chunk_sizes=settings.hierarchical_chunk_sizes,
        )

        processed_sources = []

        embed_processor = get_parallel_processor()

        processed_files = 0
        processed_chunks = 0
        last_heartbeat_file_count = 0

        await self._update_and_notify(
            task.task_id, message=f"开始处理 {len(files_to_process)} 个文件"
        )

        for rel_path, abs_path in files_to_process:
            if await self._check_cancelled(task.task_id):
                self._save_partial_progress(
                    task.task_id,
                    kb_id,
                    processed_sources,
                    processed_files,
                    processed_chunks,
                    "任务已取消（部分数据已处理）",
                )
                return
            if await self._check_paused(task.task_id):
                self._save_partial_progress(
                    task.task_id,
                    kb_id,
                    processed_sources,
                    processed_files,
                    processed_chunks,
                    "任务已暂停（部分数据已处理）",
                )
                return

            try:
                content = abs_path.read_text(encoding="utf-8", errors="ignore")

                doc = LlamaDocument(
                    text=content,
                    metadata={
                        "source": "obsidian",
                        "file_path": str(abs_path),
                        "relative_path": rel_path,
                    },
                    id_=rel_path,
                )

                nodes = node_parser.get_nodes_from_documents([doc])

                if nodes:
                    current_hash = ""
                    if hash_tool:
                        try:
                            current_hash = hash_tool(str(abs_path))
                        except Exception:
                            pass

                    texts = [node.get_content() for node in nodes]

                    results: List[Optional[EmbeddingResult]] = [None] * len(texts)
                    async for idx, result in embed_processor.process_batch_streaming(
                        texts
                    ):
                        results[idx] = result

                    failed_ids = []
                    for j in range(len(results)):
                        result_item = results[j]
                        if result_item is None:
                            failed_ids.append(nodes[j].node_id)
                            continue
                        _, embedding, _ = result_item
                        if embedding is None or all(v == 0.0 for v in embedding):
                            failed_ids.append(nodes[j].node_id)
                            continue
                        nodes[j].embedding = embedding

                    try:
                        from .document_chunk_service import DocumentChunkService
                        doc_chunk_svc = DocumentChunkService(kb_id)
                        doc_record = doc_chunk_svc.create_document(
                            source_file=rel_path,
                            source_path=str(abs_path),
                            file_hash=current_hash if current_hash else "",
                            nodes=nodes,
                            file_size=abs_path.stat().st_size if abs_path.exists() else 0,
                            failed_node_ids=failed_ids if failed_ids else None,
                        )
                        if not doc_record:
                            logger.warning(f"SQLite 保存失败，跳过文档: {rel_path}")
                            continue
                    except Exception as e:
                        logger.warning(f"SQLite 保存失败，跳过文档: {rel_path}, 错误: {e}")
                        continue

                    try:
                        processor = DocumentProcessor()
                        success_count, skipped, _ = processor._upsert_nodes(
                            lance_store, nodes
                        )
                    except Exception as write_ex:
                        logger.warning(f"LanceDB 写入失败（SQLite 已保存）: {rel_path}, 错误: {write_ex}")
                        continue

                    processed_chunks += success_count

                processed_sources.append(str(abs_path))
                processed_files += 1

                if processed_files % PROGRESS_UPDATE_INTERVAL == 0:
                    await self._update_and_notify(
                        task.task_id,
                        message=f"处理 {processed_files}/{len(files_to_process)} ({processed_chunks} chunks)",
                    )

                if (
                    processed_files - last_heartbeat_file_count
                    >= PROGRESS_UPDATE_INTERVAL
                ):
                    await self._update_heartbeat(task.task_id)
                    last_heartbeat_file_count = processed_files

            except Exception as e:
                logger.warning(f"处理失败 {rel_path}: {e}")

        stats = embed_processor.get_stats()
        failure_stats = embed_processor.get_failure_stats()
        logger.info(f"端点使用统计: {stats}, 失败统计: {failure_stats}")

        settings = get_settings()

        vs.set_chunk_strategy(settings.chunk_strategy)

        self.queue.complete_task(
            task.task_id,
            result={
                "kb_id": kb_id,
                "files": processed_files,
                "nodes": processed_chunks,
                "sources": processed_sources,
                "endpoint_stats": stats,
                "chunk_strategy": settings.chunk_strategy,
            },
        )

        if self._should_refresh_topics(params):
            self._update_kb_topics(kb_id, has_new_docs=processed_files > 0)

    # ==================== 选择性导入 ====================

    async def _execute_selective(self, task: "Task") -> None:
        """执行选择性导入（支持混合来源）"""
        from .services import (
            ZoteroService,
            ObsidianService,
            GenericService,
            KnowledgeBaseService,
        )
        from .task_queue import FileStatus

        kb_id = task.kb_id
        params = task.params
        task_id = task.task_id
        items = params.get("items", [])
        prefix = params.get("prefix", "[kb]")

        logger.info(f"[{task_id}] 开始选择性导入: kb_id={kb_id}, items={len(items)}")

        if not items:
            self.queue.complete_task(
                task_id, result={"files": 0, "nodes": 0, "message": "没有要导入的项目"}
            )
            return

        import hashlib

        total_items = len(items)
        await self._update_and_notify(
            task_id, total=total_items, message=f"准备导入 {total_items} 个项目"
        )

        file_list = []
        for idx, item in enumerate(items):
            item_type = item.get("type", "")
            item_id = str(item.get("id") or item.get("path") or f"item_{idx}")
            file_name = f"{item_type}: {item_id}"
            file_id = hashlib.md5(
                f"{task_id}:{item_type}:{item_id}".encode()
            ).hexdigest()[:12]
            file_list.append(
                {
                    "file_id": file_id,
                    "file_name": file_name,
                    "status": FileStatus.PENDING.value,
                    "total_chunks": 0,
                    "processed_chunks": 0,
                    "db_written": False,
                    "error": None,
                }
            )

        self.queue.set_file_progress(task_id, file_list)

        item_titles = {}
        try:
            from kb_zotero.processor import ZoteroImporter

            for item in items:
                if item.get("type") == "item":
                    item_id = item.get("id")
                    if item_id:
                        try:
                            importer = ZoteroImporter(kb_id=kb_id)
                            zotero_item = importer.get_item(int(item_id), prefix=prefix)
                            if zotero_item and zotero_item.title:
                                item_titles[str(item_id)] = zotero_item.title
                            importer.close()
                        except Exception as e:
                            logger.debug(
                                f"Failed to fetch title for item {item_id}: {e}"
                            )
        except Exception as e:
            logger.debug(f"Failed to pre-fetch Zotero titles: {e}")

        if item_titles:
            for idx, item in enumerate(items):
                if item.get("type") == "item":
                    item_id = item.get("id")
                    if item_id and str(item_id) in item_titles:
                        file_id = hashlib.md5(
                            f"{task_id}:{item.get('type')}:{item_id}".encode()
                        ).hexdigest()[:12]
                        self.queue.update_file_progress(
                            task_id,
                            file_id,
                            file_name=item_titles[str(item_id)],
                        )

        stats = {"files": 0, "nodes": 0, "failed": 0, "processed_sources": []}

        for i, item in enumerate(items):
            if await self._check_cancelled(task_id):
                self.queue.complete_task(
                    task_id,
                    result={
                        **stats,
                        "partial": True,
                        "file_progress": self.queue.get_file_progress(task_id),
                    },
                    error="任务已取消",
                )
                return
            if await self._check_paused(task_id):
                self.queue.complete_task(
                    task_id,
                    result={
                        **stats,
                        "partial": True,
                        "file_progress": self.queue.get_file_progress(task_id),
                    },
                    error="任务已暂停",
                )
                return

            item_type = item.get("type", "")
            item_id = item.get("id") or item.get("path", "")
            file_id = file_list[i]["file_id"]

            self.queue.update_file_progress(
                task_id, file_id, status=FileStatus.PROCESSING.value
            )
            await self._update_and_notify(
                task_id,
                current=i + 1,
                total=total_items,
                message=f"[{i + 1}/{total_items}] 处理: {item_type} - {item_id}",
            )

            nodes_count = 0
            db_written = False
            error_msg = None

            try:
                if item_type == "collection":
                    result = ZoteroService.import_collection(
                        kb_id=kb_id,
                        collection_id=item.get("id"),
                        collection_name=item.get("name", "Unknown"),
                        refresh_topics=False,
                    )
                    stats["files"] += result.get("items", 0)
                    stats["nodes"] += result.get("nodes", 0)
                    nodes_count = result.get("nodes", 0)
                    db_written = result.get("nodes", 0) > 0
                    stats["processed_sources"].extend(
                        result.get("processed_sources", [])
                    )
                    self.queue.update_file_progress(
                        task_id,
                        file_id,
                        status=FileStatus.COMPLETED.value,
                        total_chunks=nodes_count,
                        processed_chunks=nodes_count,
                        db_written=db_written,
                    )

                elif item_type == "item":
                    logger.info(
                        f"[{task_id}] 处理 Zotero 文献: item_id={item_id}, prefix={prefix}, options={item.get('options', {})}"
                    )
                    item_options = item.get("options", {})
                    result = ZoteroService.import_item(
                        kb_id=kb_id,
                        item_id=item.get("id"),
                        options=item_options,
                        refresh_topics=False,
                        prefix=prefix,
                    )
                    logger.info(
                        f"[{task_id}] Zotero 文献导入结果: nodes={result.get('nodes', 0)}, items={result.get('items', 0)}"
                    )
                    stats["files"] += (
                        result.get("items", 0) if result.get("nodes", 0) > 0 else 0
                    )
                    stats["nodes"] += result.get("nodes", 0)
                    nodes_count = result.get("nodes", 0)
                    if nodes_count == 0:
                        stats["failed"] += 1
                    db_written = nodes_count > 0
                    stats["processed_sources"].extend(
                        result.get("processed_sources", [])
                    )
                    self.queue.update_file_progress(
                        task_id,
                        file_id,
                        status=FileStatus.COMPLETED.value
                        if nodes_count > 0
                        else FileStatus.FAILED.value,
                        total_chunks=nodes_count,
                        processed_chunks=nodes_count,
                        db_written=db_written,
                        error=""
                        if nodes_count > 0
                        else (result.get("error") or "No chunks processed"),
                    )

                elif item_type == "folder":
                    vault_path = item.get("vault_path")
                    folder_path = item.get("path")
                    if vault_path and folder_path:
                        result = ObsidianService.import_vault(
                            kb_id=kb_id,
                            vault_path=vault_path,
                            folder_path=folder_path,
                            refresh_topics=False,
                        )
                        stats["files"] += (
                            result.get("files", 0) if result.get("nodes", 0) > 0 else 0
                        )
                        stats["nodes"] += result.get("nodes", 0)
                        nodes_count = result.get("nodes", 0)
                        if nodes_count == 0:
                            stats["failed"] += 1
                        db_written = nodes_count > 0
                        stats["processed_sources"].extend(
                            result.get("processed_sources", [])
                        )
                        self.queue.update_file_progress(
                            task_id,
                            file_id,
                            status=FileStatus.COMPLETED.value
                            if nodes_count > 0
                            else FileStatus.FAILED.value,
                            total_chunks=nodes_count,
                            processed_chunks=nodes_count,
                            db_written=db_written,
                            error="" if nodes_count > 0 else "No chunks processed",
                        )

                elif item_type == "file":
                    path = item.get("path")
                    if path:
                        result = GenericService.import_file(
                            kb_id=kb_id,
                            path=path,
                            refresh_topics=False,
                        )
                        stats["files"] += (
                            result.get("files", 0) if result.get("nodes", 0) > 0 else 0
                        )
                        stats["nodes"] += result.get("nodes", 0)
                        nodes_count = result.get("nodes", 0)
                        if nodes_count == 0:
                            stats["failed"] += 1
                        db_written = nodes_count > 0
                        stats["processed_sources"].append(path)
                        self.queue.update_file_progress(
                            task_id,
                            file_id,
                            status=FileStatus.COMPLETED.value
                            if nodes_count > 0
                            else FileStatus.FAILED.value,
                            total_chunks=nodes_count,
                            processed_chunks=nodes_count,
                            db_written=db_written,
                            error="" if nodes_count > 0 else "No chunks processed",
                        )

            except Exception as e:
                logger.warning(f"[{task_id}] 处理项目失败 {item_type}/{item_id}: {e}")
                stats["failed"] += 1
                error_msg = f"{type(e).__name__}: {str(e)}"
                self.queue.update_file_progress(
                    task_id,
                    file_id,
                    status=FileStatus.FAILED.value,
                    error=error_msg,
                )

            processed_chunks, total_chunks = self.queue.compute_chunk_progress(task_id)
            progress_pct = (
                int(processed_chunks / total_chunks * 100) if total_chunks > 0 else 0
            )
            await self._update_and_notify(
                task_id,
                progress=progress_pct,
                current=i + 1,
                total=total_items,
                message=f"[{i + 1}/{total_items}] 处理: {item_type} - {item_id} ({processed_chunks}/{total_chunks} chunks)",
            )

            if (i + 1) % 5 == 0:
                await self._update_heartbeat(task_id)

        if params.get("refresh_topics", True):
            self._update_kb_topics(kb_id, has_new_docs=stats["files"] > 0)

        all_failed = stats["failed"] > 0 and stats["files"] == 0
        error_msg = f"所有项目都失败了 ({stats['failed']} 个)" if all_failed else None

        processed_chunks, total_chunks = self.queue.compute_chunk_progress(task_id)
        file_progress = self.queue.get_file_progress(task_id)

        self.queue.complete_task(
            task_id,
            result={
                "kb_id": kb_id,
                "files": stats["files"],
                "nodes": stats["nodes"],
                "failed": stats["failed"],
                "sources": stats["processed_sources"],
                "processed_chunks": processed_chunks,
                "total_chunks": total_chunks,
                "file_progress": file_progress,
            },
            error=error_msg,
        )

    async def _execute_revector(self, task: "Task") -> None:
        """执行重新向量化任务（处理 pending、failed 和 orphaned success chunks）- 批量优化版"""
        from .database import init_chunk_db
        from kb_storage.lance_crud import LanceCRUDService
        from kb_processing.parallel_embedding import get_parallel_processor

        kb_id = task.kb_id
        params = task.params
        task_id = task.task_id

        include_pending = params.get("include_pending", True)
        include_failed = params.get("include_failed", True)
        include_embedded = params.get("include_embedded", False)
        batch_size = params.get("batch_size", 100)
        chunk_batch_size = params.get("chunk_batch_size", 500)
        limit = params.get("limit", 50000)

        logger.info(
            f"[{task_id}] 开始重新向量化任务: kb_id={kb_id}, "
            f"include_pending={include_pending}, include_failed={include_failed}, "
            f"include_embedded={include_embedded}, limit={limit}, "
            f"batch_size={batch_size}, chunk_batch_size={chunk_batch_size}"
        )

        chunk_db = init_chunk_db()
        processor = get_parallel_processor()

        if not processor.endpoints:
            self.queue.complete_task(
                task_id,
                error="没有可用的 embedding 端点",
            )
            return

        pending_chunks = []
        failed_chunks = []
        embedded_chunks = []

        if include_pending:
            pending_chunks = chunk_db.get_unembedded(kb_id, limit=limit)

        if include_failed:
            failed_chunks = chunk_db.get_failed_chunks(kb_id, limit=limit)

        if include_embedded:
            embedded_chunks = chunk_db.get_embedded(kb_id, limit=limit)

        all_chunks = pending_chunks + failed_chunks + embedded_chunks
        total_chunks = len(all_chunks)

        if total_chunks == 0:
            self.queue.complete_task(
                task_id,
                result={
                    "kb_id": kb_id,
                    "processed": 0,
                    "pending": 0,
                    "failed": 0,
                    "embedded": 0,
                    "success": 0,
                    "skipped": 0,
                },
            )
            return

        await self._update_and_notify(
            task_id,
            total=total_chunks,
            message=f"准备重新向量化 {total_chunks} 个 chunks",
        )

        stats = {
            "pending": len(pending_chunks),
            "failed": len(failed_chunks),
            "embedded": len(embedded_chunks),
            "success": 0,
            "skipped": 0,
        }

        processed = 0
        failed_ids = []

        for batch_start in range(0, total_chunks, chunk_batch_size):
            if await self._check_cancelled(task_id):
                self.queue.complete_task(
                    task_id,
                    result={
                        **stats,
                        "processed": processed,
                        "message": "任务已取消",
                    },
                    error="任务已取消",
                )
                return

            if await self._check_paused(task_id):
                self.queue.complete_task(
                    task_id,
                    result={
                        **stats,
                        "processed": processed,
                        "message": "任务已暂停",
                    },
                    error="任务已暂停",
                )
                return

            batch_end = min(batch_start + chunk_batch_size, total_chunks)
            chunk_batch = all_chunks[batch_start:batch_end]

            texts = [chunk["text"] for chunk in chunk_batch]
            chunk_ids = [chunk["id"] for chunk in chunk_batch]
            doc_ids = [chunk["doc_id"] for chunk in chunk_batch]

            embedding_results = await processor.process_batch(texts)

            batch_failed_ids = []
            for idx, (ep_name, embedding, error) in enumerate(embedding_results):
                chunk_id = chunk_ids[idx]

                try:
                    if error:
                        raise Exception(error)

                    if all(v == 0.0 for v in embedding):
                        raise Exception("Embedding returned zero vector")

                    LanceCRUDService.upsert_vector(
                        chunk_id, doc_ids[idx], embedding, kb_id=kb_id
                    )
                    try:
                        chunk_db.mark_embedded(chunk_id)
                    except Exception as mark_err:
                        try:
                            LanceCRUDService.delete_by_chunk_ids(kb_id, [chunk_id])
                        except Exception:
                            pass
                        raise Exception(f"DB update failed after vector write: {mark_err}")
                    stats["success"] += 1

                except Exception as e:
                    logger.warning(f"Re-embed chunk {chunk_id} failed: {e}")
                    batch_failed_ids.append(chunk_id)
                    stats["skipped"] += 1

            failed_ids.extend(batch_failed_ids)
            processed += len(chunk_batch)

            if batch_failed_ids:
                chunk_db.mark_failed_bulk(batch_failed_ids)

            progress_pct = int(processed / total_chunks * 100)
            await self._update_and_notify(
                task_id,
                progress=progress_pct,
                current=processed,
                total=total_chunks,
                message=f"进度: {processed}/{total_chunks} (成功: {stats['success']}, 失败: {stats['skipped']})",
            )
            await self._update_heartbeat(task_id)

        remaining_pending = len(chunk_db.get_unembedded(kb_id, limit=1))
        remaining_failed = len(chunk_db.get_failed_chunks(kb_id, limit=1))
        remaining_embedded = len(chunk_db.get_embedded(kb_id, limit=1))

        skipped = stats["skipped"]
        error_msg = f"{skipped} chunks failed to embed" if skipped > 0 else None

        self.queue.complete_task(
            task_id,
            result={
                "kb_id": kb_id,
                "processed": processed,
                "pending": stats["pending"],
                "failed": stats["failed"],
                "embedded": stats["embedded"],
                "success": stats["success"],
                "skipped": skipped,
                "remaining_pending": remaining_pending,
                "remaining_failed": remaining_failed,
                "remaining_embedded": remaining_embedded,
            },
            error=error_msg,
        )

    async def _execute_check_mark_failed(self, task: "Task") -> None:
        """执行检查并标记缺失向量的 chunks 为失败"""
        kb_id = task.kb_id
        task_id = task.task_id
        params = task.params
        limit = params.get("limit", 200000)

        logger.info(f"[{task_id}] 开始检查并标记缺失向量: kb_id={kb_id}, limit={limit}")

        from .database import init_chunk_db

        chunk_db = init_chunk_db()

        total_before = 0
        failed_before = 0
        success_before = 0

        with chunk_db.db.session_scope() as session:
            from .database import ChunkModel
            from sqlalchemy import select, func

            total_before = session.scalar(
                select(func.count()).where(ChunkModel.kb_id == kb_id)
            )
            failed_before = session.scalar(
                select(func.count()).where(
                    ChunkModel.kb_id == kb_id, ChunkModel.embedding_generated == 2
                )
            )
            success_before = session.scalar(
                select(func.count()).where(
                    ChunkModel.kb_id == kb_id, ChunkModel.embedding_generated == 1
                )
            )

        await self._update_and_notify(
            task_id,
            total=1,
            message=f"开始检查 {total_before} 个 chunks...",
        )

        result = chunk_db.mark_chunks_missing_from_lance(kb_id, limit=limit)

        total_after = 0
        failed_after = 0
        success_after = 0

        with chunk_db.db.session_scope() as session:
            from .database import ChunkModel
            from sqlalchemy import select, func

            total_after = session.scalar(
                select(func.count()).where(ChunkModel.kb_id == kb_id)
            )
            failed_after = session.scalar(
                select(func.count()).where(
                    ChunkModel.kb_id == kb_id, ChunkModel.embedding_generated == 2
                )
            )
            success_after = session.scalar(
                select(func.count()).where(
                    ChunkModel.kb_id == kb_id, ChunkModel.embedding_generated == 1
                )
            )

        marked = result["marked_failed"]
        checked = result["total_checked"]

        logger.info(
            f"[{task_id}] 检查完成: checked={checked}, marked_failed={marked}, "
            f"failed: {failed_before} -> {failed_after}, success: {success_before} -> {success_after}"
        )

        self.queue.complete_task(
            task_id,
            result={
                "kb_id": kb_id,
                "checked": checked,
                "marked_failed": marked,
                "failed_before": failed_before,
                "failed_after": failed_after,
                "success_before": success_before,
                "success_after": success_after,
                "message": f"检查完成: 标记 {marked} 个 chunks 为失败 (共检查 {checked} 个)",
            },
        )

    # ==================== 其他任务类型 ====================

    async def _execute_zotero(self, task: "Task") -> None:
        """执行 Zotero 导入"""
        import threading

        from kb_zotero.processor import ZoteroImporter
        from kb_processing.document_processor import DocumentProcessorConfig, ProcessingProgress
        from kb_processing.parallel_embedding import get_parallel_processor
        from rag.ollama_utils import create_parallel_ollama_embedding

        kb_id = task.kb_id
        params = task.params
        task_id = task.task_id

        collection_id = params.get("collection_id")
        collection_name = params.get("collection_name", "Unknown")
        rebuild = params.get("rebuild", False)

        logger.info(
            f"[{task_id}] 开始 Zotero 导入任务: kb_id={kb_id}, collection={collection_name}"
        )

        await self._update_and_notify(
            task_id, message=f"准备导入 Zotero: {collection_name}"
        )

        vs = None
        embed_processor = None
        importer = None

        try:
            vs = self._get_vector_store(kb_id)
            logger.debug(f"[{task_id}] 向量存储初始化完成: {kb_id}")

            embed_model = create_parallel_ollama_embedding()
            logger.debug(f"[{task_id}] Embedding 模型创建完成")

            embed_processor = get_parallel_processor()
            logger.debug(f"[{task_id}] 并行 Embedding 处理器初始化完成")

            config = DocumentProcessorConfig(
                chunk_size=params.get("chunk_size") or CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
                chunk_strategy=params.get("chunk_strategy") or "hierarchical",
                hierarchical_chunk_sizes=params.get("hierarchical_chunk_sizes"),
            )
            importer = ZoteroImporter(config=config, kb_id=kb_id)
            logger.debug(f"[{task_id}] ZoteroImporter 初始化完成")

            if not collection_id and params.get("collection_name"):
                logger.debug(
                    f"[{task_id}] 通过名称查找收藏夹 ID: {params['collection_name']}"
                )
                result = importer.get_collection_by_name(params["collection_name"])
                if result and "collectionID" in result:
                    collection_id = result["collectionID"]
                    logger.debug(f"[{task_id}] 找到收藏夹 ID: {collection_id}")
                elif result and "multiple" in result:
                    raise ValueError(
                        f"名称模糊，存在多个匹配: {[m['collectionName'] for m in result.get('matches', [])]}"
                    )

            if not collection_id:
                raise ValueError("未指定收藏夹 ID")

            progress_file = (
                Path.home() / ".llamaindex" / f"zotero_{collection_id}_progress.json"
            )
            progress = ProcessingProgress.load(progress_file)
            logger.debug(f"[{task_id}] 进度文件加载: {progress_file}")

            if rebuild:
                logger.info(f"[{task_id}] 重建模式，删除现有数据")
                vs.delete_table()
                progress = ProcessingProgress()

            item_ids = importer.get_items_in_collection(collection_id)
            total_items = len(item_ids)
            logger.info(f"[{task_id}] 收藏夹包含 {total_items} 篇文献")

            await self._update_and_notify(
                task_id,
                total=total_items,
                message=f"开始导入 {collection_name} ({total_items} 篇文献)",
            )
            await self._update_heartbeat(task_id)

            if total_items == 0:
                await self._update_and_notify(
                    task_id, progress=100, message="收藏夹为空"
                )
                self.queue.complete_task(
                    task_id, result={"items": 0, "nodes": 0, "failed": 0}
                )
                return

            cancel_event = threading.Event()
            import_done = threading.Event()
            import_error = [None]
            stats_result = [None]
            progress_queue: "queue.Queue" = queue.Queue()

            def progress_callback(
                current: int, total: int, message: str, level: str
            ) -> None:
                progress_queue.put_nowait((current, total, message))

            def run_import():
                thread_importer = ZoteroImporter(config=config, kb_id=kb_id)
                try:
                    stats_result[0] = thread_importer.import_collection(
                        collection_id=collection_id,
                        collection_name=collection_name,
                        vector_store=vs,
                        embed_model=embed_model,
                        progress=progress,
                        rebuild=rebuild,
                        progress_file=progress_file,
                        progress_callback=progress_callback,
                        cancel_event=cancel_event,
                        kb_id=kb_id,
                    )
                except Exception as e:
                    import_error[0] = e
                finally:
                    import_done.set()
                    thread_importer.close()

            import_thread = threading.Thread(target=run_import, daemon=True)
            import_thread.start()

            last_heartbeat_count = 0
            while import_thread.is_alive():
                await asyncio.sleep(1)
                while not progress_queue.empty():
                    try:
                        current, total, message = progress_queue.get_nowait()
                        await self._update_and_notify(
                            task_id,
                            current=current,
                            total=total,
                            message=message,
                        )
                    except Exception:
                        pass
                if await self._check_cancelled(task_id):
                    cancel_event.set()
                    import_thread.join(timeout=5)
                    processed = (
                        stats_result[0].get("items", 0) if stats_result[0] else 0
                    )
                    processed_sources = (
                        stats_result[0].get("processed_sources", [])
                        if stats_result[0]
                        else []
                    )
                    await self._update_and_notify(
                        task_id,
                        message=f"导入已取消 (已处理 {processed} 篇)",
                    )
                    self._save_partial_progress(
                        task_id,
                        kb_id,
                        processed_sources,
                        processed,
                        0,
                        "任务已取消（部分数据已处理）",
                    )
                    return
                current_items = (
                    stats_result[0].get("items", 0) if stats_result[0] else 0
                )
                if current_items - last_heartbeat_count >= PROGRESS_UPDATE_INTERVAL:
                    await self._update_heartbeat(task_id)
                    last_heartbeat_count = current_items

            import_thread.join()

            while not progress_queue.empty():
                try:
                    current, total, message = progress_queue.get_nowait()
                    await self._update_and_notify(
                        task_id,
                        current=current,
                        total=total,
                        message=message,
                    )
                except Exception:
                    pass

            if import_error[0]:
                raise import_error[0]

            stats = stats_result[0]

            progress_file.unlink(missing_ok=True)

            logger.info(
                f"[{task_id}] Zotero 导入完成: "
                f"items={stats.get('items', 0)}, "
                f"nodes={stats.get('nodes', 0)}, "
                f"failed={stats.get('failed', 0)}"
            )

            await self._update_and_notify(
                task_id,
                progress=100,
                message=f"完成! {stats.get('items', 0)} 文献, {stats.get('nodes', 0)} 节点",
            )
            self.queue.complete_task(
                task_id,
                result={
                    "kb_id": kb_id,
                    "items": stats.get("items", 0),
                    "nodes": stats.get("nodes", 0),
                    "sources": stats.get("processed_sources", []),
                    "endpoint_stats": embed_processor.get_stats(),
                },
            )
            logger.info(f"[{task_id}] 任务完成并标记为已完成")

            if self._should_refresh_topics(params):
                self._update_kb_topics(kb_id, has_new_docs=stats.get("items", 0) > 0)

        except Exception as e:
            logger.error(f"[{task_id}] Zotero 导入任务执行失败: {e}", exc_info=True)
            await self._update_and_notify(task_id, message=f"导入失败: {str(e)}")
            raise
        finally:
            if importer is not None:
                importer.close()

    async def _execute_generic(self, task: "Task") -> None:
        """执行通用文件导入"""
        from kb_processing.generic_processor import GenericImporter
        from kb_processing.parallel_embedding import get_parallel_processor
        from rag.config import get_settings

        kb_id = task.kb_id
        params = task.params

        vs = self._get_vector_store(kb_id)
        from .database import init_document_db

        doc_db = init_document_db()
        embed_processor = get_parallel_processor()
        lance_store = vs._get_lance_vector_store()
        from kb_processing.document_processor import get_node_parser
        settings = get_settings()
        node_parser = get_node_parser(
            strategy=settings.chunk_strategy,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            hierarchical_chunk_sizes=settings.hierarchical_chunk_sizes,
        )

        raw_paths = params.get("paths")
        if raw_paths is None:
            single_path = params.get("path")
            raw_paths = [single_path] if single_path else []
        paths = raw_paths
        all_files: List[Path] = []

        for path_str in paths:
            p = Path(path_str)
            if p.exists():
                if p.is_file():
                    all_files.append(p)
                elif p.is_dir():
                    importer = GenericImporter()
                    files = importer.collect_files(
                        [p],
                        include_exts=params.get("include_exts"),
                        exclude_exts=params.get("exclude_exts"),
                    )
                    all_files.extend(files)

        total_files = len(all_files)

        from .task_queue import FileStatus
        import hashlib

        await self._update_and_notify(
            task.task_id, total=total_files, message=f"找到 {total_files} 个文件"
        )

        if total_files > 0:
            import hashlib

            file_list = []
            for file_path in all_files:
                file_id = hashlib.md5(str(file_path).encode()).hexdigest()[:12]
                file_list.append(
                    {
                        "file_id": file_id,
                        "file_name": str(file_path.name),
                        "status": FileStatus.PENDING.value,
                        "total_chunks": 0,
                        "processed_chunks": 0,
                        "db_written": False,
                        "error": None,
                    }
                )
            self.queue.set_file_progress(task.task_id, file_list)

        if total_files == 0:
            self.queue.complete_task(
                task.task_id,
                result={
                    "kb_id": kb_id,
                    "files": 0,
                    "nodes": 0,
                    "failed": 0,
                    "endpoint_stats": embed_processor.get_stats(),
                },
            )
            return

        stats = {"files": 0, "nodes": 0, "failed": 0}
        processed_sources = []
        last_heartbeat_file_count = 0

        for i, file_path in enumerate(all_files):
            file_id = hashlib.md5(str(file_path).encode()).hexdigest()[:12]
            self.queue.update_file_progress(
                task.task_id,
                file_id,
                status=FileStatus.PROCESSING.value,
                file_name=file_path.name,
            )

            if await self._check_cancelled(task.task_id):
                self._save_partial_progress(
                    task.task_id,
                    kb_id,
                    processed_sources,
                    stats["files"],
                    stats["nodes"],
                    "任务已取消（部分数据已处理）",
                )
                return
            if await self._check_paused(task.task_id):
                self._save_partial_progress(
                    task.task_id,
                    kb_id,
                    processed_sources,
                    stats["files"],
                    stats["nodes"],
                    "任务已暂停（部分数据已处理）",
                )
                return

            try:
                from kb_processing.document_processor import (
                    DocumentProcessor,
                    DocumentProcessorConfig,
                )

                config = DocumentProcessorConfig(
                    chunk_size=params.get("chunk_size", 1024),
                    chunk_overlap=params.get("chunk_overlap", 100),
                    chunk_strategy=params.get("chunk_strategy", "hierarchical"),
                    hierarchical_chunk_sizes=params.get("hierarchical_chunk_sizes"),
                )
                processor = DocumentProcessor(config=config)
                docs = processor.process_file(str(file_path))

                if docs:
                    file_nodes = []
                    for doc in docs:
                        nodes = node_parser.get_nodes_from_documents([doc])

                        if nodes:
                            texts = [node.get_content() for node in nodes]

                            results: List = [None] * len(texts)
                            async for (
                                idx,
                                result,
                            ) in embed_processor.process_batch_streaming(texts):
                                results[idx] = result

                            for j, (ep_name, embedding, error) in enumerate(results):
                                if results[j] is not None:
                                    nodes[j].embedding = embedding

                            file_nodes.extend(nodes)

                            # Write to SQLite FIRST (document + chunks)
                            try:
                                from .document_chunk_service import DocumentChunkService

                                current_hash = ""
                                try:
                                    from kb_processing.document_processor import DocumentProcessor

                                    current_hash = DocumentProcessor().compute_file_hash(
                                        str(file_path)
                                    )
                                except Exception:
                                    pass
                                file_size = (
                                    file_path.stat().st_size if file_path.exists() else 0
                                )
                                doc_chunk_svc = DocumentChunkService(kb_id)
                                result = doc_chunk_svc.create_document(
                                    source_file=str(file_path.name),
                                    source_path=str(file_path),
                                    file_hash=current_hash,
                                    nodes=nodes,
                                    file_size=file_size,
                                    metadata={"source": "generic"},
                                )
                                if not result:
                                    logger.warning(f"SQLite 文档记录创建失败 {file_path}")
                                    continue
                            except Exception as e:
                                logger.warning(f"SQLite 文档记录创建失败 {file_path}: {e}")
                                continue

                            # Then write to LanceDB
                            try:
                                processor = DocumentProcessor()
                                success_count, skipped, failed_ids = (
                                    processor._upsert_nodes(lance_store, nodes)
                                )
                            except Exception as write_ex:
                                logger.warning(
                                    f"LanceDB 写入失败（SQLite 已保存）: {file_path}, 错误: {write_ex}"
                                )
                                error_reason = f"LanceDB write failed: {write_ex}"
                                node_ids = [n.node_id for n in nodes]
                                doc_chunk_svc.mark_chunks_failed(node_ids)
                                self.queue.update_file_progress(
                                    task.task_id,
                                    file_id,
                                    status=FileStatus.COMPLETED.value,
                                    total_chunks=len(nodes),
                                    processed_chunks=0,
                                    db_written=True,
                                    error=error_reason,
                                )
                                stats["nodes"] += len(nodes)
                                processed_sources.append(str(file_path))
                                continue

                            stats["nodes"] += success_count
                            processed_sources.append(str(file_path))
                            stats["files"] += 1
                            self.queue.update_file_progress(
                                task.task_id,
                                file_id,
                                status=FileStatus.COMPLETED.value,
                                total_chunks=len(nodes),
                                processed_chunks=success_count,
                                db_written=True,
                            )

                progress = int((i + 1) / total_files * 100) if total_files > 0 else 0
                await self._update_and_notify(
                    task.task_id, progress=progress, message=f"处理: {file_path.name}"
                )

                # 定期更新心跳
                if i - last_heartbeat_file_count >= PROGRESS_UPDATE_INTERVAL:
                    await self._update_heartbeat(task.task_id)
                    last_heartbeat_file_count = i

            except Exception as e:
                logger.warning(f"处理文件失败 {file_path}: {e}")
                self.queue.update_file_progress(
                    task.task_id,
                    file_id,
                    status=FileStatus.FAILED.value,
                    error=str(e),
                )
                stats["failed"] += 1

        settings = get_settings()
        file_progress = self.queue.get_file_progress(task.task_id)
        self.queue.complete_task(
            task.task_id,
            result={
                "kb_id": kb_id,
                "files": stats["files"],
                "nodes": stats["nodes"],
                "failed": stats["failed"],
                "sources": processed_sources,
                "endpoint_stats": embed_processor.get_stats(),
                "chunk_strategy": settings.chunk_strategy,
                "file_progress": file_progress,
            },
        )

        vs.set_chunk_strategy(settings.chunk_strategy)

        if self._should_refresh_topics(params):
            self._update_kb_topics(kb_id, has_new_docs=stats["files"] > 0)

    async def _execute_initialize(self, task: "Task") -> None:
        """执行知识库初始化任务
        
        清空知识库的所有数据（向量存储、文档、chunks），
        但保留知识库配置。
        """
        kb_id = task.kb_id

        await self._update_and_notify(task.task_id, message="初始化知识库...")

        from .services import KnowledgeBaseService

        await self._update_and_notify(task.task_id, message="正在清空数据...")

        KnowledgeBaseService.initialize(kb_id)

        self.queue.complete_task(
            task.task_id, result={"message": "知识库已初始化（所有数据已清空）"}
        )
        await self._notify_progress(task.task_id)

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self._cancel_events:
            self._cancel_events[task_id].set()
            if task_id in self._pause_events:
                self._pause_events[task_id].clear()
            if task_id in self._running_tasks:
                task = self._running_tasks[task_id]
                if isinstance(task, asyncio.Task):
                    task.cancel()
            return True

        if task_id in self._running_tasks:
            task = self._running_tasks[task_id]
            if isinstance(task, asyncio.Task):
                task.cancel()
            if task_id in self._cancel_events:
                self._cancel_events[task_id].set()
            if task_id in self._pause_events:
                self._pause_events[task_id].clear()
            return True

        return False

    def cancel_and_wait(self, task_id: str, timeout: float = 5.0) -> bool:
        import concurrent.futures
        import threading

        if task_id not in self._running_tasks:
            return True
        asyncio_task = self._running_tasks.get(task_id)
        if not asyncio_task or not isinstance(asyncio_task, asyncio.Task):
            return True
        if asyncio_task.done():
            return True
        self.cancel_task(task_id)

        def _wait():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    asyncio.wait_for(asyncio.shield(asyncio_task), timeout=timeout)
                )
            finally:
                loop.close()

        thread = threading.Thread(target=_wait)
        thread.start()
        thread.join(timeout=timeout)
        return asyncio_task.done()

    def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        if task_id in self._pause_events:
            self._pause_events[task_id].clear()
            return True
        return False

    def resume_task(self, task_id: str) -> bool:
        """恢复任务"""
        if task_id in self._pause_events:
            self._pause_events[task_id].set()
            return True
        return False

    def submit_and_start(
        self, task_id: str, loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> None:
        """提交并启动任务（API 兼容性）"""
        import threading

        def run_in_thread() -> None:
            asyncio.set_event_loop(asyncio.new_event_loop())
            asyncio.get_event_loop().run_until_complete(self.execute_task(task_id))

        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()
        self._running_tasks[task_id] = task_id  # 标记任务已提交


# 全局实例 - 供外部模块使用
task_executor = TaskExecutor()

