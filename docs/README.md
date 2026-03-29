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
3. [API.md - 完整示例](../docs/API.md#完整使用示例)

### 开发者指南
1. [ARCHITECTURE.md - 架构分层](../docs/ARCHITECTURE.md#架构分层)
2. [ARCHITECTURE.md - 扩展指南](../docs/ARCHITECTURE.md#扩展指南)
3. [API.md - WebSocket](../docs/API.md#websocket-实时推送)

### API 参考

#### 知识库管理
- `GET /kbs` - 列出所有知识库
- `POST /kbs` - 创建知识库
- `GET /kbs/{kb_id}` - 获取知识库详情
- `DELETE /kbs/{kb_id}` - 删除知识库

#### 检索查询
- `POST /kbs/{kb_id}/search` - 向量检索
- `POST /kbs/{kb_id}/query` - RAG 问答

#### 文档导入
- `POST /kbs/{kb_id}/ingest` - 通用文件导入
- `POST /kbs/{kb_id}/ingest/obsidian` - Obsidian 导入
- `POST /kbs/{kb_id}/ingest/zotero` - Zotero 导入
- `POST /kbs/{kb_id}/rebuild` - 重建知识库

#### 任务队列
- `POST /tasks` - 提交任务
- `GET /tasks` - 列出任务
- `GET /tasks/{task_id}` - 查询任务状态
- `DELETE /tasks/{task_id}` - 取消任务

## 代码索引

### 核心模块

| 模块 | 文件 | 说明 |
|------|------|------|
| 配置 | `src/llamaindex_study/config.py` | 环境变量配置 |
| 日志 | `src/llamaindex_study/logger.py` | 日志工具 |
| Ollama 工具 | `src/llamaindex_study/ollama_utils.py` | Embedding 工具 |
| Embedding 服务 | `src/llamaindex_study/embedding_service.py` | 多端点负载均衡 |
| 向量存储 | `src/llamaindex_study/vector_store.py` | LanceDB/Chroma/Qdrant |
| 查询引擎 | `src/llamaindex_study/query_engine.py` | RAG 查询 |
| 重排序 | `src/llamaindex_study/reranker.py` | SiliconFlow Reranker |

### 知识库模块

| 模块 | 文件 | 说明 |
|------|------|------|
| 服务层 | `kb/services.py` | **统一入口** |
| 知识库注册 | `kb/registry.py` | 知识库定义 |
| 任务队列 | `kb/task_queue.py` | SQLite 持久化 |
| 任务执行器 | `kb/task_executor.py` | 异步执行 |
| 去重管理 | `kb/deduplication.py` | 增量同步 |
| 文档处理 | `kb/document_processor.py` | 统一文档解析 |
| Obsidian | `kb/obsidian_processor.py` | Obsidian 导入 |
| Zotero | `kb/zotero_processor.py` | Zotero 导入 |
| 通用导入 | `kb/generic_processor.py` | 通用文件导入 |
| 并行执行 | `kb/parallel_executor.py` | 本地/远程并行 |

### CLI 脚本

| 脚本 | 命令 | 说明 |
|------|------|------|
| 向量导入 | `poetry run python -m kb.ingest_vdb` | CLI 向量数据库导入 |
| Zotero 导入 | `poetry run python -m kb.ingest_zotero` | CLI Zotero 导入 |
| 高新历史导入 | `poetry run python -m kb.ingest_hitech_history` | CLI 历史项目导入 |
| API 服务 | `poetry run python api.py` | FastAPI 服务 |

## 示例代码

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
# 导入 Obsidian
curl -X POST "http://localhost:8000/kbs/my_kb/ingest/obsidian" \
  -H "Content-Type: application/json" \
  -d '{"vault_path": "/path/to/vault"}'

# 搜索
curl -X POST "http://localhost:8000/kbs/my_kb/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "猪营养"}'
```

## 常见问题

### Q: 如何添加新的数据源？
参见 [ARCHITECTURE.md - 扩展指南](../docs/ARCHITECTURE.md#扩展指南)

### Q: 如何配置多个 Ollama 端点？
参见 [ARCHITECTURE.md - Ollama 负载均衡](../docs/ARCHITECTURE.md#ollama-负载均衡)

### Q: 如何禁用增量同步？
在导入参数中设置 `incremental=False` 或使用 `--rebuild` 参数

### Q: API 服务如何启用？
```bash
poetry run python api.py
```
服务地址：`http://localhost:8000`
API 文档：`http://localhost:8000/docs`
