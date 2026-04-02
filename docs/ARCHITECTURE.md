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
# kb/lancedb_write_queue.py
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
│  ├── reranker.py           # 重排序                       │
│  ├── node_parser.py        # 统一节点解析器               │
│  ├── query_transform.py    # HyDE、多查询转换、Query Rewrite│
│  ├── response_synthesizer.py # 答案生成模式配置            │
│  └── rag_evaluator.py      # RAG 评估（Ragas 框架）       │
└─────────────────────────────────────────────────────────────┘
```

## 核心模块说明

### 0. 导入编排统一层

- 新增统一编排层：`kb/import_service.py`
- 入口层（CLI/API）不再直接拼任务参数，统一通过 `ImportApplicationService` 组装并派发
- 统一处理三类导入：
  - `generic`（file/batch）
  - `obsidian`
  - `zotero`
- 统一语义：
  - `async_mode` 仅控制执行模式
  - `refresh_topics` 统一控制导入后 topics 刷新
- 当前入口映射：
  - CLI：`llamaindex-study ingest ...` → `ImportApplicationService`
  - API：`/kbs/{kb_id}/ingest*`、`/obsidian/import-all` → `ImportApplicationService`
  - 脚本：`python -m kb.ingest*` → `ImportApplicationService`

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

### 增量同步机制

文档导入时通过 `DeduplicationManager` 实现增量同步，避免重复处理。

**代码位置**：`kb/deduplication.py`

#### 核心概念

| 概念 | 说明 |
|------|------|
| `ChangeType` | 变更类型枚举：ADD（新增）、UPDATE（更新）、DELETE（删除）、UNCHANGE（未变更） |
| `FileChange` | 文件变更记录，包含路径、哈希、变更类型 |
| `ProcessingRecord` | 处理记录，持久化到 dedup.db |

#### 检测流程

```
导入文件列表
    ↓
遍历文件，计算 SHA256 哈希
    ↓
查询 dedup.db 中的历史记录
    ↓
比较哈希值
    ├── 哈希相同 → UNCHANGED（跳过）
    ├── 哈希不同 → UPDATE
    └── 新文件 → ADD
    ↓
同步检测删除的文件（历史记录存在但当前文件不存在 → DELETE）
```

#### 关键方法

| 方法 | 说明 |
|------|------|
| `detect_changes()` | 检测文件变更，返回 (to_add, to_update, to_delete, unchanged) |
| `mark_processed()` | 标记文件为已处理 |
| `clear()` | 清除所有记录（用于重建模式） |
| `_save()` | 保存状态到 dedup.db |

#### 数据库 Schema

```sql
CREATE TABLE dedup_records (
    kb_id TEXT NOT NULL,       -- 知识库 ID
    file_path TEXT NOT NULL,   -- 文件相对路径
    hash TEXT NOT NULL,        -- SHA256 哈希值
    doc_id TEXT NOT NULL,      -- 文档 ID（LlamaIndex 生成）
    chunk_count INTEGER,        -- 分块数量
    mtime REAL NOT NULL,       -- 文件修改时间
    last_processed REAL,       -- 最后处理时间
    PRIMARY KEY (kb_id, file_path)
);
```

#### 与 LanceDB 配合

去重管理层与 LanceDB 的 upsert 机制配合：

```
detect_changes() → 找出需要处理的文件
    ↓
处理文件，生成 nodes（含 doc_id）
    ↓
Upsert 到 LanceDB（基于 doc_id 去重）
    ↓
mark_processed() → 更新 dedup.db 记录
```

#### CLI 控制

```bash
# 增量同步（默认行为）
uv run llamaindex-study ingest obsidian my_kb

# 强制重建（清除 dedup.db，清空 LanceDB）
uv run llamaindex-study ingest obsidian my_kb --rebuild
```

### 4. LanceDB 写入队列

```python
# kb/lancedb_write_queue.py

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

### 5. 节点解析器（统一分块策略）

```python
# src/llamaindex_study/node_parser.py

from llamaindex_study.node_parser import get_node_parser, get_hierarchical_node_parser

# 普通分块（SentenceSplitter 或 SemanticChunker）
parser = get_node_parser(chunk_size=512, chunk_overlap=50)

# 语义分块（基于 embedding 相似度动态决定分块边界）
parser = get_node_parser(chunk_size=512, use_semantic=True)

# 父子节点分块（用于 Auto-Merging Retriever）
parser = get_hierarchical_node_parser()
# 生成三层: [2048, 512, 128]
```

#### HierarchicalNodeParser 层级分块详解

**分块结构**（默认三层）：

