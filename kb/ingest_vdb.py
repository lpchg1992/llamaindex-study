#!/usr/bin/env python3
"""
知识库导入脚本 - 并行多端点版本

支持增量同步 + 本地/远程 Ollama 并行处理：
- 任务提交和执行分离
- 本地和远程 Ollama 同时处理
- 实时进度查询

用法:
    python -m kb.ingest_vdb                    # 提交所有知识库导入任务
    python -m kb.ingest_vdb --kb tech_tools   # 提交指定知识库导入任务
    python -m kb.ingest_vdb --tasks           # 查看任务状态
    python -m kb.ingest_vdb --list            # 列出知识库
    python -m kb.ingest_vdb --show-changes    # 显示变更
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from llamaindex_study.logger import get_logger
logger = get_logger(__name__)


# ==================== LanceDB 写入队列 ====================

class LanceDBWriteQueue:
    """
    LanceDB 写入队列
    
    确保串行写入，避免数据库锁定
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
        self._queue = asyncio.Queue()
        self._running = True
        self._worker_task = None
        import concurrent.futures
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    
    async def _worker(self):
        """写入 worker"""
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                lance_store, nodes, kb_id = item
                
                if lance_store and nodes:
                    try:
                        # 在线程池中执行同步写入
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            self._executor,
                            lambda: lance_store.add(nodes)
                        )
                    except Exception as e:
                        logger.error(f"LanceDB 写入失败 ({kb_id}): {e}")
                
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"写入队列错误: {e}")
    
    async def start(self):
        """启动写入 worker"""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker())
    
    def stop(self):
        """停止写入 worker"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
    
    async def enqueue(self, lance_store, nodes, kb_id: str):
        """添加写入任务"""
        await self._queue.put((lance_store, nodes, kb_id))


# 全局写入队列
lance_write_queue = LanceDBWriteQueue()

from kb.registry import KnowledgeBaseRegistry
from kb.deduplication import DeduplicationManager
from kb.task_queue import TaskQueue, TaskType, TaskStatus
from kb.task_executor import TaskExecutor
from llamaindex_study.vector_store import VectorStoreType, create_vector_store, get_default_vector_store


# ==================== 任务提交 ====================

def submit_ingest_task(kb_id: str, rebuild: bool = False, force_delete: bool = True) -> str:
    """提交知识库导入任务"""
    task_queue = TaskQueue()
    
    task_id = task_queue.submit_task(
        task_type=TaskType.OBSIDIAN.value,
        kb_id=kb_id,
        params={"rebuild": rebuild, "force_delete": force_delete, "engine": "lancedb"},
        source=f"obsidian ingest: {kb_id}",
    )
    
    return task_id


def submit_all_ingest_tasks(rebuild: bool = False) -> list:
    """提交所有知识库的导入任务"""
    registry = KnowledgeBaseRegistry()
    results = []
    
    for kb in registry.list_all():
        task_id = submit_ingest_task(kb.id, rebuild=rebuild)
        results.append((kb.id, task_id, kb.name))
    
    return results


# ==================== 并行任务执行器 ====================

class ParallelIngestExecutor:
    """并行导入执行器 - 本地/远程 Ollama 同时工作"""
    
    def __init__(self):
        pass
    
    async def execute(self, task_id: str):
        """执行导入任务"""
        task_queue = TaskQueue()
        task = task_queue.get_task(task_id)
        
        if not task or task.status != TaskStatus.PENDING.value:
            return
        
        try:
            task_queue.start_task(task_id)
            
            kb_id = task.kb_id
            params = task.params
            rebuild = params.get("rebuild", False)
            force_delete = params.get("force_delete", True)
            
            task_queue.update_progress(task_id, message=f"开始导入: {kb_id}")
            
            # ===== 准备阶段 =====
            registry = KnowledgeBaseRegistry()
            kb = registry.get(kb_id)
            
            if not kb:
                raise ValueError(f"知识库不存在: {kb_id}")
            
            vault_root = Path.home() / "Documents" / "Obsidian Vault"
            persist_dir = kb.persist_dir
            
            # 向量存储
            vs = create_vector_store(VectorStoreType.LANCEDB, persist_dir=persist_dir, table_name=kb_id)
            
            # 去重管理器
            dedup_manager = DeduplicationManager(kb_id, persist_dir)
            
            # 收集文件
            all_files = []
            for source_path in kb.source_paths_abs(vault_root):
                if source_path.exists():
                    all_files.extend(source_path.rglob("*.md"))
            
            task_queue.update_progress(task_id, total=len(all_files),
                                     message=f"扫描到 {len(all_files)} 个文件")
            
            # 重建模式
            if rebuild:
                dedup_manager.clear()
                try:
                    vs.delete_table()
                    task_queue.update_progress(task_id, message="已清空旧数据")
                except:
                    pass
            
            # 检测变更
            to_add, to_update, to_delete, unchanged = dedup_manager.detect_changes(all_files, vault_root)
            
            if not to_add and not to_update:
                task_queue.complete_task(task_id, result={"message": "没有变更"})
                return
            
            # 处理删除
            if to_delete and force_delete:
                self._process_deletes(persist_dir, kb_id, to_delete, dedup_manager)
            
            # 收集要处理的文档
            all_docs = [(c.rel_path, c.abs_path) for c in to_add + to_update]
            
            task_queue.update_progress(task_id,
                                     message=f"新增{len(to_add)} 更新{len(to_update)}")
            
            # ===== 真正并行处理（asyncio + ThreadPool）=====
            from llama_index.core.node_parser import SentenceSplitter
            from llama_index.core.schema import Document as LlamaDocument
            from kb.parallel_embedding import get_parallel_processor
            
            lance_store = vs._get_lance_vector_store()
            node_parser = SentenceSplitter(chunk_size=512, chunk_overlap=50)
            
            # 启动写入队列
            await lance_write_queue.start()
            
            # 获取并行处理器
            embed_processor = get_parallel_processor()
            
            processed_files = 0
            processed_chunks = 0
            
            task_queue.update_progress(task_id, message=f"开始处理 {len(all_docs)} 个文件")
            
            for rel_path, abs_path in all_docs:
                try:
                    content = abs_path.read_text(encoding="utf-8", errors="ignore")
                    
                    doc = LlamaDocument(
                        text=content,
                        metadata={"source": "obsidian", "file_path": str(abs_path),
                                 "relative_path": rel_path},
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
                    
                    dedup_manager.mark_processed(abs_path, content, rel_path,
                                               chunk_count=len(nodes), vault_root=vault_root)
                    
                    processed_files += 1
                    
                    if processed_files % 10 == 0:
                        task_queue.update_progress(task_id,
                                                 message=f"处理 {processed_files}/{len(all_docs)} ({processed_chunks} chunks)")
                    
                except Exception as e:
                    logger.warning(f"处理失败 {rel_path}: {e}")
            
            # 等待写入队列清空
            await lance_write_queue._queue.join()
            
            # 保存去重状态
            dedup_manager._save()
            
            # 统计端点使用情况
            stats = embed_processor.get_stats()
            logger.info(f"端点使用统计: {stats}")
            
            task_queue.complete_task(task_id, result={
                "kb_id": kb_id,
                "files": processed_files,
                "nodes": processed_chunks,
                "endpoint_stats": stats,
            })
            
            logger.info(f"任务完成: {task_id}, {processed_files} 文件, {processed_chunks} chunks")
            
        except Exception as e:
            logger.error(f"任务失败 {task_id}: {e}")
            task_queue.complete_task(task_id, error=str(e))
    
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


# ==================== 任务调度器 ====================

class TaskScheduler:
    """
    任务调度器
    
    架构：
    - 任务级别：串行执行（避免 LanceDB 数据库锁）
    - 文件级别：并行处理（本地+远程 Ollama 同时工作）
    """
    
    def __init__(self, max_concurrent: int = 1):
        self.queue = TaskQueue()
        self.executor = ParallelIngestExecutor()
        self._running = True
        self.max_concurrent = max_concurrent
    
    async def run(self):
        """运行调度器"""
        logger.info(f"📋 任务调度器已启动 (最大并发: {self.max_concurrent})")
        
        while self._running:
            try:
                # 获取当前运行中的任务数
                running_count = len(self.executor._running_tasks)
                
                # 如果还有并发余量，提交新任务
                if running_count < self.max_concurrent:
                    pending = self.queue.get_pending(limit=self.max_concurrent - running_count)
                    
                    for task in pending:
                        if task.task_id in self.executor._running_tasks:
                            continue
                        
                        self.executor._running_tasks[task.task_id] = asyncio.create_task(
                            self.executor.execute(task.task_id))
                        logger.info(f"▶️  启动任务: {task.task_id[:8]} ({task.kb_id})")
                
                # 清理已完成的任务引用
                done = [tid for tid, t in list(self.executor._running_tasks.items()) 
                       if t.done() if hasattr(t, 'done')]
                for tid in done:
                    self.executor._running_tasks.pop(tid, None)
                
            except Exception as e:
                logger.error(f"调度器错误: {e}")
            
            await asyncio.sleep(1)
        
        logger.info("📋 任务调度器已停止")
    
    def stop(self):
        """停止调度器"""
        self._running = False


# ==================== 后台运行 ====================

def start_background_executor():
    """启动后台任务执行器"""
    import threading
    
    loop = asyncio.new_event_loop()
    
    def run_loop():
        asyncio.set_event_loop(loop)
        scheduler = TaskScheduler()
        try:
            loop.run_until_complete(scheduler.run())
        except KeyboardInterrupt:
            pass
        finally:
            loop.close()
    
    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    
    return thread


# ==================== 辅助函数 ====================

def show_tasks():
    """显示任务队列状态"""
    task_queue = TaskQueue()
    
    print("\n📋 任务队列状态\n")
    
    all_tasks = task_queue.list_tasks(limit=100)
    pending = [t for t in all_tasks if t.status == TaskStatus.PENDING.value]
    running = [t for t in all_tasks if t.status == TaskStatus.RUNNING.value]
    completed = [t for t in all_tasks if t.status == TaskStatus.COMPLETED.value]
    failed = [t for t in all_tasks if t.status == TaskStatus.FAILED.value]
    
    print(f"   ⏳ 等待中: {len(pending)}")
    print(f"   🔄 执行中: {len(running)}")
    print(f"   ✅ 已完成: {len(completed)}")
    print(f"   ❌ 失败: {len(failed)}")
    
    if running:
        print("\n🔄 正在执行:")
        for task in running:
            print(f"   • {task.kb_id}: {task.progress}% - {task.message}")
    
    if pending:
        print("\n⏳ 等待中:")
        for task in pending[:5]:
            print(f"   • {task.kb_id}: {task.message}")
    
    if completed:
        print("\n✅ 最近完成:")
        for task in completed[:3]:
            print(f"   • {task.kb_id}: {task.result}")
    
    if failed:
        print("\n❌ 失败:")
        for task in failed[:3]:
            print(f"   • {task.kb_id}: {task.error}")
    
    print()


def show_changes(kb_id: str = None):
    """显示变更"""
    registry = KnowledgeBaseRegistry()
    vault_root = Path.home() / "Documents" / "Obsidian Vault"
    
    if kb_id:
        kbs = [registry.get(kb_id)]
    else:
        kbs = registry.list_all()
    
    print("\n📊 变更检测\n")
    
    for kb in kbs:
        if not kb:
            continue
        
        dedup_manager = DeduplicationManager(kb.id, kb.persist_dir)
        
        all_files = []
        for source_path in kb.source_paths_abs(vault_root):
            if source_path.exists():
                all_files.extend(source_path.rglob("*.md"))
        
        to_add, to_update, to_delete, unchanged = dedup_manager.detect_changes(all_files, vault_root)
        
        print(f"{kb.name}:")
        print(f"   当前文件: {len(all_files)}")
        print(f"   新增: {len(to_add)} | 更新: {len(to_update)} | 删除: {len(to_delete)}")
        print()


def list_knowledge_bases():
    """列出所有知识库"""
    registry = KnowledgeBaseRegistry()
    
    print("\n📚 知识库列表\n")
    print(f"{'ID':<20} {'名称':<20} {'状态':<12} {'文件':<8} {'节点':<8}")
    print("-" * 75)
    
    for kb in registry.list_all():
        vs = get_default_vector_store(persist_dir=kb.persist_dir)
        vs.table_name = kb.id
        stats = vs.get_stats()
        
        dedup_manager = DeduplicationManager(kb.id, kb.persist_dir)
        dedup_stats = dedup_manager.get_stats()
        
        status = "✅ 已索引" if stats.get("exists") else "⏳ 未索引"
        
        print(f"{kb.id:<20} {kb.name:<20} {status:<12} "
              f"{dedup_stats.get('total_files', '-'):<8} {stats.get('row_count', '-'):<8}")
    
    print()


# ==================== 主程序 ====================

def main():
    parser = argparse.ArgumentParser(description="知识库导入工具（并行多端点版）")
    parser.add_argument("--list", "-l", action="store_true", help="列出知识库")
    parser.add_argument("--kb", "-k", type=str, help="指定知识库 ID")
    parser.add_argument("--rebuild", "-r", action="store_true", help="强制重建")
    parser.add_argument("--show-changes", action="store_true", help="显示变更")
    parser.add_argument("--tasks", "-t", action="store_true", help="查看任务队列")
    parser.add_argument("--no-delete", action="store_true", help="不同步删除")
    
    args = parser.parse_args()
    
    if args.list:
        list_knowledge_bases()
        return
    
    if args.show_changes:
        show_changes(args.kb)
        return
    
    if args.tasks:
        show_tasks()
        return
    
    # 提交任务
    registry = KnowledgeBaseRegistry()
    
    if args.kb:
        kb = registry.get(args.kb)
        if not kb:
            print(f"❌ 知识库不存在: {args.kb}")
            sys.exit(1)
        
        task_id = submit_ingest_task(args.kb, rebuild=args.rebuild,
                                    force_delete=not args.no_delete)
        
        print(f"\n📝 任务已提交")
        print(f"   知识库: {kb.name}")
        print(f"   任务ID: {task_id}")
        print(f"\n使用 --tasks 查看进度")
        
    else:
        print(f"\n🚀 提交所有知识库导入任务\n")
        
        results = submit_all_ingest_tasks(rebuild=args.rebuild)
        
        print(f"已提交 {len(results)} 个任务:\n")
        for kb_id, task_id, name in results:
            print(f"   • {name}: {task_id}")
    
    # 启动后台执行器
    print(f"\n▶️  启动后台任务执行器...")
    executor_thread = start_background_executor()
    
    # 实时监控
    print("\n📊 实时进度监控 (Ctrl+C 退出)\n")
    
    try:
        while True:
            time.sleep(5)
            show_tasks()
    except KeyboardInterrupt:
        print("\n\n👋 已退出进度监控")


if __name__ == "__main__":
    main()
