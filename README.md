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
| **并行 Embedding** | 本地 + 远程 Ollama 同时工作，chunk 级轮流分配 |
| **去重串行访问** | Semaphore(1) 保护 dedup.db，避免数据库锁定 |
| **LanceDB 串行写入** | WriteQueue 保证写入顺序，避免锁定 |
| **任务队列** | 异步提交，随时查询状态 |
| **增量同步** | 基于文件哈希检测变更 |

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
SILICONFLOW_API_KEY=你的密钥
SILICONFLOW_MODEL=deepseek-ai/DeepSeek-V3
OLLAMA_EMBED_MODEL=bge-m3
PERSIST_DIR=./storage
```

### 5. 运行

```bash
# 启动 API 服务
poetry run python api.py

# 或使用 CLI
poetry run python main.py
```

## 项目结构

```
llamaindex-study/
├── api.py                    # FastAPI 服务入口
├── main.py                   # 交互式查询 CLI
│
├── src/llamaindex_study/    # 核心库
│   ├── config.py             # 配置管理
│   ├── embedding_service.py   # Ollama Embedding 服务
│   ├── embedding_loadbalancer.py  # 负载均衡
│   ├── vector_store.py       # 向量数据库管理
│   ├── query_engine.py        # 查询引擎
│   └── logger.py             # 日志工具
│
├── kb/                      # 知识库模块
│   ├── registry.py           # 知识库注册表
│   ├── database.py           # SQLite 数据库
│   ├── task_queue.py         # 任务队列
│   ├── task_executor.py      # 任务执行器
│   ├── task_lock.py          # 去重数据库锁（Semaphore）
│   ├── parallel_embedding.py  # 并行 Embedding 处理器
│   ├── ingest_vdb.py         # LanceDB 写入队列
│   ├── obsidian_processor.py # Obsidian 笔记导入
│   ├── deduplication.py      # 去重管理
│   └── services.py           # 统一服务层
│
└── docs/
    ├── API.md               # API 详细文档
    └── ARCHITECTURE.md      # 架构文档
```

## 核心功能

### 1. 真正的并行 Embedding

```
Chunk 1 ──→ 本地 Ollama  ─┐
Chunk 2 ──→ 远程 Ollama  ──┼──→ 并行执行
Chunk 3 ──→ 本地 Ollama  ──┤
Chunk 4 ──→ 远程 Ollama  ─┘
```

使用 `asyncio + ThreadPoolExecutor` 实现，两个端点同时工作。

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

# 增量同步（只处理新增/更新）
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
# 列出知识库
poetry run python -m kb.ingest_vdb --list

# 提交导入任务
poetry run python -m kb.ingest_vdb --kb tech_tools

# 查看任务状态
poetry run python -m kb.ingest_vdb --tasks

# 强制重建
poetry run python -m kb.ingest_vdb --kb tech_tools --rebuild
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

## 存储位置

```
/Volumes/online/llamaindex/           # 向量数据
~/.llamaindex/                       # SQLite 数据库
├── project.db                      # 项目数据、去重状态
└── tasks.db                        # 任务队列
```

## 硅基流动模型推荐

| 模型 | 特点 | 适用场景 |
|------|------|----------|
| `Pro/deepseek-ai/DeepSeek-V3.2` | 通用强模型，低成本 | 日常问答、文档总结 |
| `deepseek-ai/DeepSeek-R1` | 推理能力强，思维链 | 复杂推理，分析任务 |
| `Qwen/Qwen2.5-7B-Instruct` | 开源稳定 | 通用对话 |
