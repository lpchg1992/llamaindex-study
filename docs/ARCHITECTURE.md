# LlamaIndex Study 项目架构

## 概述

本项目是一个基于 LlamaIndex 的现代化 RAG（检索增强生成）应用，采用分层架构设计，实现了业务逻辑与接口层的完全解耦。

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
│  kb/services.py                                           │
│  - KnowledgeBaseService   # 知识库管理                       │
│  - VectorStoreService   # 向量存储                         │
│  - ObsidianService      # Obsidian 导入                     │
│  - ZoteroService        # Zotero 导入                       │
│  - GenericService       # 通用文件导入                      │
│  - SearchService        # 搜索和 RAG                       │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                     业务层 (Business)                       │
├─────────────────────────────────────────────────────────────┤
│  kb/                                                    │
│  ├── obsidian_processor.py   # Obsidian 文档处理          │
│  ├── zotero_processor.py      # Zotero 文献处理            │
│  ├── generic_processor.py     # 通用文件处理               │
│  ├── document_processor.py     # 文档解析和切分             │
│  ├── deduplication.py         # 去重和增量同步              │
│  ├── task_queue.py            # 任务队列                   │
│  ├── task_executor.py         # 任务执行器                 │
│  └── registry.py               # 知识库注册表               │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                     核心库 (Core)                          │
├─────────────────────────────────────────────────────────────┤
│  src/llamaindex_study/                                    │
│  ├── config.py              # 配置管理                    │
│  ├── logger.py              # 日志工具                    │
│  ├── ollama_utils.py        # Ollama 工具（批量 embedding）│
│  ├── embedding_service.py    # Ollama Embedding 服务        │
│  ├── vector_store.py        # 向量数据库                   │
│  ├── query_engine.py        # 查询引擎                     │
│  └── reranker.py            # 重排序                      │
└─────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                     外部依赖 (External)                      │
├─────────────────────────────────────────────────────────────┤
│  - Ollama              # 本地 Embedding 服务               │
│  - LanceDB             # 向量数据库                       │
│  - SiliconFlow          # LLM 服务（OpenAI 兼容）          │
│  - SQLite               # 任务队列和去重状态               │
│  - Zotero               # 文献数据库                       │
│  - Obsidian             # 笔记数据库                       │
└─────────────────────────────────────────────────────────────┘
```

## 核心模块说明

### 1. 服务层 (kb/services.py)

服务层是业务逻辑的统一入口，API 和 CLI 都通过这里调用业务功能。

```python
from kb.services import (
    KnowledgeBaseService,  # 知识库 CRUD
    VectorStoreService,    # 向量存储操作
    ObsidianService,       # Obsidian 导入
    ZoteroService,         # Zotero 导入
    GenericService,         # 通用文件导入
    SearchService,          # 搜索和问答
)
```

**设计原则:**
- API 层只负责接收请求和返回响应
- 业务逻辑集中在服务层
- 所有模块通过服务层交互，避免直接耦合

### 2. 文档处理流程

```
文件/文件夹
    │
    ▼
┌─────────────────────┐
│  DocumentProcessor  │  # 统一文档处理
│  - PDF 检测/转换    │
│  - Office 解析      │
│  - Markdown 清理    │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  SentenceSplitter  │  # 文本切分
│  chunk_size=512    │
│  chunk_overlap=50  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ BatchEmbeddingHelper│  # 批量 Embedding
│  - 批量请求         │
│  - 并发控制         │
│  - 失败重试        │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  DeduplicationMgr  │  # 去重管理
│  - 文件哈希检测     │
│  - 增量同步        │
│  - 状态持久化      │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   LanceDBVectorStore│  # 向量存储
│   - add()           │
│   - upsert()       │
│   - load_index()   │
└─────────────────────┘
```

### 3. 任务队列系统

```
API 提交任务
    │
    ▼
