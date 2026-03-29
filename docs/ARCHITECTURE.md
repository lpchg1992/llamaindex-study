# LlamaIndex Study 项目架构

## 概述

本项目是一个基于 LlamaIndex 的现代化 RAG（检索增强生成）应用，采用分层架构设计，实现了**并行处理**与**资源保护**的平衡。

## 核心架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        任务执行流程                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   任务提交 ──→ 调度器 ──→ 去重锁 ──→ dedup.db（串行访问）      │
│       │                    │                                   │
│       │                    ▼                                   │
│       │              Embedding 处理                             │
│       │              ┌──────────┬──────────┐                  │
│       │              │ 本地     │ 远程     │ ← 并行执行        │
│       │              │ Ollama   │ Ollama   │                  │
│       │              └──────────┴──────────┘                  │
│       │                    │                                   │
│       │                    ▼                                   │
│       │              LanceDBWriteQueue ──→ LanceDB（串行写入） │
│       │                                                        │
│       ▼                                                        │
│   任务状态更新（可随时查询）                                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 关键设计决策

### 1. 并行 Embedding vs 串行写入

| 层级 | 组件 | 并行/串行 | 原因 |
|------|------|----------|------|
| 计算层 | Embedding | **并行** | 两个 Ollama 端点可同时工作 |
| 存储层 | dedup.db | 串行 | SQLite 不支持高并发 |
| 存储层 | LanceDB | 串行 | WriteQueue 避免锁定 |

### 2. 资源保护机制

#### 去重数据库（Semaphore）

```python
# kb/task_lock.py
class DedupLock:
    async def __aenter__(self):
        await self.lock.acquire()  # Semaphore(1)
        
# 使用方式
async with DedupLock():
    dedup_manager.detect_changes(...)
    dedup_manager.mark_processed(...)
```

#### LanceDB 写入队列

```python
# kb/ingest_vdb.py
class LanceDBWriteQueue:
    async def _worker(self):
        while True:
            item = await self._queue.get()
            lance_store.add(item)  # 串行写入
            self._queue.task_done()
```

### 3. 并行 Embedding 处理器

```python
# kb/parallel_embedding.py
class ParallelEmbeddingProcessor:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=2)
        self.endpoints = [
            {"name": "本地", "url": "http://localhost:11434"},
            {"name": "远程", "url": "http://192.168.31.169:11434"},
        ]
    
    async def process_batch(self, texts):
        # 为每个文本轮流分配端点
        tasks = []
        for i, text in enumerate(texts):
            ep = self.endpoints[i % len(self.endpoints)]
            task = loop.run_in_executor(
                self._executor,
                lambda: self._call_ollama(text, ep)
            )
            tasks.append(task)
        
        # 真正并行执行
        return await asyncio.gather(*tasks)
```

## 架构分层

```
┌─────────────────────────────────────────────────────────────┐
│                        接口层 (Interface)                    │
├─────────────────────────────────────────────────────────────┤
│  API 层 (api.py)        │  CLI 层 (kb/ingest_vdb.py)      │
│  - FastAPI HTTP 接口     │  - 命令行入口                    │
│  - WebSocket 推送        │  - 批处理脚本                    │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                     服务层 (Services)                        │
├─────────────────────────────────────────────────────────────┤
│  kb/services.py                                               │
│  - KnowledgeBaseService   # 知识库管理                       │
│  - VectorStoreService     # 向量存储                         │
│  - ObsidianService        # Obsidian 导入                    │
│  - ZoteroService          # Zotero 导入                     │
│  - SearchService          # 搜索和 RAG                      │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                     业务层 (Business)                       │
├─────────────────────────────────────────────────────────────┤
│  kb/                                                        │
│  ├── task_queue.py            # 任务队列（SQLite）           │
│  ├── task_executor.py        # 任务执行器                   │
│  ├── task_lock.py            # 去重锁（Semaphore）         │
│  ├── parallel_embedding.py    # 并行 Embedding               │
│  ├── ingest_vdb.py           # LanceDB 写入队列             │
│  ├── deduplication.py        # 去重和增量同步               │
│  └── registry.py             # 知识库注册表                  │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                     核心库 (Core)                          │
├─────────────────────────────────────────────────────────────┤
│  src/llamaindex_study/                                    │
│  ├── config.py              # 配置管理                     │
│  ├── logger.py              # 日志工具                     │
│  ├── ollama_utils.py        # Ollama 工具                  │
│  ├── embedding_service.py   # Ollama Embedding 服务        │
│  ├── vector_store.py        # 向量数据库                   │
│  ├── query_engine.py        # 查询引擎                     │
│  └── reranker.py            # 重排序                       │
└─────────────────────────────────────────────────────────────┘
```

