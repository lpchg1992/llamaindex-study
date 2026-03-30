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
│       │              │ 本地     │ 远程     │ ← 自适应均衡      │
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
| 计算层 | Embedding | **自适应负载均衡** | 快的端点多分配，慢的端点少分配 |
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

### 3. 并行 Embedding 处理器（自适应负载均衡）

```python
# kb/parallel_embedding.py
class ParallelEmbeddingProcessor:
    def __init__(self):
        self.endpoints = [
            EmbeddingEndpoint("本地", DEFAULT_LOCAL_URL),
            EmbeddingEndpoint("远程", DEFAULT_REMOTE_URL),
        ]
        self._executor = ThreadPoolExecutor(max_workers=len(self.endpoints))
        self._chunk_queue = deque()
    
    async def process_batch(self, texts):
        """自适应负载均衡：所有 chunk 入队，快的端点处理更多"""
        # 1. 所有 chunk 入队
        self._chunk_queue = deque(range(len(texts)))
        
        # 2. 每个端点的 worker 不断从队列取任务
        def worker(ep):
            while True:
                chunk_idx = self._chunk_queue.popleft() if self._chunk_queue else None
                if chunk_idx is None:
                    return
                result = ep.process(texts[chunk_idx])
                results[chunk_idx] = result
        
        # 3. 快的端点自然处理更多 chunk
        return results
```

### 4. 失败重试机制

```python
# kb/parallel_embedding.py
def _get_embedding_with_retry(self, text: str, ep: EmbeddingEndpoint) -> EmbeddingResult:
    """带重试的 embedding 获取"""
    for attempt in range(MAX_RETRIES):  # 默认3次
        try:
            embedding = model.get_text_embedding(text)
            self._stats[ep.name] += 1
            return (ep.name, embedding, None)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                logger.debug(f"[{ep.name}] 重试 {attempt + 1}/{MAX_RETRIES}")
    
    self._failures[ep.name] += 1
    return (ep.name, [0.0] * EMBEDDING_DIM, f"重试{MAX_RETRIES}次后失败")
```

## 架构分层

```
┌─────────────────────────────────────────────────────────────┐
│                        接口层 (Interface)                    │
├─────────────────────────────────────────────────────────────┤
│  api.py                     │  src/llamaindex_study/main.py  │
│  - FastAPI HTTP 接口         │  - llamaindex-study CLI         │
│  - WebSocket 推送           │                                 │
├─────────────────────────────┼─────────────────────────────────┤
│  kb/ingest.py               │  kb/ingest_zotero.py            │
│  - Obsidian 批量导入        │  - Zotero 导入 (特定收藏)        │
│                             │                                 │
│  kb/ingest_hitech_history.py│  kb/ingest_vdb.py               │
│  - 高新历史项目导入         │  - LanceDB 写入队列              │
└─────────────────────────────┴─────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                     服务层 (Services)                        │
├─────────────────────────────────────────────────────────────┤
│  kb/services.py                                               │
│  - KnowledgeBaseService   # 知识库管理                       │
│  - VectorStoreService    # 向量存储                         │
│  - ObsidianService       # Obsidian 导入                    │
│  - ZoteroService         # Zotero 导入                      │
│  - GenericService        # 通用文件导入                      │
│  - SearchService         # 搜索和 RAG                       │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                     业务层 (Business)                       │
├─────────────────────────────────────────────────────────────┤
│  kb/                                                        │
│  ├── registry.py             # 知识库注册表                   │
│  ├── task_queue.py          # 任务队列（SQLite）             │
│  ├── task_executor.py       # 任务执行器                     │
│  ├── task_lock.py           # 去重锁（Semaphore）           │
│  ├── parallel_embedding.py   # 并行 Embedding（自适应负载均衡）     │
│  ├── ingest_vdb.py          # LanceDB 写入队列               │
│  ├── deduplication.py        # 去重和增量同步                 │
│  └── database.py            # SQLite 数据库管理              │
├─────────────────────────────────────────────────────────────┤
│  kb/ (独立脚本，非 TaskScheduler 管理)                       │
│  ├── ingest.py              # Obsidian 批量导入脚本          │
│  ├── ingest_zotero.py       # Zotero 导入脚本               │
│  └── ingest_hitech_history.py # 高新历史项目导入脚本         │
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
│  ├── embedding_loadbalancer.py  # 负载均衡                  │
│  ├── vector_store.py        # 向量数据库（多后端）          │
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
    
    # 阶段2: 并行处理（embedding - 自适应负载均衡）
    embed_processor = get_parallel_processor()
    await lance_write_queue.start()
    
    for rel_path, abs_path in all_docs:
        nodes = node_parser.get_nodes_from_documents([doc])
        
        # 并行获取 embeddings（自适应负载均衡）
        texts = [n.get_content() for n in nodes]
        results = await embed_processor.process_batch(texts)
        
        # 串行写入
        await lance_write_queue.enqueue(lance_store, nodes, kb_id)
    
    await lance_write_queue.wait_until_empty()
    
    # 阶段3: 保存状态（串行访问）
    async with DedupLock():
        dedup_manager._save()
```

