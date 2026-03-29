# LlamaIndex 学习项目

一个基于 LlamaIndex v0.10+ 的现代化 RAG（检索增强生成）学习项目，支持**本地/远程 Ollama 并行处理**。

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

## 主要特性

| 特性 | 说明 |
|------|------|
| **并行 Embedding** | 本地 + 远程 Ollama 同时工作，chunk 级竞争模式 |
| **失败重试机制** | 每个端点最多重试 3 次，提高稳定性 |
| **去重串行访问** | Semaphore(1) 保护 dedup.db，避免数据库锁定 |
| **LanceDB 串行写入** | WriteQueue 保证写入顺序，避免锁定 |
| **任务队列** | 异步提交，随时查询状态 |
| **增量同步** | 基于文件哈希检测变更 |
| **完整类型注解** | 提升代码可维护性 |
| **统一日志管理** | 使用 Python logging 模块 |

## 环境要求

- Python >= 3.11
- Poetry（Python 包管理器）
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
poetry install

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
OBSIDIAN_STORAGE_DIR=~/.llamaindex/storage
ZOTERO_STORAGE_DIR=~/.llamaindex/storage/zotero
```

### 5. 运行

```bash
# 启动 API 服务
poetry run python api.py

# 启动交互式查询
poetry run llamaindex-study
```

## 项目结构

```
llamaindex-study/
├── api.py                    # FastAPI 服务入口
├── main.py                   # 交互式查询 CLI
│
├── src/llamaindex_study/    # 核心库
│   ├── __init__.py
│   ├── config.py             # 配置管理
│   ├── logger.py             # 日志工具
│   ├── embedding_service.py   # Ollama Embedding 服务
│   ├── embedding_loadbalancer.py  # 负载均衡
│   ├── ollama_utils.py      # Ollama 工具
│   ├── vector_store.py       # 向量数据库管理（多后端）
│   ├── query_engine.py       # 查询引擎
│   └── reranker.py           # 重排序
│
├── kb/                      # 知识库模块
│   ├── __init__.py
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
│   ├── deduplication.py      # 去重管理
│   ├── category_classifier.py # 分类器
│   ├── sync_state.py         # 同步状态
│   ├── document_processor.py  # 文档处理器
│   ├── generic_processor.py   # 通用文件处理器
│   ├── zotero_processor.py    # Zotero 导入器
│   ├── zotero_reader.py      # Zotero 读取器
│   ├── websocket_manager.py   # WebSocket 管理
│   └── services.py           # 统一服务层
│
└── docs/
    ├── API.md               # API 详细文档
    └── ARCHITECTURE.md      # 架构文档
```

## 核心功能

### 1. 真正的并行 Embedding（竞争模式）

```
Chunk 1 ──→ 本地 Ollama  ─┐
Chunk 2 ──→ 远程 Ollama  ──┼──→ 谁先完成用谁的结果
Chunk 3 ──→ 本地 Ollama  ──┤
Chunk 4 ──→ 远程 Ollama  ─┘
```

使用 `asyncio + ThreadPoolExecutor` 实现，所有任务类型共用同一套多端点调度，首个成功结果立即返回。

### 2. 资源保护机制

```
去重数据库 (dedup.db)
    └── Semaphore(1) ── 串行访问，避免锁定

LanceDB
    └── WriteQueue ── 串行写入，避免锁定
```

### 3. 任务队列

```bash
# 提交任务
curl -X POST "http://localhost:8000/kbs/tech_tools/ingest/obsidian"

# 返回任务 ID
{"task_id": "abc12345", "status": "pending"}

# 查询状态
curl "http://localhost:8000/tasks/abc12345"

# 返回
{"task_id": "abc12345", "status": "completed", 
 "progress": 100, "result": {
   "files": 26, "nodes": 248,
   "endpoint_stats": {"本地": 124, "远程": 124}
 }}
```

### 4. 增量同步

```bash
# 查看变更
poetry run python -m kb.ingest_vdb --show-changes

# 增量同步（默认提交全部知识库）
poetry run python -m kb.ingest_vdb
```

## 使用方式

### API 方式

```bash
# 启动服务
poetry run python api.py

# 提交 Obsidian 导入任务
curl -X POST "http://localhost:8000/kbs/tech_tools/ingest/obsidian" \
  -H "Content-Type: application/json" \
  -d '{"recursive": true}'

# 查询任务状态
curl http://localhost:8000/tasks/{task_id}

