# LlamaIndex 学习项目

一个基于 LlamaIndex v0.14+ 的现代化 RAG（检索增强生成）学习项目，支持**本地/远程 Ollama 并行处理**。

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
│       │              │ 本地     │ 远程     │ ← 自适应负载均衡  │
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

## 主要特性

| 特性 | 说明 | 启用方式 |
|------|------|---------|
| **并行 Embedding** | 本地 + 远程 Ollama 自适应负载均衡 | 默认启用 |
| **失败重试机制** | 每个端点最多重试 3 次 | 默认启用 |
| **去重串行访问** | Semaphore(1) 保护 dedup.db | 默认启用 |
| **LanceDB 串行写入** | WriteQueue 保证写入顺序 | 默认启用 |
| **任务队列** | 异步提交，随时查询状态 | 默认启用 |
| **增量同步** | 基于文件哈希检测变更 | 默认启用 |
| **LLM 主题提取** | 导入时自动提取专业主题词 | 默认启用 |
| **自动路由** | 根据问题内容自动选择知识库 | 默认启用 |
| **相似度去重** | 避免重复主题词 | 默认启用 |
| **混合搜索** | 向量检索 + BM25 关键词融合 | `USE_HYBRID_SEARCH=true` |
| **HyDE 查询转换** | 假设文档嵌入，提升检索质量 | `USE_HYDE=true` 或 API 参数 |
| **多查询转换** | 生成多个查询变体，减少遗漏 | `USE_MULTI_QUERY=true` 或 API 参数 |
| **Auto-Merging** | 检索时自动合并子节点为父节点（需 hierarchical 分块） | `USE_AUTO_MERGING=true` 或 API 参数 |
| **语义分块** | 基于 embedding 相似度的智能分块 | `USE_SEMANTIC_CHUNKING=true` |
| **层级分块** | 父子节点分块（Auto-Merging 基础） | `CHUNK_STRATEGY=hierarchical`（默认） |
| **Response Synthesizer** | 多样化答案生成模式 | API 参数 `response_mode` |
| **RAG 评估** | 基于 Ragas 框架的评估指标 | 默认启用 |

## 环境要求

- Python >= 3.11
- **UV**（Python 包管理器）
- **本地 Ollama**：Embedding 服务
- **远程 Ollama**（可选）：GPU 加速
- 硅基流动 API Key（注册送 14 元额度：https://www.siliconflow.com）

## 快速开始

### 1. 安装 Ollama

```bash
# 安装 Ollama
brew install ollama

# 启动 Ollama（后台运行）
ollama serve

# 下载 embedding 模型（支持中英文，推荐 bge-m3）
ollama pull bge-m3
```

### 2. 配置远程 Ollama（可选）

```bash
# 在远程机器上启动 Ollama
ollama serve

# 确保 bge-m3 模型可用
ollama pull bge-m3
```

### 3. 安装项目

```bash
cd ~/文档/GitHub/llamaindex-study

# 安装依赖
uv sync

# 复制并编辑环境变量
cp .env.example .env
```

### 4. 配置 .env

```env
# ==================== LLM 配置 ====================
SILICONFLOW_API_KEY=你的密钥
SILICONFLOW_MODEL=Pro/deepseek-ai/DeepSeek-V3.2

# ==================== Embedding 配置 ====================
OLLAMA_EMBED_MODEL=bge-m3
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_LOCAL_URL=http://localhost:11434
OLLAMA_REMOTE_URL=http://192.168.31.169:11434

# ==================== 存储配置 ====================
OBSIDIAN_VAULT_ROOT=~/Documents/Obsidian Vault
PERSIST_DIR=/Volumes/online/llamaindex
ZOTERO_PERSIST_DIR=/Volumes/online/llamaindex/zotero

# ==================== 检索配置（可选）====================
USE_HYBRID_SEARCH=false
USE_HYDE=false
USE_MULTI_QUERY=false
USE_AUTO_MERGING=false
RESPONSE_MODE=compact
```

### 5. 运行

```bash
# 启动 API 服务（默认端口 37241）
uv run python api.py

# 启动交互式查询
uv run llamaindex-study
```

## 项目结构