### 2. 并行 Embedding 处理器（自适应负载均衡）

```python
# kb/parallel_embedding.py

class ParallelEmbeddingProcessor:
    """真正的自适应负载均衡 - 所有端点同时请求，先完成的返回"""
    
    # 配置常量
    EMBEDDING_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
    EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0
    
    async def process_batch(self, texts: List[str]) -> List[EmbeddingResult]:
        """批量处理，自适应负载均衡"""
        async def get_embedding_from_any_endpoint(text: str) -> EmbeddingResult:
            # 同时向所有端点发送请求
            tasks = [try_endpoint(ep) for ep in self.endpoints]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 找出最快成功的
            for r in results:
                if isinstance(r, tuple) and r[2] is None:
                    return r
            
            # 所有端点都失败
            return (self.endpoints[0].name, [0.0] * EMBEDDING_DIM, "所有端点都失败")
        
        return await asyncio.gather(*[get_embedding_from_any_endpoint(t) for t in texts])
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
    async def __aexit__(self, *args):
        self.lock.release()
```

### 4. LanceDB 写入队列

```python
# kb/ingest_vdb.py

class LanceDBWriteQueue:
    """确保串行写入，避免数据库锁定"""
    
    _instance = None
    
    async def _worker(self):
        while self._running:
            item = await self._queue.get()
            lance_store, nodes, kb_id = item
            lance_store.add_nodes(nodes)  # 串行写入
            self._queue.task_done()
    
    async def enqueue(self, lance_store, nodes, kb_id):
        await self._queue.put((lance_store, nodes, kb_id))
    
    async def wait_until_empty(self, timeout: float = None) -> bool:
        """等待队列清空"""
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
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
│  - 并发控制         │
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
1. CLI: poetry run llamaindex-study ingest obsidian tech_tools --folder-path IT
   或
   API: POST /kbs/tech_tools/ingest/obsidian

2. 任务提交
   └── TaskQueue.submit_task()

3. 任务执行 (TaskExecutor.execute_task)
   ├── 阶段1: 去重（串行）
   │   └── DedupLock() → detect_changes() → mark_processed()
   │
   ├── 阶段2: 并行处理（embedding - 自适应负载均衡）
   │   ├── 解析文档
   │   ├── 切分文本（SentenceSplitter）
   │   ├── 并行 Embedding（自适应负载均衡）
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
    current INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    message TEXT DEFAULT '',
    result TEXT,                    -- JSON: {"files": 26, "nodes": 248}
    error TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    source TEXT DEFAULT ''
);
```

### SQLite: 统一数据库 (project.db)

```sql
-- 同步状态
CREATE TABLE sync_states (
    kb_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    hash TEXT NOT NULL,
    mtime REAL NOT NULL,
    doc_id TEXT NOT NULL,
    last_synced REAL NOT NULL,
    PRIMARY KEY (kb_id, file_path)
);

-- 去重记录
CREATE TABLE dedup_records (
    kb_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    hash TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    chunk_count INTEGER DEFAULT 0,
    mtime REAL NOT NULL,
    last_processed REAL NOT NULL,
    PRIMARY KEY (kb_id, file_path)
);

-- 进度记录
CREATE TABLE progress (
    kb_id TEXT UNIQUE NOT NULL,
    task_type TEXT NOT NULL,
    current INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    processed_items TEXT DEFAULT '[]',
    failed_items TEXT DEFAULT '[]',
    started_at REAL,
    completed_at REAL
);

-- 知识库元数据
CREATE TABLE knowledge_bases (
    kb_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    source_type TEXT NOT NULL,
    persist_path TEXT,
    tags TEXT DEFAULT '[]',
    config TEXT DEFAULT '{}'
);

-- 分类规则
CREATE TABLE kb_category_rules (
    kb_id TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    pattern TEXT NOT NULL,
    description TEXT,
    priority INTEGER DEFAULT 0,
    PRIMARY KEY (kb_id, rule_type, pattern)
);
```