## 核心模块说明

### 1. 任务执行流程

```python
# kb/task_executor.py - _execute_obsidian()

async def _execute_obsidian(self, task):
    # 阶段1: 去重阶段（串行访问）
    async with DedupLock():
        dedup_manager.clear()  # 可选：重建
        to_add, to_update = dedup_manager.detect_changes(...)
        all_docs = [(c.rel_path, c.abs_path) for c in to_add + to_update]
    
    # 阶段2: 并行处理（embedding）
    embed_processor = get_parallel_processor()
    lance_write_queue.start()
    
    for rel_path, abs_path in all_docs:
        nodes = node_parser.get_nodes_from_documents([doc])
        
        # 并行获取 embeddings
        texts = [n.get_content() for n in nodes]
        results = await embed_processor.process_batch(texts)
        
        # 串行写入
        await lance_write_queue.enqueue(lance_store, nodes, kb_id)
    
    await lance_write_queue._queue.join()
    
    # 阶段3: 保存状态（串行访问）
    async with DedupLock():
        dedup_manager._save()
```

### 2. 并行 Embedding 处理器

```python
# kb/parallel_embedding.py

class ParallelEmbeddingProcessor:
    """真正的并行处理 - 两个端点同时工作"""
    
    async def process_batch(self, texts: List[str]) -> List[tuple]:
        """
        批量处理，轮流使用端点
        
        chunk_1 → 本地
        chunk_2 → 远程
        chunk_3 → 本地
        chunk_4 → 远程
        ...
        """
        tasks = []
        for i, text in enumerate(texts):
            ep = self.endpoints[i % len(self.endpoints)]
            tasks.append(
                loop.run_in_executor(
                    self._executor,
                    lambda t=text, e=ep: self._call_ollama(t, e)
                )
            )
        
        return await asyncio.gather(*tasks)
```

### 3. 去重数据库锁

```python
# kb/task_lock.py

_dedup_lock = None  # 全局单例

def get_dedup_lock() -> asyncio.Semaphore:
    global _dedup_lock
    if _dedup_lock is None:
        _dedup_lock = asyncio.Semaphore(1)
    return _dedup_lock

class DedupLock:
    """异步上下文管理器"""
    async def __aenter__(self):
        await self.lock.acquire()
    async def __aexit__(self, ...):
        self.lock.release()
```

### 4. LanceDB 写入队列

```python
# kb/ingest_vdb.py

class LanceDBWriteQueue:
    """确保串行写入，避免数据库锁定"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def _worker(self):
        while self._running:
            item = await self._queue.get()
            lance_store, nodes, kb_id = item
            lance_store.add(nodes)  # 串行写入
            self._queue.task_done()
    
    async def enqueue(self, lance_store, nodes, kb_id):
        await self._queue.put((lance_store, nodes, kb_id))
```

## 任务队列系统

```
API 提交任务
    │
    ▼
┌─────────────────────┐
│    TaskQueue        │  # SQLite 持久化
│  - submit_task()    │
│  - get_task()       │
│  - update_progress() │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   TaskScheduler     │  # 调度器（asyncio）
│  - 定时检查待处理任务│
│  - 分配执行器       │
│  - 不限制并发数     │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   TaskExecutor      │  # 异步执行器
│  - _execute_obsidian│
│  - 去重锁保护       │
│  - 并行 embedding   │
│  - 串行写入         │
└─────────┬───────────┘
          │
          ▼
    WebSocket 推送
```

## 数据流

### 文档导入流程

