"""
任务执行器

支持本地和远程 Ollama 并行处理。
"""

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)

# 配置常量
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "512"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
PROGRESS_UPDATE_INTERVAL = int(os.getenv("PROGRESS_UPDATE_INTERVAL", "10"))
DEFAULT_MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_TASKS", "10"))

if TYPE_CHECKING:
    from kb.task_queue import Task, TaskQueue, TaskStatus
    from llamaindex_study.vector_store import LanceDBVectorStore
    from kb.deduplication import DeduplicationManager


class TaskExecutor:
    """任务执行器 - 支持本地/远程 Ollama 并行处理"""
    
    def __init__(self) -> None:
        from kb.task_queue import TaskQueue
        self.queue: TaskQueue = TaskQueue()
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}
    
    async def execute_task(self, task_id: str) -> None:
        """执行任务"""
        from kb.task_queue import TaskStatus
        
        task = self.queue.get_task(task_id)
        if not task:
            logger.warning(f"任务不存在: {task_id}")
            return
        
        if task.status != TaskStatus.PENDING.value:
            logger.debug(f"任务状态不是 pending: {task_id} ({task.status})")
            return
        
        self._cancel_events[task_id] = asyncio.Event()
        
        try:
            self.queue.start_task(task_id)
            await self._notify_progress(task_id)
            
            if task.task_type == "zotero":
                await self._execute_zotero(task)
            elif task.task_type in ("obsidian", "obsidian_folder"):
                await self._execute_obsidian(task)
            elif task.task_type == "generic":
                await self._execute_generic(task)
            elif task.task_type == "rebuild":
                await self._execute_rebuild(task)
            else:
                raise ValueError(f"Unknown task type: {task.task_type}")
            
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
    
    async def _notify_progress(self, task_id: str) -> None:
        """通知进度更新"""
        try:
            task = self.queue.get_task(task_id)
            if task:
                from kb.websocket_manager import ws_manager
                await ws_manager.send_task_update(task_id, task.to_dict())
        except Exception as e:
            logger.debug(f"进度通知失败: {e}")
    
    async def _check_cancelled(self, task_id: str) -> bool:
        """检查是否取消"""
        if task_id in self._cancel_events:
            if self._cancel_events[task_id].is_set():
                return True
        return False
    
    def _get_vector_store(self, kb_id: str) -> "LanceDBVectorStore":
        """获取向量存储（使用服务层）"""
        from kb.services import VectorStoreService
        return VectorStoreService.get_vector_store(kb_id)
    
    def _get_vault_root(self) -> Path:
        """获取 Vault 根目录"""
        from kb.registry import get_vault_root
        return get_vault_root()
    
    def _get_dedup_manager(self, kb_id: str, persist_dir: Path) -> "DeduplicationManager":
        """获取去重管理器"""
        from kb.deduplication import DeduplicationManager
        return DeduplicationManager(kb_id, persist_dir)
    
    # ==================== Obsidian 导入 ====================
    
    async def _execute_obsidian(self, task: "Task") -> None:
        """
        执行 Obsidian 导入（并行多端点版本）
        
        架构：
        - 去重数据库：串行访问（保护共享资源）
        - Embedding：并行处理（本地+远程同时工作）
        - LanceDB 写入：串行（通过 WriteQueue）
        """
        from kb.registry import KnowledgeBaseRegistry
        from kb.task_lock import DedupLock
        from llama_index.core.node_parser import SentenceSplitter
        from llama_index.core.schema import Document as LlamaDocument
        from kb.parallel_embedding import get_parallel_processor
        from kb.ingest_vdb import lance_write_queue
        
        kb_id = task.kb_id
        params = task.params
        rebuild = params.get("rebuild", False)
        
        self.queue.update_progress(task.task_id, message=f"开始导入: {kb_id}")
        
        # ===== 准备阶段 =====
        registry = KnowledgeBaseRegistry()
        kb = registry.get(kb_id)
        vault_root = Path(params.get("vault_path")).expanduser() if params.get("vault_path") else self._get_vault_root()
        folder_path = params.get("folder_path") or params.get("folder")
        recursive = params.get("recursive", True)
        if not kb and not folder_path:
            raise ValueError(f"知识库不存在且未提供 folder_path: {kb_id}")
        persist_dir = Path(params.get("persist_dir")).expanduser() if params.get("persist_dir") else self._get_vector_store(kb_id).persist_dir
        
        # 向量存储
        vs = self._get_vector_store(kb_id)
        
        # 去重管理器
        dedup_manager = self._get_dedup_manager(kb_id, persist_dir)
        
        # 收集文件
        all_files: List[Path] = []
        if folder_path:
            source_paths = [vault_root / folder_path]
        else:
            source_paths = kb.source_paths_abs(vault_root)

        for source_path in source_paths:
            if source_path.exists():
                pattern = source_path.rglob("*.md") if recursive else source_path.glob("*.md")
                all_files.extend(pattern)
        
        self.queue.update_progress(
            task.task_id, 
            total=len(all_files),
            message=f"扫描到 {len(all_files)} 个文件"
        )
        
        # ===== 去重阶段（串行访问）=====
        async with DedupLock():
            # 重建模式
            if rebuild:
                dedup_manager.clear()
                try:
                    vs.delete_table()
                    self.queue.update_progress(task.task_id, message="已清空旧数据")
                except Exception as e:
                    logger.warning(f"清空旧数据失败: {e}")
            
            # 检测变更
            to_add, to_update, to_delete, unchanged = dedup_manager.detect_changes(
                all_files, vault_root
            )
            
            if not to_add and not to_update:
                self.queue.complete_task(task.task_id, result={"message": "没有变更"})
                return
            
            # 处理删除
            if to_delete and params.get("force_delete", True):
                self._process_deletes(persist_dir, kb_id, to_delete, dedup_manager)
            
            # 收集要处理的文档
            all_docs: List[tuple] = [(c.rel_path, c.abs_path) for c in to_add + to_update]
            
            self.queue.update_progress(
                task.task_id,
                message=f"新增{len(to_add)} 更新{len(to_update)}"
            )
        
        # ===== 并行处理阶段（embedding + LanceDB 写入）=====
        lance_store = vs._get_lance_vector_store()
        node_parser = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        
        # 启动写入队列
        await lance_write_queue.start()
        
        # 获取并行处理器
        embed_processor = get_parallel_processor()
        
        processed_files = 0
        processed_chunks = 0
        
        self.queue.update_progress(
            task.task_id, 
            message=f"开始处理 {len(all_docs)} 个文件"
        )
        
        for rel_path, abs_path in all_docs:
            try:
                content = abs_path.read_text(encoding="utf-8", errors="ignore")
                
                doc = LlamaDocument(
                    text=content,
                    metadata={
                        "source": "obsidian", 
                        "file_path": str(abs_path),
                        "relative_path": rel_path
                    },
                    id_=rel_path,
                )
                
                nodes = node_parser.get_nodes_from_documents([doc])
                
                if nodes:
                    # 收集所有文本
                    texts = [node.get_content() for node in nodes]
                    
                    # 真正并行获取 embeddings（两个端点同时工作）
                    results = await embed_processor.process_batch(texts)
                    
                    # 赋值 embeddings
                    for j, (ep_name, embedding, error) in enumerate(results):
                        nodes[j].id_ = f"{rel_path}_{j}"
                        nodes[j].embedding = embedding
                    
                    # 发送到写入队列（串行执行）
                    await lance_write_queue.enqueue(lance_store, nodes, kb_id)
                    processed_chunks += len(nodes)
                
                # 更新去重状态（串行访问）
                async with DedupLock():
                    dedup_manager.mark_processed(
                        file_path=abs_path,
                        content=content,
                        doc_id=rel_path,
                        chunk_count=len(nodes),
                        vault_root=vault_root
                    )
                
                processed_files += 1
                
                # 定期更新进度
                if processed_files % PROGRESS_UPDATE_INTERVAL == 0:
                    self.queue.update_progress(
                        task.task_id,
                        message=f"处理 {processed_files}/{len(all_docs)} ({processed_chunks} chunks)"
                    )
                
            except Exception as e:
                logger.warning(f"处理失败 {rel_path}: {e}")
        
        # 等待写入队列清空（使用公共方法）
        await lance_write_queue.wait_until_empty()
        
        # 保存去重状态（串行访问）
        async with DedupLock():
            dedup_manager._save()
        
        # 统计端点使用情况
        stats = embed_processor.get_stats()
        failure_stats = embed_processor.get_failure_stats()
        logger.info(f"端点使用统计: {stats}, 失败统计: {failure_stats}")
        
        self.queue.complete_task(task.task_id, result={
            "kb_id": kb_id,
            "files": processed_files,
            "nodes": processed_chunks,
            "endpoint_stats": stats,
        })
    
    def _process_deletes(
        self, 
        persist_dir: Path, 
        kb_id: str, 
        to_delete: List[Any],
        dedup_manager: "DeduplicationManager"
    ) -> None:
        """处理删除的文件"""
        import lancedb
        
        doc_ids = [c.doc_id for c in to_delete if c.doc_id]
        
        try:
            db = lancedb.connect(str(persist_dir))
            if db.list_table_names():
                table = db.open_table(kb_id)
                data = table.to_pandas()
                
                if not data.empty and "_row_id" in data.columns:
                    to_keep = ~data["_row_id"].astype(str).isin(doc_ids)
                    remaining = data[to_keep]
                    
                    db.drop_table(kb_id)
                    if not remaining.empty:
                        db.create_table(kb_id, data=remaining)
        except Exception as e:
            logger.error(f"删除处理失败: {e}")
        
        for change in to_delete:
            dedup_manager.remove_record(change.rel_path)
    
    # ==================== 其他任务类型 ====================
    
    async def _execute_zotero(self, task: "Task") -> None:
        """执行 Zotero 导入"""
        from kb.zotero_processor import ZoteroImporter
        from kb.document_processor import DocumentProcessorConfig, ProcessingProgress
        from kb.parallel_embedding import get_parallel_processor
        from llamaindex_study.ollama_utils import create_parallel_ollama_embedding
        
        kb_id = task.kb_id
        params = task.params
        
        collection_id = params.get("collection_id")
        collection_name = params.get("collection_name", "Unknown")
        rebuild = params.get("rebuild", False)
        
        self.queue.update_progress(
            task.task_id, 
            message=f"准备导入 Zotero: {collection_name}"
        )
        
        vs = self._get_vector_store(kb_id)
        embed_model = create_parallel_ollama_embedding()
        embed_processor = get_parallel_processor()
        
        config = DocumentProcessorConfig(
            chunk_size=CHUNK_SIZE, 
            chunk_overlap=CHUNK_OVERLAP
        )
        importer = ZoteroImporter(config=config)
        
        if not collection_id and params.get("collection_name"):
            result = importer.get_collection_by_name(params["collection_name"])
            if result and "collectionID" in result:
                collection_id = result["collectionID"]
        
        if not collection_id:
            raise ValueError("未指定收藏夹 ID")
        
        progress_file = Path.home() / ".llamaindex" / f"zotero_{collection_id}_progress.json"
        progress = ProcessingProgress.load(progress_file)
        
        if rebuild:
            vs.delete_table()
            progress = ProcessingProgress()
        
        self.queue.update_progress(
            task.task_id, 
            message=f"开始导入 {collection_name}..."
        )
        
        try:
            stats = importer.import_collection(
                collection_id=collection_id,
                collection_name=collection_name,
                vector_store=vs,
                embed_model=embed_model,
                progress=progress,
                rebuild=rebuild,
            )
            
            progress_file.unlink(missing_ok=True)
            
            self.queue.update_progress(
                task.task_id, 
                progress=100,
                message=f"完成! {stats.get('items', 0)} 文献, {stats.get('nodes', 0)} 节点"
            )
            self.queue.complete_task(task.task_id, result={
                "kb_id": kb_id,
                "items": stats.get("items", 0),
                "nodes": stats.get("nodes", 0),
                "endpoint_stats": embed_processor.get_stats(),
            })
            
        except Exception as e:
            self.queue.update_progress(task.task_id, message=f"导入失败: {str(e)}")
            raise
        finally:
            importer.close()
    
    async def _execute_generic(self, task: "Task") -> None:
        """执行通用文件导入"""
        from kb.generic_processor import GenericImporter
        from kb.parallel_embedding import get_parallel_processor
        from llamaindex_study.ollama_utils import create_parallel_ollama_embedding
        
        kb_id = task.kb_id
        params = task.params
        
        vs = self._get_vector_store(kb_id)
        embed_model = create_parallel_ollama_embedding()
        embed_processor = get_parallel_processor()
        
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
                    files = importer.collect_files([p])
                    all_files.extend(files)
        
        total_files = len(all_files)
        
        self.queue.update_progress(
            task.task_id, 
            total=total_files,
            message=f"找到 {total_files} 个文件"
        )

        if total_files == 0:
            self.queue.complete_task(task.task_id, result={
                "kb_id": kb_id,
                "files": 0,
                "nodes": 0,
                "failed": 0,
                "endpoint_stats": embed_processor.get_stats(),
            })
            return
        
        importer = GenericImporter()
        stats = {"files": 0, "nodes": 0, "failed": 0}
        
        for i, file_path in enumerate(all_files):
            if await self._check_cancelled(task.task_id):
                return
            
            try:
                file_stats = importer.process_file(
                    path=file_path, 
                    vector_store=vs,
                    embed_model=embed_model,
                )
                stats["files"] += file_stats.get("files", 0)
                stats["nodes"] += file_stats.get("nodes", 0)
                stats["failed"] += file_stats.get("failed", 0)
                
                progress = int((i + 1) / total_files * 100) if total_files > 0 else 0
                self.queue.update_progress(
                    task.task_id, 
                    progress=progress,
                    message=f"处理: {file_path.name}"
                )
                
            except Exception as e:
                logger.warning(f"处理文件失败 {file_path}: {e}")
                stats["failed"] += 1
        
        self.queue.complete_task(task.task_id, result={
            "kb_id": kb_id,
            "files": stats["files"],
            "nodes": stats["nodes"],
            "failed": stats["failed"],
            "endpoint_stats": embed_processor.get_stats(),
        })
    
    async def _execute_rebuild(self, task: "Task") -> None:
        """执行重建知识库"""
        kb_id = task.kb_id
        
        self.queue.update_progress(task.task_id, message="清空知识库...")
        
        vs = self._get_vector_store(kb_id)
        vs.delete_table()
        
        self.queue.complete_task(task.task_id, result={"message": "知识库已清空"})
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self._cancel_events:
            self._cancel_events[task_id].set()
            return True
        return False
    
    def submit_and_start(self, task_id: str, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """提交并启动任务（API 兼容性）"""
        import threading
        
        def run_in_thread() -> None:
            asyncio.set_event_loop(asyncio.new_event_loop())
            asyncio.get_event_loop().run_until_complete(self.execute_task(task_id))
        
        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()
        self._running_tasks[task_id] = thread  # type: ignore


# 全局实例
task_executor = TaskExecutor()


class TaskScheduler:
    """任务调度器"""
    
    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT) -> None:
        from kb.task_queue import TaskQueue
        self.queue: TaskQueue = TaskQueue()
        self.executor: TaskExecutor = task_executor
        self._running: bool = True
        self.max_concurrent: int = max_concurrent
    
    async def run(self) -> None:
        """运行调度器"""
        logger.info(f"任务调度器已启动 (最大并发: {self.max_concurrent})")
        
        while self._running:
            try:
                # 获取当前运行中的任务数
                running_count = len(self.executor._running_tasks)
                
                # 如果还有并发余量，提交新任务
                if running_count < self.max_concurrent:
                    pending = self.queue.get_pending(
                        limit=self.max_concurrent - running_count
                    )
                    
                    for task in pending:
                        if task.task_id in self.executor._running_tasks:
                            continue
                        
                        self.executor._running_tasks[task.task_id] = asyncio.create_task(
                            self.executor.execute_task(task.task_id)
                        )
                        logger.info(f"启动任务: {task.task_id[:8]} ({task.kb_id})")
                
                # 清理已完成的任务引用
                self._cleanup_completed_tasks()
                
            except Exception as e:
                logger.error(f"调度器错误: {e}")
            
            await asyncio.sleep(1)
        
        logger.info("任务调度器已停止")
    
    def _cleanup_completed_tasks(self) -> None:
        """清理已完成的任务引用"""
        try:
            done = [
                tid for tid, t in list(self.executor._running_tasks.items())
                if isinstance(t, asyncio.Task) and t.done()
            ]
            for tid in done:
                self.executor._running_tasks.pop(tid, None)
        except Exception as e:
            logger.debug(f"清理已完成任务失败: {e}")
    
    def stop(self) -> None:
        """停止调度器"""
        self._running = False