### LanceDB: 向量存储

```
Table: {kb_id}
├── id (TEXT, PRIMARY KEY)      -- 节点 ID
├── text (TEXT)                 -- 文本内容
├── embedding (FLOAT[])         -- 向量 (1024维)
├── metadata (JSON)             -- 元数据
│   ├── source                  -- 来源
│   ├── file_path              -- 文件路径
│   └── relative_path           -- 相对路径
└── _row_id (TEXT)             -- 行 ID
```

## 配置说明

### 环境变量 (.env)

```env
# ==================== LLM 配置 ====================
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_API_KEY=your_api_key
SILICONFLOW_MODEL=Pro/deepseek-ai/DeepSeek-V3.2

# ==================== Embedding 配置 ====================
OLLAMA_EMBED_MODEL=bge-m3
EMBEDDING_DIM=1024
OLLAMA_LOCAL_URL=http://localhost:11434
OLLAMA_REMOTE_URL=http://192.168.31.169:11434

# ==================== 存储配置 ====================
OBSIDIAN_VAULT_ROOT=~/Documents/Obsidian Vault
PERSIST_DIR=~/.llamaindex/storage
ZOTERO_STORAGE_DIR=~/.llamaindex/storage/zotero
PERSIST_DIR=~/.llamaindex/storage

# ==================== 任务处理配置 ====================
CHUNK_SIZE=512
CHUNK_OVERLAP=50
PROGRESS_UPDATE_INTERVAL=10
MAX_CONCURRENT_TASKS=10

# ==================== 并行 Embedding 配置 ====================
MAX_RETRIES=3
RETRY_DELAY=1.0
```

### 配置常量（代码中）

```python
# kb/registry.py
DEFAULT_STORAGE_ROOT = Path.home() / ".llamaindex" / "storage"
DEFAULT_VAULT_ROOT = Path.home() / "Documents" / "Obsidian Vault"

# kb/parallel_embedding.py
EMBEDDING_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
DEFAULT_LOCAL_URL = os.getenv("OLLAMA_LOCAL_URL", "http://localhost:11434")
DEFAULT_REMOTE_URL = os.getenv("OLLAMA_REMOTE_URL", "http://localhost:11434")
MAX_RETRIES = 3
RETRY_DELAY = 1.0

# kb/task_executor.py
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "512"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
PROGRESS_UPDATE_INTERVAL = int(os.getenv("PROGRESS_UPDATE_INTERVAL", "10"))
DEFAULT_MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_TASKS", "10"))
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
# 测试并行 Embedding（自适应负载均衡）
poetry run python -c "
import asyncio
from kb.parallel_embedding import get_parallel_processor

async def test():
    p = get_parallel_processor()
    results = await p.process_batch(['test'] * 10)
    print(f'统计: {p.get_stats()}')
    print(f'失败统计: {p.get_failure_stats()}')

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

# 测试任务执行器
poetry run python -c "
from kb.task_executor import TaskExecutor
executor = TaskExecutor()
print(f'任务队列: {executor.queue}')
"
```

## 代码质量特性

- **完整类型注解**: 所有模块都有类型注解，提升代码可读性和 IDE 支持
- **统一日志管理**: 使用 Python logging 模块，支持不同日志级别
- **参数化查询**: SQLite 使用参数化查询，防止 SQL 注入
- **配置常量集中管理**: 所有可配置项通过环境变量控制
- **错误处理完善**: 区分不同错误类型，记录详细日志
- **失败重试机制**: Embedding 请求支持重试，提高稳定性