```
1. CLI: poetry run python -m kb.ingest_vdb --kb tech_tools
   或
   API: POST /kbs/tech_tools/ingest/obsidian

2. 任务提交
   └── TaskQueue.submit_task()

3. 任务执行 (TaskExecutor.execute_task)
   ├── 阶段1: 去重（串行）
   │   └── DedupLock() → detect_changes() → mark_processed()
   │
   ├── 阶段2: 并行处理
   │   ├── 解析文档
   │   ├── 切分文本（SentenceSplitter）
   │   ├── 并行 Embedding（本地+远程同时工作）
   │   └── 串行写入 LanceDB（WriteQueue）
   │
   └── 阶段3: 保存状态（串行）
       └── DedupLock() → _save()

4. 进度推送（WebSocket）
   └── WebSocketManager.send_task_update()

5. 任务完成
   └── TaskQueue.complete_task()
       └── {"files": 26, "nodes": 248, "endpoint_stats": {"本地": 124, "远程": 124}}
```

### 检索流程

```
1. API: POST /kbs/tech_tools/query
        Body: {"query": "猪营养配方设计"}

2. 向量检索
   └── LanceDBVectorStore.as_retriever()
       └── similarity_top_k=15

3. Rerank（可选）
   └── SiliconFlowReranker
       └── top_n=5

4. 生成回答
   └── QueryEngine.query()
       └── LLM (SiliconFlow)

5. 返回结果
   └── {"response": "...", "sources": [...]}
```

## 数据库 Schema

### SQLite: 任务队列 (tasks.db)

```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,       -- obsidian, zotero, generic
    status TEXT NOT NULL,          -- pending, running, completed, failed
    kb_id TEXT NOT NULL,
    params TEXT NOT NULL,          -- JSON
    progress INTEGER DEFAULT 0,
    message TEXT DEFAULT '',
    result TEXT,                   -- JSON: {"files": 26, "nodes": 248}
    error TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    source TEXT DEFAULT ''
);
```

### SQLite: 统一数据库 (project.db)

```sql
-- 去重状态
CREATE TABLE dedup_records (
    kb_id TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    hash TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    mtime REAL NOT NULL,
    last_processed REAL NOT NULL,
    chunk_count INTEGER DEFAULT 0,
    PRIMARY KEY (kb_id, rel_path)
);
```

### LanceDB: 向量存储

```
Table: {kb_id}
├── id (TEXT, PRIMARY KEY)      -- 节点 ID
├── text (TEXT)                  -- 文本内容
├── embedding (FLOAT[])          -- 向量 (1024维)
├── metadata (JSON)             -- 元数据
│   ├── source                  -- 来源
│   ├── file_path              -- 文件路径
│   └── relative_path           -- 相对路径
└── _row_id (TEXT)             -- 行 ID
```

## 配置说明

### 环境变量 (.env)

```env
# LLM 配置（硅基流动）
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_API_KEY=your_api_key
SILICONFLOW_MODEL=Pro/deepseek-ai/DeepSeek-V3.2

# Embedding 配置（本地 Ollama）
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBED_MODEL=bge-m3

# 远程 Ollama（GPU 加速）
OLLAMA_REMOTE_URL=http://192.168.31.169:11434

# 索引配置
PERSIST_DIR=/Volumes/online/llamaindex/obsidian
TOP_K=5
```

## 扩展指南

### 添加新的数据源

1. 在 `kb/` 创建处理器
2. 在 `kb/task_executor.py` 添加执行方法
3. 在 `api.py` 添加 API 端点

### 示例：添加 Notion 支持

```python
# 1. 添加执行器 kb/task_executor.py
async def _execute_notion(self, task):
    async with DedupLock():
        # 处理 Notion 页面
        pass

# 2. 添加 API 端点 api.py
@app.post("/kbs/{kb_id}/ingest/notion")
def ingest_notion(kb_id: str, page_id: str):
    task_id = task_queue.submit_task(...)
    return {"task_id": task_id}
```

## 测试

```bash
# 测试并行 Embedding
poetry run python -c "
import asyncio
from kb.parallel_embedding import get_parallel_processor

async def test():
    p = get_parallel_processor()
    results = await p.process_batch(['test'] * 10)
    print(p.get_stats())

asyncio.run(test())
"

# 测试去重锁
poetry run python -c "
import asyncio
from kb.task_lock import DedupLock

async def test():
    async with DedupLock():
        print('Lock acquired')
    print('Lock released')

asyncio.run(test())
"
```