┌─────────────────────┐
│    TaskQueue        │  # SQLite 持久化
│  - submit_task()    │
│  - get_task()       │
│  - update_progress()│
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   TaskScheduler     │  # 调度器
│  - 定时检查待处理任务│
│  - 分配执行器       │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   TaskExecutor      │  # 异步执行器
│  - 本地并发控制     │
│  - 远程并发控制     │
│  - 取消支持        │
└─────────┬───────────┘
          │
          ▼
    WebSocket 推送
```

### 4. Ollama 负载均衡

```
                  ┌─────────────────┐
                  │ EmbeddingService│
                  └────────┬────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│   本地端点     │  │   远程端点 1  │  │   远程端点 2  │
│ localhost:11434│  │192.168.31.169│  │192.168.31.63 │
│   Semaphore=1 │  │   Semaphore=1 │  │   Semaphore=1 │
└───────────────┘  └───────────────┘  └───────────────┘

# 并行导入策略
- 奇数文件夹 → 本地 Ollama
- 偶数文件夹 → 远程 Ollama
```

### 5. 批量 Embedding 优化

```python
# 优化前：串行调用
for node in nodes:
    node.embedding = embed_model.get_text_embedding(node.text)

# 优化后：批量 + 并发
texts = [node.text for node in nodes]
embeddings = await batch_helper.embed_documents_async(texts)
# ├── 使用 asyncio.gather 并发请求
# ├── 批量大小 batch_size=10
# └── 并发数 max_concurrency=3
```

## 数据流

### 文档导入流程

```
1. CLI: poetry run python -m kb.ingest_vdb --kb tech_tools
   或
   API: POST /kbs/tech_tools/ingest/obsidian

2. 任务提交
   └── TaskQueue.submit_task()

3. 任务执行
   └── TaskExecutor.execute_task()
       ├── 检测增量变化（DeduplicationManager）
       ├── 解析文档（ObsidianProcessor）
       ├── 切分文本（SentenceSplitter）
       ├── 生成 Embedding（BatchEmbeddingHelper）
       └── 保存到 LanceDB

4. 进度推送（WebSocket）
   └── WebSocketManager.send_task_update()

5. 任务完成
   └── TaskQueue.complete_task()
```

### 检索流程

```
1. API: POST /kbs/tech_tools/query
        Body: {"query": "猪营养配方设计"}

2. 加载索引
   └── LanceDBVectorStore.load_index()

3. 向量检索
   └── VectorStoreIndex.as_retriever()
       └── similarity_top_k=15

4. Rerank（可选）
   └── SiliconFlowReranker
       └── top_n=5

5. 生成回答
   └── QueryEngine.query()
       └── LLM (SiliconFlow)

6. 返回结果
   └── {"response": "...", "sources": [...]}
```

## 关键设计模式

### 1. 单例模式

```python
# TaskQueue
class TaskQueue:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

# 全局实例
task_queue = TaskQueue()
```

### 2. 工厂模式

```python
# 向量存储工厂
def create_vector_store(store_type, persist_dir, table_name):
    if store_type == VectorStoreType.LANCEDB:
        return LanceDBVectorStore(...)
    elif store_type == VectorStoreType.CHROMA:
        return ChromaVectorStore(...)
```

### 3. 策略模式

```python
# 检索模式
query_engine = create_query_engine(kb_id, mode="hybrid")  # 向量 + 关键词
query_engine = create_query_engine(kb_id, mode="vector")  # 仅向量
```

### 4. 观察者模式

```python
# WebSocket 推送
class WebSocketManager:
    async def send_task_update(self, task_id, data):
        # 通知所有订阅者
        for ws in self._task_connections[task_id]:
            await ws.send_text(message)
```

## 数据库 Schema

### SQLite: 任务队列 (tasks.db)

```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,       -- zotero, obsidian, generic, rebuild
    status TEXT NOT NULL,          -- pending, running, completed, failed
    kb_id TEXT NOT NULL,
    params TEXT NOT NULL,          -- JSON
    progress INTEGER DEFAULT 0,
    current INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    message TEXT DEFAULT '',
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