```
llamaindex-study/
├── api.py                    # FastAPI 服务入口
├── main.py                   # 交互式查询 CLI
│
├── src/llamaindex_study/    # 核心库
│   ├── config.py             # 配置管理
│   ├── logger.py             # 日志工具
│   ├── embedding_service.py   # Ollama Embedding 服务
│   ├── embedding_loadbalancer.py  # 负载均衡
│   ├── ollama_utils.py      # Ollama 工具
│   ├── vector_store.py       # 向量数据库管理（多后端）
│   ├── query_engine.py       # 查询引擎（支持 HyDE、多查询）
│   ├── reranker.py           # 重排序（SiliconFlow）
│   ├── node_parser.py        # 统一节点解析器
│   ├── query_transform.py    # HyDE、多查询转换、Query Rewrite
│   ├── response_synthesizer.py # 答案生成模式配置
│   └── rag_evaluator.py      # RAG 评估（Ragas）
│
├── kb/                      # 知识库模块
│   ├── registry.py           # 知识库注册表
│   ├── database.py           # SQLite 数据库管理
│   ├── task_queue.py         # 任务队列
│   ├── task_executor.py      # 任务执行器
│   ├── task_lock.py          # 去重数据库锁（Semaphore）
│   ├── parallel_embedding.py  # 并行 Embedding 处理器
│   ├── ingest_vdb.py         # LanceDB 写入队列
│   ├── obsidian_processor.py # Obsidian 笔记导入
│   ├── obsidian_reader.py    # Obsidian 笔记读取
│   ├── obsidian_config.py    # Obsidian 配置
│   ├── deduplication.py       # 去重管理
│   ├── category_classifier.py # 分类器
│   ├── sync_state.py         # 同步状态
│   ├── document_processor.py  # 文档处理器
│   ├── generic_processor.py   # 通用文件处理器
│   ├── zotero_processor.py    # Zotero 导入器
│   ├── zotero_reader.py      # Zotero 读取器
│   ├── websocket_manager.py   # WebSocket 管理
│   ├── topic_analyzer.py     # LLM 主题词提取
│   ├── keyword_extractor.py  # LLM 关键词提取
│   ├── services.py           # 统一服务层
│   └── scripts/
│       └── analyze_kb_topics.py  # 知识库主题分析脚本
│
└── docs/
    ├── API.md               # API 详细文档
    ├── CLI.md               # CLI 完整使用文档
    └── ARCHITECTURE.md      # 架构文档
```

## 核心功能详解

### 1. 并行 Embedding（自适应负载均衡）

```
Chunk 队列：
[Chunk 1] [Chunk 2] [Chunk 3] [Chunk 4] ...

端点分配（快的多处理）：
本地 Ollama  ──→ Chunk 1, Chunk 3, Chunk 5 ...
远程 Ollama  ──→ Chunk 2, Chunk 4 ...
```

使用 `asyncio + ThreadPoolExecutor` 实现，所有任务进入共享队列，处理快的端点自动分配更多任务。

### 2. 检索模式

#### 纯向量检索（默认）
```
用户查询 → 向量检索器 → Top-K 结果
```

#### 混合搜索（需启用 `USE_HYBRID_SEARCH=true`）
```
用户查询
    ├── 向量检索器
    └── BM25 检索器
            ↓
    QueryFusionRetriever 融合
```

#### HyDE 查询转换（需启用 `USE_HYDE=true`）
```
用户查询 → LLM 生成假设性答案 → 用假设性答案的 embedding 检索真实文档
```

#### 多查询转换（需启用 `USE_MULTI_QUERY=true`）
```
用户查询 → LLM 生成 N 个查询变体 → 分别检索 → 融合结果
```

#### Auto-Merging Retriever（需启用 `USE_AUTO_MERGING=true`，且 KB 使用 hierarchical 分块）
```
用户查询 → 叶子节点检索 → 合并到父节点 → 更完整的上下文
```

> 如果 KB 使用 `sentence` 或 `semantic` 分块策略，Auto-Merging 会自动回退到普通 retriever。

### 3. Response Synthesizer 模式

| 模式 | 说明 |
|------|------|
| `compact` | 压缩检索结果后生成答案（默认） |
| `refine` | 迭代优化答案 |
| `tree_summarize` | 构建答案树结构 |
| `simple_summarize` | 简单拼接检索结果 |
| `no_text` | 仅返回检索结果，不生成答案 |
| `accumulate` | 累积式生成 |

## 使用方式

### API 方式

```bash
# 启动服务（端口 37241）
uv run python api.py

# API 文档
# http://localhost:37241/docs (Swagger)
# http://localhost:37241/api-docs (Markdown)

# 提交 Obsidian 导入任务
curl -X POST "http://localhost:37241/kbs/tech_tools/ingest/obsidian" \
  -H "Content-Type: application/json" \
  -d '{"recursive": true}'

# 查询任务状态
curl http://localhost:37241/tasks/{task_id}

# RAG 问答（基础）
curl -X POST "http://localhost:37241/kbs/tech_tools/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程", "top_k": 5}'

# RAG 问答（启用 HyDE）
curl -X POST "http://localhost:37241/kbs/tech_tools/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程", "use_hyde": true}'

# RAG 问答（指定答案生成模式）
curl -X POST "http://localhost:37241/kbs/tech_tools/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程", "response_mode": "tree_summarize"}'
```