```
文档
  └── 父节点 (chunk_size=2048)
        ├── 子节点 (chunk_size=512)
        │     └── 叶子节点 (chunk_size=128)
        │
        └── 子节点 (chunk_size=512)
              └── 叶子节点 (chunk_size=128)
```

**关键特性**：
- 每个子/叶子节点通过 `parent_node_id` 字段引用父节点
- 检索时利用父子关系实现 Auto-Merging

**Auto-Merging 检索流程**：

```
1. 查询向量库 → 检索叶子节点 (128)
           ↓
2. 如果多个相邻叶子节点都相关 → 合并到父节点 (512)
           ↓
3. 如果父节点也高度相关 → 继续合并到根节点 (2048)
           ↓
4. 返回包含更完整上下文的节点
```

**配置参数**：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CHUNK_STRATEGY` | `hierarchical` | 分块策略 |
| `HIERARCHICAL_CHUNK_SIZES` | `2048,512,128` | 各层分块大小 |
| `CHUNK_OVERLAP` | `50` | 分块重叠大小 |
| `USE_AUTO_MERGING` | `false` | 是否启用 Auto-Merging 检索 |

**存储的节点关系字段**：
- `node_id`: 节点唯一ID
- `parent_node_id`: 父节点ID（根节点此字段为空）
- `prev_node_id` / `next_node_id`: 兄弟节点关系

**支持的解析器**：

| 解析器 | 说明 | 适用场景 |
|--------|------|---------|
| `SentenceSplitter` | 固定大小分块 | 默认，向后兼容 |
| `SemanticChunker` | 基于语义的分块 | 需要启用 USE_SEMANTIC_CHUNKING |
| `HierarchicalNodeParser` | 父子节点分块 | 启用 Auto-Merging Retriever |

### 6. 模型管理系统

模型管理系统提供统一的 LLM/Embedding/Reranker 模型管理，支持多供应商（siliconflow、ollama、ollama_homepc 等）。

采用**供应商 + 模型**两级管理架构：

- **供应商 (Vendor)**：存储供应商配置（API端点、API密钥）
- **模型 (Model)**：存储模型配置，关联到供应商，支持三种类型：
  - `llm`: 大语言模型（如 DeepSeek-V3.2、LFM 2.5）
  - `embedding`: Embedding 模型（如 bge-m3）
  - `reranker`: 重排序模型

#### 核心组件

| 组件 | 文件 | 说明 |
|------|------|------|
| `VendorDB` | `kb/database.py` | 供应商数据库操作 |
| `ModelDB` | `kb/database.py` | 模型数据库操作 |
| `ModelRegistry` | `src/llamaindex_study/config.py` | 模型注册表（单例） |
| `ollama_utils` | `src/llamaindex_study/ollama_utils.py` | LLM 和 Embedding 创建配置 |

#### ID规范

- **供应商ID**：如 `siliconflow`, `ollama`, `ollama_homepc`
- **模型ID**：格式 `{vendor_id}/{model-name}`，如 `siliconflow/DeepSeek-V3.2`, `ollama/bge-m3:latest`

#### 核心方法

**VendorDB** (`kb/database.py`):
- `upsert()`: 创建或更新供应商
- `get()`: 获取指定供应商
- `get_all()`: 获取所有供应商
- `delete()`: 删除供应商
- `set_active()`: 设置供应商激活状态

**ModelDB** (`kb/database.py`):
- `upsert()`: 创建或更新模型
- `get()`: 获取指定模型
- `get_all()`: 获取所有模型
- `get_by_type()`: 按类型获取模型
- `get_default()`: 获取默认模型
- `delete()`: 删除模型
- `set_default()`: 设置默认模型

**ModelRegistry** (`src/llamaindex_study/config.py`):
- `get_model()`: 获取指定模型
- `list_models()`: 列出所有模型
- `get_by_type()`: 按类型获取
- `get_default()`: 获取默认模型
- `reload()`: 重新从数据库加载

**ollama_utils** (`src/llamaindex_study/ollama_utils.py`):
- `create_llm()`: 创建 LLM 实例（支持 model_id 参数，自动从供应商获取配置）
- `configure_llm_by_model_id()`: 根据 model_id 配置全局 LLM
- `configure_global_embed_model()`: 配置全局 Embedding 模型

#### API 端点

**供应商管理**：

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/vendors` | 列出所有供应商 |
| POST | `/vendors` | 创建/更新供应商 |
| GET | `/vendors/{vendor_id}` | 获取指定供应商 |
| DELETE | `/vendors/{vendor_id}` | 删除供应商 |

