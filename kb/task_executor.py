"""
任务执行器

支持本地和远程 Ollama 并行处理。
"""

import asyncio
import traceback
from typing import Optional

from llamaindex_study.logger import get_logger
from llamaindex_study.ollama_utils import create_ollama_embedding
from llamaindex_study.embedding_service import OllamaEndpoint, get_embedding_service

logger = get_logger(__name__)

try:
    from kb.task_queue import TaskQueue, TaskStatus
except ImportError:
    TaskQueue = None
    TaskStatus = None


class TaskExecutor:
    """任务执行器 - 支持本地/远程 Ollama 并行处理"""
    
    def __init__(self):
        from kb.task_queue import TaskQueue
        self.queue = TaskQueue()
        self._running_tasks: dict = {}
        self._cancel_events: dict = {}
    
    async def execute_task(self, task_id: str):
        """执行任务"""
        task = self.queue.get_task(task_id)
        if not task:
            return
        
        if task.status != TaskStatus.PENDING.value:
            return
        
        self._cancel_events[task_id] = asyncio.Event()
        
        try:
            self.queue.start_task(task_id)
            await self._notify_progress(task_id)
            
            if task.task_type == "zotero":
                await self._execute_zotero(task)
            elif task.task_type in ("obsidian", "obsidian_folder"):
                # obsidian_folder 使用相同的逻辑
                await self._execute_obsidian(task)
            elif task.task_type == "generic":
                await self._execute_generic(task)
            elif task.task_type == "rebuild":
                await self._execute_rebuild(task)
            else:
                raise ValueError(f"Unknown task type: {task.task_type}")
            
            # 注意：_execute_obsidian 等方法会自行调用 complete_task
            
        except asyncio.CancelledError:
            self.queue.complete_task(task_id, error="任务被取消")
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            traceback.print_exc()
            self.queue.complete_task(task_id, error=error_msg)
        finally:
            self._running_tasks.pop(task_id, None)
            self._cancel_events.pop(task_id, None)
    
    async def _notify_progress(self, task_id: str):
        """通知进度更新"""
        try:
            task = self.queue.get_task(task_id)
            if task:
                from kb.websocket_manager import ws_manager
                await ws_manager.send_task_update(task_id, task.to_dict())
        except Exception:
            pass
    
    async def _check_cancelled(self, task_id: str) -> bool:
        """检查是否取消"""
        if task_id in self._cancel_events:
            if self._cancel_events[task_id].is_set():
                return True
        return False
    
    def _get_vector_store(self, kb_id: str):
        """获取向量存储"""
        from kb.registry import get_storage_root
        from llamaindex_study.vector_store import LanceDBVectorStore
        
        persist_dir = get_storage_root() / kb_id
        return LanceDBVectorStore(persist_dir=persist_dir, table_name=kb_id)
    
    # ==================== Obsidian 导入 ====================
    
    async def _execute_obsidian(self, task):
        """
        执行 Obsidian 导入（并行多端点版本）
        
        使用本地和远程 Ollama 同时处理文件
        """
        from kb.registry import KnowledgeBaseRegistry
        from llama_index.embeddings.ollama import OllamaEmbedding
        from llama_index.core.node_parser import SentenceSplitter
        from llama_index.core.schema import Document as LlamaDocument
        from pathlib import Path
        
        kb_id = task.kb_id
        params = task.params
        rebuild = params.get("rebuild", False)
        
        self.queue.update_progress(task.task_id, message=f"开始导入: {kb_id}")
        
        # ===== 准备阶段 =====
        registry = KnowledgeBaseRegistry()
        kb = registry.get(kb_id)
        
        if not kb:
            raise ValueError(f"知识库不存在: {kb_id}")
        
        vault_root = Path.home() / "Documents" / "Obsidian Vault"
        persist_dir = kb.persist_dir
        
        # 向量存储
        vs = self._get_vector_store(kb_id)
        
        # 去重管理器
        dedup_manager = self._get_dedup_manager(kb_id, persist_dir)
        
        # 收集文件
        all_files = []
        for source_path in kb.source_paths_abs(vault_root):
            if source_path.exists():
                all_files.extend(source_path.rglob("*.md"))
        
        self.queue.update_progress(task.task_id, total=len(all_files),
                                  message=f"扫描到 {len(all_files)} 个文件")
        
        # 重建模式
        if rebuild:
            dedup_manager.clear()
            try:
                vs.delete_table()
                self.queue.update_progress(task.task_id, message="已清空旧数据")
            except:
                pass
        
        # 检测变更
        from kb.deduplication import DeduplicationManager
        dedup_manager = DeduplicationManager(kb_id, persist_dir)
        to_add, to_update, to_delete, unchanged = dedup_manager.detect_changes(all_files, vault_root)
        
        if not to_add and not to_update:
            self.queue.complete_task(task.task_id, result={"message": "没有变更"})
            return
        
        # 处理删除
        if to_delete and params.get("force_delete", True):
            self._process_deletes(persist_dir, kb_id, to_delete, dedup_manager)
        
        # 收集要处理的文档
        all_docs = [(c.rel_path, c.abs_path) for c in to_add + to_update]
        
        self.queue.update_progress(task.task_id,
                                  message=f"新增{len(to_add)} 更新{len(to_update)}")
        
        # ===== 并行处理阶段 =====
        # 端点配置
        endpoints = [
            {"name": "本地", "url": "http://localhost:11434"},
            {"name": "远程", "url": "http://192.168.31.169:11434"},
        ]
        
        lance_store = vs._get_lance_vector_store()
        node_parser = SentenceSplitter(chunk_size=512, chunk_overlap=50)
        
        # 分配文件
        files_per_ep = len(all_docs) // len(endpoints) + 1
        
        async def process_endpoint(endpoint, files):
            """处理一个端点的文件"""
            self.queue.update_progress(task.task_id, 
                                      message=f"[{endpoint['name']}] 处理 {len(files)} 个文件")
            
            embed_model = OllamaEmbedding(model_name="bge-m3", base_url=endpoint["url"])
            processed = 0
            total_nodes = 0
            
            for rel_path, abs_path in files:
                try:
                    content = abs_path.read_text(encoding="utf-8", errors="ignore")
                    
                    doc = LlamaDocument(
                        text=content,
                        metadata={"source": "obsidian", "file_path": str(abs_path),
                                 "relative_path": rel_path},
                        id_=rel_path,
                    )
                    
                    nodes = node_parser.get_nodes_from_documents([doc])
                    
                    # 生成 embeddings
                    for j, node in enumerate(nodes):
                        node.id_ = f"{rel_path}_{j}"
                        try:
                            embedding = embed_model.get_text_embedding(node.get_content())
                            node.embedding = embedding
                        except Exception as e:
                            logger.warning(f"[{endpoint['name']}] Embedding 失败: {e}")
                            node.embedding = [0.0] * 1024
                    
                    if nodes:
                        lance_store.add(nodes)
                        total_nodes += len(nodes)
                    
                    dedup_manager.mark_processed(abs_path, content, rel_path,
                                               chunk_count=len(nodes), vault_root=vault_root)
                    
                    processed += 1
                    
                    if processed % 10 == 0:
                        self.queue.update_progress(task.task_id,
                                                  message=f"[{endpoint['name']}] {processed}/{len(files)}")
                    
                except Exception as e:
                    logger.warning(f"[{endpoint['name']}] 失败 {rel_path}: {e}")
            
            self.queue.update_progress(task.task_id,
                                       message=f"[{endpoint['name']}] 完成: {processed} 文件")
            return processed, total_nodes
        
        # 准备并发任务
        worker_tasks = []
        for i, ep in enumerate(endpoints):
            start = i * files_per_ep
            end = min((i + 1) * files_per_ep, len(all_docs))
            ep_files = all_docs[start:end]
            
            if ep_files:
                self.queue.update_progress(task.task_id, message=f"• {ep['name']}: {len(ep_files)} 个文件")
                worker_tasks.append(process_endpoint(ep, ep_files))
        
        # 并发执行
        results = await asyncio.gather(*worker_tasks, return_exceptions=True)
        
        # 保存去重状态
        dedup_manager._save()
        
        # 统计
        total_files = sum(r[0] for r in results if isinstance(r, tuple))
        total_nodes = sum(r[1] for r in results if isinstance(r, tuple))
        
        self.queue.complete_task(task.task_id, result={
            "kb_id": kb_id,
            "files": total_files,
            "nodes": total_nodes,
        })
    
    def _get_dedup_manager(self, kb_id, persist_dir):
        """获取去重管理器"""
        from kb.deduplication import DeduplicationManager
        return DeduplicationManager(kb_id, persist_dir)
    
    def _process_deletes(self, persist_dir, kb_id, to_delete, dedup_manager):
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
    
    async def _execute_zotero(self, task):
        """执行 Zotero 导入"""
        from kb.zotero_processor import ZoteroImporter
        from kb.document_processor import DocumentProcessorConfig, ProcessingProgress
        from pathlib import Path
        
        kb_id = task.kb_id
        params = task.params
        
        collection_id = params.get("collection_id")
        collection_name = params.get("collection_name", "Unknown")
        rebuild = params.get("rebuild", False)
        
        self.queue.update_progress(task.task_id, message=f"准备导入 Zotero: {collection_name}")
        
        vs = self._get_vector_store(kb_id)
        embed_model = create_ollama_embedding()
        
        config = DocumentProcessorConfig(chunk_size=512, chunk_overlap=50)
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
        
        self.queue.update_progress(task.task_id, message=f"开始导入 {collection_name}...")
        
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
            
            self.queue.update_progress(task.task_id, progress=100,
                                      message=f"完成! {stats.get('items', 0)} 文献, {stats.get('nodes', 0)} 节点")
            
        except Exception as e:
            self.queue.update_progress(task.task_id, message=f"导入失败: {str(e)}")
            raise
        finally:
            importer.close()
    
    async def _execute_generic(self, task):
        """执行通用文件导入"""
        from kb.generic_processor import GenericImporter
        from pathlib import Path
        
        kb_id = task.kb_id
        params = task.params
        
        vs = self._get_vector_store(kb_id)
        
        paths = params.get("paths", [])
        all_files = []
        
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
        
        self.queue.update_progress(task.task_id, total=total_files,
                                  message=f"找到 {total_files} 个文件")
        
        importer = GenericImporter()
        
        for i, file_path in enumerate(all_files):
            if await self._check_cancelled(task.task_id):
                return
            
            try:
                importer.process_file(path=file_path, vector_store=vs,
                                   embed_model=create_ollama_embedding())
                
                progress = int((i + 1) / total_files * 100) if total_files > 0 else 0
                self.queue.update_progress(task.task_id, progress=progress,
                                         message=f"处理: {file_path.name}")
                
            except Exception as e:
                logger.warning(f"处理文件失败 {file_path}: {e}")
        
        self.queue.update_progress(task.task_id, progress=100,
                                  message=f"完成! 处理 {total_files} 个文件")
    
    async def _execute_rebuild(self, task):
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
    
    def submit_and_start(self, task_id: str, loop=None):
        """提交并启动任务（API 兼容性）"""
        import asyncio
        import threading
        
        # 在新线程中创建并运行事件循环
        def run_in_thread():
            asyncio.set_event_loop(asyncio.new_event_loop())
            asyncio.get_event_loop().run_until_complete(self.execute_task(task_id))
        
        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()
        self._running_tasks[task_id] = thread
    
    def _run_loop(self, loop):
        """运行事件循环"""
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        finally:
            loop.close()


# 全局实例
task_executor = TaskExecutor()


class TaskScheduler:
    """任务调度器"""
    
    def __init__(self):
        from kb.task_queue import TaskQueue
        self.queue = TaskQueue()
        self.executor = TaskExecutor()
        self._running = True
    
    async def run(self):
        """运行调度器"""
        logger.info("任务调度器已启动")
        
        while self._running:
            try:
                pending = self.queue.get_pending(limit=10)
                
                for task in pending:
                    if task.task_id in self.executor._running_tasks:
                        continue
                    
                    self.executor._running_tasks[task.task_id] = asyncio.create_task(
                        self.executor.execute_task(task.task_id)
                    )
                    logger.info(f"启动任务: {task.task_id[:8]}...")
                
                # 清理已完成的任务引用
                done = [tid for tid, t in self.executor._running_tasks.items() if t.done()]
                for tid in done:
                    self.executor._running_tasks.pop(tid, None)
                
            except Exception as e:
                logger.error(f"调度器错误: {e}")
            
            await asyncio.sleep(1)
        
        logger.info("任务调度器已停止")
    
    def stop(self):
        """停止调度器"""
        self._running = False