### CLI 方式

```bash
# 交互式查询
uv run llamaindex-study

# 查看统一 CLI 帮助
uv run llamaindex-study --help

# 列出知识库
uv run llamaindex-study kb list

# 查看知识库详情
uv run llamaindex-study kb show tech_tools

# 向量检索 / RAG 问答
uv run llamaindex-study search tech_tools "Python 异步编程" -k 5
uv run llamaindex-study search tech_tools "Python 异步编程" -k 5 --auto-merging
uv run llamaindex-study query tech_tools "总结当前知识库重点"

# 启用 HyDE 查询转换
uv run llamaindex-study query tech_tools "Python 最佳实践" --hyde

# 启用多查询转换
uv run llamaindex-study query tech_tools "如何优化性能" --multi-query

# 指定答案生成模式
uv run llamaindex-study query tech_tools "性能优化" --response-mode tree_summarize

# 提交导入任务
uv run llamaindex-study ingest obsidian tech_tools --folder-path IT
uv run llamaindex-study ingest file tech_tools README.md
uv run llamaindex-study ingest zotero zotero_nutrition --collection-name "营养"

# 任务管理
uv run llamaindex-study task list              # 查看任务（自动清理孤儿任务）
uv run llamaindex-study task show <task_id>  # 查看任务详情
uv run llamaindex-study task watch <task_id>  # 持续观察任务
uv run llamaindex-study task cancel <task_id>  # 取消任务
uv run llamaindex-study task pause <task_id>   # 暂停任务
uv run llamaindex-study task resume <task_id>  # 恢复任务
uv run llamaindex-study task pause-all         # 暂停所有任务
uv run llamaindex-study task resume-all       # 恢复所有任务
uv run llamaindex-study task delete <task_id> [--cleanup]  # 删除任务记录
uv run llamaindex-study task delete-all [--status completed]  # 删除所有任务
uv run llamaindex-study task cleanup          # 清理孤儿任务

# 配置管理
uv run llamaindex-study config list
uv run llamaindex-study config get USE_HYDE
uv run llamaindex-study config set USE_HYBRID_SEARCH true

# Obsidian / Zotero 辅助
uv run llamaindex-study obsidian mappings
uv run llamaindex-study zotero collections --limit 10

# 分类规则与管理命令
uv run llamaindex-study category rules list
uv run llamaindex-study admin tables
```

### Python 代码方式

```python
from kb.services import SearchService, KnowledgeBaseService, QueryRouter

# 列出知识库
kbs = KnowledgeBaseService.list_all()

# 基础 RAG 查询
result = SearchService.query("tech_tools", "Python 异步编程", top_k=5)

# 启用 HyDE 查询
result = SearchService.query(
    "tech_tools",
    "Python 异步编程",
    use_hyde=True,
    top_k=5
)

# 指定答案生成模式
result = SearchService.query(
    "tech_tools",
    "Python 异步编程",
    response_mode="tree_summarize",
    top_k=5
)

# 自动路由查询
result = QueryRouter.query("猪饲料配方", top_k=5)
```

## API 端点

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api-docs` | Markdown API 文档 |

### 知识库管理

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/kbs` | 列出所有知识库 |
| POST | `/kbs` | 创建知识库 |
| GET | `/kbs/{kb_id}` | 获取知识库详情 |
| DELETE | `/kbs/{kb_id}` | 删除知识库 |

### 检索查询

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/kbs/{kb_id}/search` | 向量检索 |
| POST | `/kbs/{kb_id}/query` | RAG 问答 |
| POST | `/search` | 自动路由检索 |
| POST | `/query` | 自动路由 RAG 问答 |

### 文档导入

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/kbs/{kb_id}/ingest` | 通用文件导入（本地文件/文件夹） |
| POST | `/kbs/{kb_id}/ingest/obsidian` | Obsidian 导入 |
| POST | `/kbs/{kb_id}/ingest/zotero` | Zotero 导入 |
| POST | `/kbs/{kb_id}/rebuild` | 重建知识库 |

### 任务队列

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/tasks` | 提交任务 |
| GET | `/tasks` | 列出任务 |
| GET | `/tasks/{task_id}` | 查询任务状态 |
| DELETE | `/tasks/{task_id}` | 取消任务 |
| DELETE | `/tasks/{task_id}/delete` | 删除任务 |

详细 API 文档请参考 [docs/API.md](docs/API.md)

## 环境变量配置

所有配置都通过环境变量控制，支持以下变量：

### LLM 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SILICONFLOW_API_KEY` | - | 硅基流动 API 密钥 |
| `SILICONFLOW_BASE_URL` | `https://api.siliconflow.cn/v1` | API 地址 |
| `SILICONFLOW_MODEL` | `Pro/deepseek-ai/DeepSeek-V3.2` | LLM 模型 |