# 搜索
curl -X POST "http://localhost:8000/kbs/tech_tools/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程", "top_k": 5}'
```

### CLI 方式

```bash
# 交互式查询
poetry run llamaindex-study

# 查看统一 CLI 帮助
poetry run llamaindex-study --help

# 列出知识库
poetry run llamaindex-study kb list

# 查看知识库详情
poetry run llamaindex-study kb show tech_tools

# 向量检索 / RAG 问答
poetry run llamaindex-study search tech_tools "Python 异步编程" -k 5
poetry run llamaindex-study query tech_tools "总结当前知识库重点"

# 提交导入任务
poetry run llamaindex-study ingest obsidian tech_tools --folder-path IT
poetry run llamaindex-study ingest file tech_tools README.md
poetry run llamaindex-study ingest zotero zotero_nutrition --collection-name "营养"

# 任务管理
poetry run llamaindex-study task list
poetry run llamaindex-study task show <task_id>
poetry run llamaindex-study task watch <task_id>

# Obsidian / Zotero 辅助
poetry run llamaindex-study obsidian mappings
poetry run llamaindex-study zotero collections --limit 10

# 分类规则与管理命令
poetry run llamaindex-study category rules list
poetry run llamaindex-study admin tables
```

### Python 代码方式

```python
from kb.task_queue import TaskQueue, TaskType

# 提交任务
tq = TaskQueue()
task_id = tq.submit_task(
    task_type=TaskType.OBSIDIAN.value,
    kb_id="tech_tools",
    params={"rebuild": False},
    source="cli"
)

# 查询任务
task = tq.get_task(task_id)
print(f"状态: {task.status}")
print(f"结果: {task.result}")
```

## API 端点

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/kbs/{kb_id}/ingest/obsidian` | Obsidian 导入（并行） |
| POST | `/kbs/{kb_id}/ingest/zotero` | Zotero 导入 |
| GET | `/tasks` | 列出任务 |
| GET | `/tasks/{task_id}` | 查询任务状态 |
| POST | `/kbs/{kb_id}/search` | 向量检索 |
| POST | `/kbs/{kb_id}/query` | RAG 问答 |

详细 API 文档请参考 [docs/API.md](docs/API.md)

## 环境变量配置

所有配置都通过环境变量控制，支持以下变量：

### 存储路径配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OBSIDIAN_VAULT_ROOT` | `~/Documents/Obsidian Vault` | Obsidian Vault 根目录 |
| `PERSIST_DIR` | `./.llamaindex/storage` | 默认向量存储目录 |
| `ZOTERO_PERSIST_DIR` | `./.llamaindex/storage/zotero` | Zotero 向量存储目录 |
| `DATA_DIR` | `./.llamaindex` | 任务队列与项目数据库目录 |

### Embedding 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_EMBED_MODEL` | `bge-m3` | Embedding 模型名称 |
| `EMBEDDING_DIM` | `1024` | Embedding 向量维度 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | 默认 Ollama 地址 |
| `OLLAMA_LOCAL_URL` | `http://localhost:11434` | 本地 Ollama 地址 |
| `OLLAMA_REMOTE_URL` | 空 | 远程 Ollama 地址，留空表示禁用第二端点 |
| `DATA_DIR` | `./.llamaindex` | 任务队列与项目数据库目录 |

### 任务处理配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CHUNK_SIZE` | `512` | 文本分块大小 |
| `CHUNK_OVERLAP` | `50` | 文本分块重叠 |
| `PROGRESS_UPDATE_INTERVAL` | `10` | 进度更新间隔 |
| `MAX_CONCURRENT_TASKS` | `10` | 最大并发任务数 |

### 并行 Embedding 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MAX_RETRIES` | `3` | 每个端点最大重试次数 |
| `RETRY_DELAY` | `1.0` | 重试延迟（秒） |
| `OLLAMA_SHORT_TEXT_THRESHOLD` | `600` | 短文本优先单端点阈值 |
| `OLLAMA_FANOUT_TEXT_THRESHOLD` | `1800` | 长文本触发双端点竞速阈值 |

## 存储位置

```
~/.llamaindex/                    # 本地存储根目录
├── storage/                      # 向量数据（可配置）
│   ├── kb_swine_nutrition/      # 知识库存储
│   └── kb_tech_tools/
├── project.db                   # SQLite 数据库
│   ├── sync_states              # 同步状态
│   ├── dedup_records            # 去重记录
│   ├── progress                 # 处理进度
│   ├── knowledge_bases          # 知识库元数据
│   └── kb_category_rules         # 分类规则
└── tasks.db                     # 任务队列
```

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
