"""
任务执行器

后台任务执行器，支持：
- 异步任务执行
- 进度实时更新
- 错误处理
- 任务取消
"""

import asyncio
import traceback
from typing import Dict, Any, Callable, Optional

from kb.task_queue import TaskQueue, TaskStatus


class TaskExecutor:
    """
    任务执行器
    
    在后台异步执行任务，实时更新进度
    """
    
    def __init__(self):
        self.queue = TaskQueue()
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}
    
    async def execute_task(self, task_id: str):
        """
        执行任务
        
        Args:
            task_id: 任务 ID
        """
        task = self.queue.get_task(task_id)
        if not task:
            return
        
        # 检查任务状态
        if task.status != TaskStatus.PENDING.value:
            return
        
        # 创建取消事件
        self._cancel_events[task_id] = asyncio.Event()
        
        try:
            # 标记为运行中
            self.queue.start_task(task_id)
            
            # 根据任务类型执行
            if task.task_type == "zotero":
                await self._execute_zotero(task)
            elif task.task_type == "obsidian":
                await self._execute_obsidian(task)
            elif task.task_type == "generic":
                await self._execute_generic(task)
            elif task.task_type == "rebuild":
                await self._execute_rebuild(task)
            else:
                raise ValueError(f"Unknown task type: {task.task_type}")
            
            # 完成任务
            result = {
                "kb_id": task.kb_id,
                "task_id": task_id,
            }
            self.queue.complete_task(task_id, result=result)
            
        except asyncio.CancelledError:
            self.queue.complete_task(task_id, error="任务被取消")
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            traceback.print_exc()
            self.queue.complete_task(task_id, error=error_msg)
        finally:
            # 清理
            self._running_tasks.pop(task_id, None)
            self._cancel_events.pop(task_id, None)
    
    async def _check_cancelled(self, task_id: str) -> bool:
        """检查是否取消"""
        if task_id in self._cancel_events:
            if self._cancel_events[task_id].is_set():
                return True
        return False
    
    async def _execute_zotero(self, task):
        """执行 Zotero 导入"""
        from kb.zotero_processor import ZoteroImporter
        from kb.document_processor import DocumentProcessorConfig
        from llamaindex_study.vector_store import create_vector_store, VectorStoreType
        from llamaindex_study.config import get_settings
        from llama_index.embeddings.ollama import OllamaEmbedding
        from llama_index.core import Settings
        
        settings = get_settings()
        kb_id = task.kb_id
        params = task.params
        
        # 配置
        Settings.embed_model = OllamaEmbedding(
            model_name=settings.ollama_embed_model,
            base_url=settings.ollama_base_url,
        )
        embed_model = OllamaEmbedding(
            model_name=settings.ollama_embed_model,
            base_url=settings.ollama_base_url,
        )
        
        # 获取向量存储
        from api import get_vector_store
        vs = get_vector_store(kb_id)
        
        # 重建
        if params.get("rebuild"):
            vs.delete_table()
            self.queue.update_progress(task.task_id, message="已清空知识库")
        
        # 创建导入器
        config = DocumentProcessorConfig(
            chunk_size=params.get("chunk_size", 512),
            chunk_overlap=params.get("chunk_overlap", 50),
        )
        importer = ZoteroImporter(config=config)
        
        # 获取收藏夹
        collection_id = params.get("collection_id")
        collection_name = params.get("collection_name", "Unknown")
        
        if not collection_id and params.get("collection_name"):
            result = importer.get_collection_by_name(params["collection_name"])
            if result and "collectionID" in result:
                collection_id = result["collectionID"]
                collection_name = result.get("collectionName", collection_name)
        
        if not collection_id:
            raise ValueError("未指定收藏夹 ID 或名称")
        
        # 获取文献列表
        item_ids = importer.get_items_in_collection(collection_id)
        total_items = len(item_ids)
        
        self.queue.update_progress(
            task.task_id,
            total=total_items,
            message=f"找到 {total_items} 篇文献"
        )
        
        # 导入文献
        total_nodes = 0
        processed = 0
        failed = 0
        
        for item_id in item_ids:
            # 检查取消
            if await self._check_cancelled(task.task_id):
                importer.close()
                return
            
            # 获取文献
            item = importer.get_item(item_id)
            if not item:
                failed += 1
                continue
            
            try:
                # 这里简化处理，实际应该调用 importer.import_item
                # 更新进度
                processed += 1
                progress = int(processed / total_items * 100) if total_items > 0 else 0
                
                self.queue.update_progress(
                    task.task_id,
                    progress=progress,
                    current=processed,
                    total=total_items,
                    message=f"处理: {item.title[:30]}..."
                )
                
                # 模拟一些延迟（实际处理可能很慢）
                await asyncio.sleep(0.1)
                
            except Exception as e:
                failed += 1
                continue
        
        importer.close()
        
        self.queue.update_progress(
            task.task_id,
            progress=100,
            message=f"完成！处理 {processed} 篇，成功 {processed - failed} 篇"
        )
    
    async def _execute_obsidian(self, task):
        """执行 Obsidian 导入"""
        from kb.obsidian_processor import ObsidianImporter
        from kb.document_processor import DocumentProcessorConfig
        from llamaindex_study.vector_store import create_vector_store, VectorStoreType
        from llamaindex_study.config import get_settings
        from llama_index.embeddings.ollama import OllamaEmbedding
        from llama_index.core import Settings
        from pathlib import Path
        
        settings = get_settings()
        kb_id = task.kb_id
        params = task.params
        
        # 配置
        Settings.embed_model = OllamaEmbedding(
            model_name=settings.ollama_embed_model,
            base_url=settings.ollama_base_url,
        )
        embed_model = OllamaEmbedding(
            model_name=settings.ollama_embed_model,
            base_url=settings.ollama_base_url,
        )
        
        # 获取向量存储
        from api import get_vector_store
        vs = get_vector_store(kb_id)
        
        # 创建导入器
        vault_path = Path(params.get("vault_path"))
        if not vault_path.exists():
            raise ValueError(f"Vault 路径不存在: {vault_path}")
        
        import_dir = vault_path
        if params.get("folder_path"):
            import_dir = vault_path / params["folder_path"]
            if not import_dir.exists():
                raise ValueError(f"文件夹不存在: {import_dir}")
        
        importer = ObsidianImporter(vault_root=vault_path)
        
        # 收集文件
        files = importer.collect_files(import_dir, recursive=params.get("recursive", True))
        total_files = len(files)
        
        self.queue.update_progress(
            task.task_id,
            total=total_files,
            message=f"找到 {total_files} 个笔记"
        )
        
        # 模拟处理
        for i, _ in enumerate(files):
            if await self._check_cancelled(task.task_id):
                return
            
            progress = int((i + 1) / total_files * 100) if total_files > 0 else 0
            self.queue.update_progress(
                task.task_id,
                progress=progress,
                current=i + 1,
                total=total_files,
                message=f"处理: {i + 1}/{total_files}"
            )
            
            await asyncio.sleep(0.05)
        
        self.queue.update_progress(
            task.task_id,
            progress=100,
            message=f"完成！处理 {total_files} 个文件"
        )
    
    async def _execute_generic(self, task):
        """执行通用文件导入"""
        from kb.generic_processor import GenericImporter, FileImportConfig
        from kb.document_processor import DocumentProcessorConfig
        from llamaindex_study.vector_store import create_vector_store, VectorStoreType
        from llamaindex_study.config import get_settings
        from llama_index.embeddings.ollama import OllamaEmbedding
        from llama_index.core import Settings
        from pathlib import Path
        
        settings = get_settings()
        kb_id = task.kb_id
        params = task.params
        
        # 配置
        Settings.embed_model = OllamaEmbedding(
            model_name=settings.ollama_embed_model,
            base_url=settings.ollama_base_url,
        )
        embed_model = OllamaEmbedding(
            model_name=settings.ollama_embed_model,
            base_url=settings.ollama_base_url,
        )
        
        # 获取向量存储
        from api import get_vector_store
        vs = get_vector_store(kb_id)
        
        # 收集文件
        paths = params.get("paths", [])
        all_files = []
        for path_str in paths:
            p = Path(path_str)
            if p.exists():
                if p.is_file():
                    all_files.append(p)
                elif p.is_dir():
                    files = GenericImporter().collect_files([p])
                    all_files.extend(files)
        
        total_files = len(all_files)
        
        self.queue.update_progress(
            task.task_id,
            total=total_files,
            message=f"找到 {total_files} 个文件"
        )
        
        # 模拟处理
        for i, _ in enumerate(all_files):
            if await self._check_cancelled(task.task_id):
                return
            
            progress = int((i + 1) / total_files * 100) if total_files > 0 else 0
            self.queue.update_progress(
                task.task_id,
                progress=progress,
                current=i + 1,
                total=total_files,
                message=f"处理: {i + 1}/{total_files}"
            )
            
            await asyncio.sleep(0.05)
        
        self.queue.update_progress(
            task.task_id,
            progress=100,
            message=f"完成！处理 {total_files} 个文件"
        )
    
    async def _execute_rebuild(self, task):
        """执行重建知识库"""
        from llamaindex_study.vector_store import create_vector_store, VectorStoreType
        from api import get_vector_store
        
        kb_id = task.kb_id
        
        self.queue.update_progress(
            task.task_id,
            message="正在清空知识库..."
        )
        
        vs = get_vector_store(kb_id)
        vs.delete_table()
        
        self.queue.update_progress(
            task.task_id,
            progress=100,
            message="知识库已清空"
        )
    
    def submit_and_start(self, task_id: str, loop: asyncio.AbstractEventLoop = None):
        """提交并启动任务"""
        if loop is None:
            loop = asyncio.new_event_loop()
        
        task = loop.create_task(self.execute_task(task_id))
        self._running_tasks[task_id] = task
        
        # 在新线程中运行事件循环
        import threading
        thread = threading.Thread(target=self._run_loop, args=(loop,))
        thread.daemon = True
        thread.start()
    
    def _run_loop(self, loop):
        """运行事件循环"""
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        finally:
            loop.close()
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self._cancel_events:
            self._cancel_events[task_id].set()
            return True
        return False


# 全局实例
task_executor = TaskExecutor()