### Embedding 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_EMBED_MODEL` | `bge-m3` | Embedding 模型名称 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | 默认 Ollama 地址 |
| `OLLAMA_LOCAL_URL` | `http://localhost:11434` | 本地 Ollama 地址 |
| `OLLAMA_REMOTE_URL` | 空 | 远程 Ollama 地址（留空禁用） |
| `MAX_RETRIES` | `3` | 每个端点最大重试次数 |
| `RETRY_DELAY` | `1.0` | 重试延迟（秒） |

### 存储配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OBSIDIAN_VAULT_ROOT` | `~/Documents/Obsidian Vault` | Obsidian Vault 根目录 |
| `PERSIST_DIR` | `/Volumes/online/llamaindex` | 向量存储目录（通用 KB） |
| `ZOTERO_PERSIST_DIR` | `/Volumes/online/llamaindex/zotero` | Zotero 向量存储目录 |
| `DATA_DIR` | `~/.llamaindex` | 任务队列与项目数据库目录 |

### 检索配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TOP_K` | `5` | 每个知识库返回的结果数量 |
| `CHUNK_STRATEGY` | `hierarchical` | 分块策略：`hierarchical`/`sentence`/`semantic` |
| `HIERARCHICAL_CHUNK_SIZES` | `2048,512,128` | 层级分块各层大小 |
| `SENTENCE_CHUNK_SIZE` | `512` | 句子分块大小 |
| `SENTENCE_CHUNK_OVERLAP` | `50` | 句子分块重叠 |
| `USE_HYBRID_SEARCH` | `false` | 启用混合搜索（向量 + BM25） |
| `HYBRID_SEARCH_ALPHA` | `0.5` | 混合搜索向量权重（0-1） |
| `HYBRID_SEARCH_MODE` | `relative_score` | 混合搜索融合模式 |
| `USE_HYDE` | `false` | 启用 HyDE 查询转换 |
| `USE_MULTI_QUERY` | `false` | 启用多查询转换 |
| `USE_QUERY_REWRITE` | `false` | 启用 Query Rewriting |
| `USE_AUTO_MERGING` | `false` | 启用 Auto-Merging Retriever（需 KB 使用 hierarchical 分块） |
| `USE_SEMANTIC_CHUNKING` | `false` | 启用语义分块（需重建知识库） |
| `RESPONSE_MODE` | `compact` | 答案生成模式 |

### Reranker 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `USE_RERANKER` | `true` | 是否启用重排序 |
| `RERANK_MODEL` | `Pro/BAAI/bge-reranker-v2-m3` | 重排序模型 |

### 任务处理配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CHUNK_SIZE` | `512` | 文本分块大小 |
| `CHUNK_OVERLAP` | `50` | 文本分块重叠 |
| `EMBED_BATCH_SIZE` | `32` | Embedding 批处理大小 |
| `PROGRESS_UPDATE_INTERVAL` | `10` | 进度更新间隔 |
| `MAX_CONCURRENT_TASKS` | `10` | 最大并发任务数 |

## 存储位置

```
/Volumes/online/llamaindex/       # 主存储目录
├── obsidian/                    # Obsidian 来源 KB（通用 KB）
│   └── <kb_id>/
└── zotero/                      # Zotero 来源 KB
    └── <kb_id>/
        └── <kb_id>.lance/       # LanceDB 向量数据

~/.llamaindex/                    # 项目数据库目录
├── project.db                   # SQLite 数据库
│   ├── sync_states              # 同步状态
│   ├── dedup_records            # 去重记录
│   ├── progress                 # 处理进度
│   ├── knowledge_bases          # 知识库元数据（唯一数据源）
│   └── kb_category_rules         # 分类规则
└── tasks.db                     # 任务队列
```

**存储策略：**
- 通用 KB（Obsidian 等）→ `PERSIST_DIR/{kb_id}/`
- Zotero KB → `ZOTERO_PERSIST_DIR/{kb_id}/`
- 知识库元数据全部存储在数据库中，`KNOWLEDGE_BASES` 仅作种子数据

## 硅基流动模型推荐

| 模型 | 特点 | 适用场景 |
|------|------|----------|
| `Pro/deepseek-ai/DeepSeek-V3.2` | 通用强模型，低成本 | 日常问答、文档总结 |
| `deepseek-ai/DeepSeek-R1` | 推理能力强，思维链 | 复杂推理，分析任务 |
| `Qwen/Qwen2.5-7B-Instruct` | 开源稳定 | 通用对话 |

## 代码质量

- ✅ 完整的类型注解
- ✅ 统一的日志管理（使用 logging 模块）
- ✅ 参数化查询（防 SQL 注入）
- ✅ 配置常量集中管理
- ✅ 模块化设计