**模型管理**：

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/models` | 列出所有模型（支持 `?type=` 筛选） |
| POST | `/models` | 创建/更新模型（供应商不存在时自动创建） |
| GET | `/models/{model_id}` | 获取指定模型 |
| DELETE | `/models/{model_id}` | 删除模型 |
| PUT | `/models/{model_id}/default` | 设置默认模型 |

**类型筛选**: `GET /models?type=llm`、`GET /models?type=embedding`、`GET /models?type=reranker`

#### CLI 命令

```bash
# 供应商管理
llamaindex-study vendor list
llamaindex-study vendor add ollama_homepc --name "Ollama HomePC" --api-base "http://192.168.31.169:11434"
llamaindex-study vendor remove ollama_homepc

# 模型管理
llamaindex-study model list
llamaindex-study model list --type embedding
llamaindex-study model add ollama/bge-m3:latest --vendor-id ollama --name "BGE-M3" --type embedding
llamaindex-study model add ollama_homepc/bge-m3:latest --vendor-id ollama_homepc --name "BGE-M3 (HomePC)" --type embedding
llamaindex-study model set-default ollama/bge-m3:latest
```

#### 使用示例

```python
from llamaindex_study.ollama_utils import create_llm, configure_llm_by_model_id

# 方式1: 创建时指定模型（自动使用供应商配置）
llm = create_llm(model_id="ollama/lfm2.5-thinking:latest")

# 方式2: 全局配置后使用
configure_llm_by_model_id("ollama/lfm2.5-thinking:latest")
# 之后 create_llm() 会自动使用该模型
```
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
1. CLI: uv run llamaindex-study ingest obsidian tech_tools --folder-path IT
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

### 自动路由机制

当使用 `QueryRouter` 进行自动路由查询时（不指定 `kb_id`）：

```
用户查询
    │
    ▼
QueryRouter.route()
    │
    ├─→ 1. LLM 路由 (_llm_route)
    │     - 收集所有 KB 的 topics
    │     - 发送给 LLM (DeepSeek-V3.2)
    │     - LLM 判断哪些 KB 相关
    │     - 成功 → 返回 KB ID 列表
    │
    └─→ 失败时降级 → 2. 关键词匹配路由 (_keyword_route)
          - 分词 query
          - 匹配 KB topics
          - 计算得分排序
          - 返回 KB ID 列表
```

**代码位置**：`kb/services.py` → `QueryRouter`

| 方法 | 说明 |
|------|------|
| `route()` | 主入口，协调 LLM 路由和关键词匹配 |
| `_llm_route()` | 调用 LLM 智能选择 KB |
| `_keyword_route()` | 关键词匹配（fallback） |

### Topics 生成机制

Topics 是知识库的主题词标签，用于自动路由时的知识库选择。

**代码位置**：`kb/topic_analyzer.py` → `TopicAnalyzer`

#### 触发生成

| 时机 | 说明 |
|------|------|
| 文档导入完成 | `_execute_obsidian()`、`_execute_zotero()`、`_execute_generic()` 完成后自动调用 |
| 手动触发 | `kb topics` / `kb topics-local` CLI 命令 |

#### 生成流程

```
文档导入完成
    ↓
_update_kb_topics(kb_id, has_new_docs=True)
    ↓
get_kb_documents_for_analysis() 
    - 从 LanceDB 采样最多 50 个文档
    ↓
TopicAnalyzer.extract_topics(docs, use_llm=True)
    ↓
_llm_extract_topics()
    - 合并前 30 个文档（最多 8000 字符）
    - 调用 SiliconFlow API (DeepSeek-V3.2)
    - Prompt 要求提取 15-25 个专业术语
    - 过滤停用词和垃圾词
    ↓
merge_topics()
    - 与现有 topics 合并
    - 去重、相似度检测
    ↓
_is_significant_change()
    - Jaccard 相似度 < 0.7 时认为显著变化
    ↓
db.update_topics() → 写入数据库
```

#### LLM 提取 Prompt

```python
prompt = """你是一个专业的知识库主题分析助手。请从以下文档内容中提取15-25个主题词。

要求：
1. 只提取专业术语、学术名词、具体概念（如蛋白质代谢、猪营养配方、线性规划等）
2. 只提取名词性词汇，不要动词、形容词、副词、介词
3. 优先提取能体现学科领域特色的专业词汇
4. 用换行符分隔，每行一个词

---文档内容---
{combined_text}
---文档结束---

主题词（每行一个）："""
```

#### 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_TOPICS` | 30 | 最多保留主题词数量 |
| `TOPIC_THRESHOLD` | 0.3 | 主题词得分阈值 |
| `SAMPLE_SIZE` | 50 | 从 LanceDB 采样文档数 |

#### 存储位置

- **数据库表**：`knowledge_bases`
- **字段**：`topics` (JSON 数组)
- **操作方法**：`db.update_topics()`、`db.get_topics()`