-- 处理进度
CREATE TABLE progress (
    kb_id TEXT PRIMARY KEY,
    total_items INTEGER,
    processed_items TEXT,        -- JSON
    failed_items TEXT,           -- JSON
    converted_files TEXT,         -- JSON
    started_at REAL,
    last_item TEXT,
    total_nodes INTEGER DEFAULT 0
);

-- 知识库元数据
CREATE TABLE knowledge_bases (
    kb_id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    config TEXT,                 -- JSON
    created_at REAL NOT NULL,
    updated_at REAL
);
```

### LanceDB: 向量存储

```
Table: {kb_id}
├── id (TEXT, PRIMARY KEY)      -- 节点 ID
├── text (TEXT)                  -- 文本内容
├── embedding (FLOAT[])          -- 向量
├── metadata (JSON)             -- 元数据
│   ├── source                  -- 来源
│   ├── file_path              -- 文件路径
│   ├── relative_path           -- 相对路径
│   └── tags                    -- 标签
└── _row_id (TEXT)              -- 行 ID
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

# 索引配置
PERSIST_DIR=/Volumes/online/llamaindex/obsidian
TOP_K=5

# Reranker 配置
USE_RERANKER=false
RERANK_MODEL=Pro/BAAI/bge-reranker-v2-m3

# 向量数据库配置
VECTOR_STORE_TYPE=lancedb
VECTOR_TABLE_NAME=llamaindex
```

### 知识库注册 (kb/registry.py)

```python
KNOWLEDGE_BASES = [
    KnowledgeBase(
        id="swine_nutrition",
        name="🐷 猪营养技术库",
        description="猪营养学理论...",
        source_paths=["技术理论及方法", "饲料原料笔记"],
        persist_name="kb_swine_nutrition",
    ),
    # ...
]
```

## 性能优化

### 1. 批量 Embedding

```python
# 使用批量接口减少网络开销
class BatchEmbeddingHelper:
    async def embed_documents_async(self, texts: List[str]):
        # 分批处理
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            # 并发请求
            tasks = [self.embed_single(t) for t in batch]
            await asyncio.gather(*tasks)
```

### 2. 增量同步

```python
# 只处理变化的文件
to_add, to_update, to_delete, unchanged = dedup_manager.detect_changes(
    files, vault_root
)

# 未变化的文件跳过
for change in unchanged:
    print(f"⏭️  跳过未变化: {change.rel_path}")
```

### 3. 并发控制

```python
# 本地和远程各一个并发
self._local_sem = asyncio.Semaphore(1)
self._remote_sem = asyncio.Semaphore(1)

async with self._local_sem:
    # 处理本地任务
    pass

async with self._remote_sem:
    # 处理远程任务
    pass
```

## 扩展指南

### 添加新的数据源

1. 在 `kb/` 创建处理器（如 `notion_processor.py`）
2. 在 `kb/services.py` 添加服务类
3. 在 `kb/task_executor.py` 添加执行方法
4. 在 `api.py` 添加 API 端点

### 示例：添加 Notion 支持

```python
# 1. 创建处理器 kb/notion_processor.py
class NotionProcessor:
    def import_page(self, page_id, vector_store, embed_model):
        # 处理逻辑
        pass

# 2. 添加服务 kb/services.py
class NotionService:
    @staticmethod
    def import_page(kb_id, page_id):
        processor = NotionProcessor()
        return processor.import_page(...)

# 3. 添加执行器 kb/task_executor.py
async def _execute_notion(self, task):
    NotionService.import_page(task.kb_id, task.params["page_id"])

# 4. 添加 API 端点 api.py
@app.post("/kbs/{kb_id}/ingest/notion")
def ingest_notion(kb_id: str, req: NotionRequest):
    task_id = task_queue.submit_task(...)
    task_executor.submit_and_start(task_id, loop)
    return {"task_id": task_id}
```

## 测试

```bash
# 运行所有测试
poetry run pytest

# 运行特定模块测试
poetry run pytest tests/test_vector_store.py

# 覆盖率报告
poetry run pytest --cov=src --cov-report=html
```
