# 文档目录

## 项目文档

| 文档 | 说明 |
|------|------|
| [README.md](../README.md) | 项目主文档，包含安装、配置、快速开始 |
| [docs/API.md](API.md) | API 接口详细文档，包含所有端点说明 |
| [docs/ARCHITECTURE.md](ARCHITECTURE.md) | 项目架构文档，包含模块说明、设计模式、数据流 |

## 快速导航

### 新手入门
1. [README.md - 快速开始](../README.md#快速开始)
2. [README.md - 使用方式](../README.md#使用方式)
3. [API.md - 完整示例](../docs/API.md#完整示例)

### 开发者指南
1. [ARCHITECTURE.md - 架构分层](../docs/ARCHITECTURE.md#架构分层)
2. [ARCHITECTURE.md - 扩展指南](../docs/ARCHITECTURE.md#扩展指南)
3. [API.md - WebSocket](../docs/API.md#websocket-实时推送)

### 配置参考
1. [README.md - 环境变量配置](../README.md#环境变量配置)
2. [.env.example](../.env.example) - 所有配置项说明

## API 端点速查

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

### 文档导入
| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/kbs/{kb_id}/ingest` | 通用文件导入 |
| POST | `/kbs/{kb_id}/ingest/obsidian` | Obsidian 导入（并行） |
| POST | `/kbs/{kb_id}/ingest/zotero` | Zotero 导入 |
| POST | `/kbs/{kb_id}/rebuild` | 重建知识库 |

### 任务队列
| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/tasks` | 提交任务 |
| GET | `/tasks` | 列出任务 |
| GET | `/tasks/{task_id}` | 查询任务状态 |
| DELETE | `/tasks/{task_id}` | 取消任务 |

### 分类规则
| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/category/rules` | 列出分类规则 |
| POST | `/category/rules/sync` | 同步分类规则 |
| POST | `/category/classify` | 分类文件夹 |
| POST | `/category/rules/add` | 添加分类规则 |

## 代码索引

### 核心模块 (`src/llamaindex_study/`)

| 模块 | 文件 | 说明 |
|------|------|------|
| 配置 | `config.py` | 环境变量配置 |
| 日志 | `logger.py` | 日志工具 |
| Ollama 工具 | `ollama_utils.py` | Embedding 工具 |
| Embedding 服务 | `embedding_service.py` | Ollama Embedding |
| 负载均衡 | `embedding_loadbalancer.py` | 多端点负载均衡 |
| 向量存储 | `vector_store.py` | LanceDB/Chroma/Qdrant |
| 查询引擎 | `query_engine.py` | RAG 查询 |
| 重排序 | `reranker.py` | SiliconFlow Reranker |

### 知识库模块 (`kb/`)

| 模块 | 文件 | 说明 |
|------|------|------|
| 服务层 | `services.py` | **统一入口** |
| 知识库注册 | `registry.py` | 知识库定义、路径配置 |
| 数据库 | `database.py` | SQLite 数据库管理 |
| 任务队列 | `task_queue.py` | SQLite 持久化 |
| 任务执行器 | `task_executor.py` | 异步执行 |
| 任务锁 | `task_lock.py` | 去重锁（Semaphore） |
| 并行 Embedding | `parallel_embedding.py` | 竞争模式并行处理 |
| 写入队列 | `ingest_vdb.py` | LanceDB 写入队列 |
| 去重管理 | `deduplication.py` | 增量同步 |
| 文档处理 | `document_processor.py` | 统一文档解析 |
| Obsidian | `obsidian_processor.py` | Obsidian 导入 |
| Obsidian 读取 | `obsidian_reader.py` | Obsidian 笔记读取 |
| Obsidian 配置 | `obsidian_config.py` | Obsidian 配置 |
| 分类器 | `category_classifier.py` | LLM 分类 |
| 同步状态 | `sync_state.py` | 同步状态管理 |
| Zotero | `zotero_processor.py` | Zotero 导入 |
| Zotero 读取 | `zotero_reader.py` | Zotero 读取 |
| 通用导入 | `generic_processor.py` | 通用文件导入 |
| WebSocket | `websocket_manager.py` | WebSocket 管理 |

## CLI 脚本

| 脚本 | 命令 | 说明 |
|------|------|------|
| API 服务 | `poetry run python api.py` | FastAPI 服务 |
| 主程序 | `poetry run python main.py` | 交互式查询 CLI |
| 向量导入 | `poetry run python -m kb.ingest_vdb` | CLI 向量数据库导入 |
| 知识库导入 | `poetry run python -m kb.ingest` | 知识库导入脚本 |
| Zotero 导入 | `poetry run python -m kb.ingest_zotero` | CLI Zotero 导入 |
| 高新历史 | `poetry run python -m kb.ingest_hitech_history` | CLI 历史项目导入 |

## 使用示例

### Python SDK 方式

```python
from kb.services import (
    KnowledgeBaseService,
    ObsidianService,
    ZoteroService,
    SearchService,
)

# 列出知识库
kbs = KnowledgeBaseService.list_all()

# 导入 Obsidian
ObsidianService.import_vault(
    kb_id="my_kb",
    vault_path="/path/to/vault",
    folder_path="技术理论",
)

# 搜索
results = SearchService.search("my_kb", "猪营养配方设计")
```

### API 方式

```bash
# 导入 Obsidian（并行处理）
curl -X POST "http://localhost:8000/kbs/my_kb/ingest/obsidian" \
  -H "Content-Type: application/json" \
  -d '{"vault_path": "/path/to/vault", "recursive": true}'

# 查询任务状态
curl http://localhost:8000/tasks/{task_id}

# 搜索
curl -X POST "http://localhost:8000/kbs/my_kb/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "猪营养", "top_k": 5}'

# RAG 问答
curl -X POST "http://localhost:8000/kbs/my_kb/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "如何设计猪饲料配方？", "top_k": 5}'
```

## 环境变量速查

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_EMBED_MODEL` | `bge-m3` | Embedding 模型 |
| `OLLAMA_LOCAL_URL` | `http://localhost:11434` | 本地 Ollama |
| `OLLAMA_REMOTE_URL` | `http://localhost:11434` | 远程 Ollama |
| `OBSIDIAN_VAULT_ROOT` | `~/Documents/Obsidian Vault` | Vault 目录 |
| `OBSIDIAN_STORAGE_DIR` | `~/.llamaindex/storage` | 存储目录 |
| `CHUNK_SIZE` | `512` | 分块大小 |
| `MAX_RETRIES` | `3` | 最大重试次数 |
| `MAX_CONCURRENT_TASKS` | `10` | 最大并发 |

## 常见问题

### Q: 如何添加新的数据源？
参见 [ARCHITECTURE.md - 扩展指南](../docs/ARCHITECTURE.md#扩展指南)

### Q: 如何配置多个 Ollama 端点？
设置 `OLLAMA_LOCAL_URL` 和 `OLLAMA_REMOTE_URL` 环境变量

### Q: 如何禁用增量同步？
在导入参数中设置 `rebuild=True` 或使用 `--rebuild` 参数

### Q: API 服务如何启动？
```bash
poetry run python api.py
```
- 服务地址：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`
- WebSocket：`ws://localhost:8000/ws/tasks`

### Q: 如何查看详细日志？
配置 Python logging 级别：
```bash
export LOG_LEVEL=DEBUG
poetry run python api.py
```