#### CLI 命令

```bash
# 使用远程 LLM（DeepSeek-V3.2）
uv run llamaindex-study kb topics <kb_id>

# 使用本地模型（统计方法）
uv run llamaindex-study kb topics-local <kb_id>

# 分析所有知识库
uv run llamaindex-study kb topics --all --update
```

### 检索流程

```
1. API: POST /query
        Body: {"query": "猪营养配方设计", "kb_ids": "tech_tools"}

2. 查询转换（可选）
   ├── HyDE: 生成假设性文档 → 用假设性文档检索
   ├── Multi-Query: 生成多个查询变体 → 分别检索 → 融合结果
   └── Query Rewrite: 改写查询 → 检索

3. 向量检索
   └── index.as_retriever()
       └── similarity_top_k=15

4. (可选) 混合搜索融合
   └── BM25Retriever + QueryFusionRetriever

5. (可选) Auto-Merging
   └── 合并叶子节点到父节点

6. Rerank（可选）
   └── SiliconFlowReranker
       └── top_n=5

7. 生成回答
   └── QueryEngine.query()
       └── Response Synthesizer (compact/refine/tree_summarize/...)
       └── LLM (SiliconFlow)

8. 返回结果
   └── {"response": "...", "sources": [...]}
```

### 检索模式

#### 纯向量检索（默认）
```
用户查询 → 向量检索器 → Top-K 结果
```

#### 混合搜索（需启用 USE_HYBRID_SEARCH=true）
```
用户查询
    │
    ├── 向量检索器 (similarity_top_k=15)
    │
    └── BM25 检索器 (similarity_top_k=15)
            │
            ▼
    QueryFusionRetriever 融合
    (mode=relative_score, RRF, 或 dist_based_score)
            │
            ▼
        融合结果
            │
            ▼
    (可选) Reranker 重排
            │
            ▼
        Top-K 结果
```

#### Auto-Merging Retriever（需启用 USE_AUTO_MERGING=true，需配合 HierarchicalNodeParser 构建的知识库）
```
用户查询 → 叶子节点检索 → 合并到父节点 → 更完整的上下文
```

#### HyDE 查询转换（需启用 USE_HYDE=true）
```
用户查询 → LLM 生成假设性答案 → 用假设性答案的 embedding 检索真实文档
```

#### 多查询转换（需启用 USE_MULTI_QUERY=true）
```
用户查询 → LLM 生成 N 个查询变体 → 分别检索 → RRF 融合结果
```

**配置**：通过 `MULTI_QUERY_NUM` 环境变量控制生成变体数量（默认 3 个）

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

-- 模型供应商
CREATE TABLE vendors (
    id TEXT PRIMARY KEY,              -- 供应商ID: siliconflow, ollama
    name TEXT NOT NULL,               -- 显示名称: SiliconFlow, Ollama
    api_base TEXT,                    -- API端点
    api_key TEXT,                     -- API密钥（Ollama不需要）
    is_active INTEGER DEFAULT 1,      -- 是否激活
    created_at REAL,                  -- 创建时间戳
    updated_at REAL                   -- 更新时间戳
);

-- 模型管理
CREATE TABLE models (
    id TEXT PRIMARY KEY,              -- 模型ID，格式: vendor_id/model-name
    vendor_id TEXT NOT NULL,          -- 供应商ID (FK to vendors.id)
    name TEXT NOT NULL,               -- 显示名称或实际模型名
    type TEXT NOT NULL,               -- 类型: llm, embedding, reranker
    is_active INTEGER DEFAULT 1,      -- 是否激活
    is_default INTEGER DEFAULT 0,     -- 是否默认
    config TEXT DEFAULT '{}',         -- 其他配置(JSON)
    created_at REAL,                  -- 创建时间戳
    updated_at REAL,                  -- 更新时间戳
    FOREIGN KEY (vendor_id) REFERENCES vendors(id)
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
PERSIST_DIR=/Volumes/online/llamaindex
ZOTERO_PERSIST_DIR=/Volumes/online/llamaindex/zotero

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
# 注意：实际路径由环境变量 PERSIST_DIR 和 ZOTERO_PERSIST_DIR 配置
# 通用 KB: PERSIST_DIR/{kb_id}/
# Zotero KB: ZOTERO_PERSIST_DIR/{kb_id}/
DEFAULT_STORAGE_ROOT = Path.home() / ".llamaindex" / "storage"  # 仅作默认值参考
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
uv run python -c "
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
uv run python -c "
import asyncio
from kb.task_lock import DedupLock

async def test():
    async with DedupLock():
        print('Lock acquired')
    print('Lock released')

asyncio.run(test())
"

# 测试任务执行器
uv run python -c "
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
