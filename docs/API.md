# LlamaIndex RAG API 文档

> ⚠️ 基于 LlamaIndex v0.14+ 构建，2026-03-30 完成升级（原 v0.10 → v0.14）

## 相关文档

- [Query 参数设计指南](./QUERY_PARAM_GUIDE.md) - **客户端 UI 设计必读**，详细说明 route_mode、retrieval_mode、各检索增强参数的适用场景
- [CLI 使用文档](./CLI.md) - 命令行接口详细说明
- [架构设计](./ARCHITECTURE.md) - 系统架构与设计模式

## 概述

基于 FastAPI 的 RAG（检索增强生成）API 服务，支持：

- **并行多端点 Ollama** - 多端点自适应负载均衡（inflight 最少优先），Ollama 全部失败时自动切换 SiliconFlow
- **失败重试机制** - 每个端点最多重试 3 次
- **任务队列** - 异步提交，随时查询状态
- **增量同步** - 基于文件哈希检测变更
- **资源保护** - documents 表串行访问、LanceDB 串行写入
- **混合搜索** - 向量检索 + BM25 关键词融合（需启用）
- **Auto-Merging** - 检索时自动合并相关子节点（需启用）

## 启动服务

```bash
cd llamaindex-study
uv run python -m api.main
```

或者使用 CLI 一键启动：

```bash
uv run llamaindex-study service start
```

 - 服务地址: `http://localhost:37241`
 - API 文档: `http://localhost:37241/docs`
 - Markdown API 文档: `http://localhost:37241/api-docs`
 - WebSocket: `ws://localhost:37241/ws/tasks`

---

## 核心功能

### 并行多端点 Ollama（自适应负载均衡）

导入任务使用**多 Ollama 端点自适应分配**：

- **队列机制**：所有 chunk 进入共享队列
- **负载均衡**：选择 inflight 最少的端点，避免过载
- **自动恢复**：Ollama 端点失败时会重试健康检查，恢复后自动重新启用

```
Chunk 队列：
[Chunk 1] [Chunk 2] [Chunk 3] [Chunk 4] [Chunk 5] ...

端点分配（inflight 最少优先）：
Ollama-PC     ──→ Chunk 1, Chunk 3, Chunk 5 ...
Ollama-Server ──→ Chunk 2, Chunk 4 ...
```

端点配置基于数据库中的 `vendor` 和 `model` 表，通过健康检查动态选择。所有 Ollama 端点均通过健康检查调度，全部失败时自动 fallback 到 SiliconFlow。

> **注意**: Ollama 供应商和端点通过 CLI/API 管理，参见 `vendor add` / `model add` 命令。

### 任务队列

任务提交后立即返回 `task_id`，后台异步执行：

```bash
# 提交任务
curl -X POST "http://localhost:37241/kbs/tech_tools/ingest/obsidian"

# 返回
{"task_id": "abc12345", "status": "pending"}

# 查询状态
curl "http://localhost:37241/tasks/abc12345"

# 返回
{
  "task_id": "abc12345",
  "status": "completed",
  "progress": 100,
  "result": {
    "kb_id": "tech_tools",
    "files": 26,
    "nodes": 248,
    "endpoint_stats": {
      "Ollama-PC": 124,
      "Ollama-Server": 124
    }
  }
}
```

---

## API 端点总览

### 健康检查

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/health` | 服务健康检查 |
| GET | `/api-docs` | Markdown 格式 API 文档页面 |

### 任务队列

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/tasks` | 提交任务 |
| GET | `/tasks` | 列出任务 |
| GET | `/tasks/{task_id}` | 查询任务状态 |
| POST | `/tasks/{task_id}/cancel` | 取消任务 |
| POST | `/tasks/{task_id}/pause` | 暂停任务 |
| POST | `/tasks/{task_id}/resume` | 恢复任务 |
| DELETE | `/tasks/{task_id}` | 删除任务（可选 cleanup=true 清理关联数据） |
| POST | `/tasks/pause-all` | 暂停所有运行中的任务 |
| POST | `/tasks/resume-all` | 恢复所有已暂停的任务 |
| DELETE | `/tasks/delete-all` | 删除所有任务 |
| POST | `/tasks/cleanup` | 清理孤儿任务 |

### 知识库管理

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/kbs` | 列出所有知识库 |
| POST | `/kbs` | 创建知识库 |
| GET | `/kbs/{kb_id}` | 获取知识库详情 |
| DELETE | `/kbs/{kb_id}` | 删除知识库 |

#### POST /kbs - 创建知识库

```bash
curl -X POST http://localhost:37241/kbs \
  -H "Content-Type: application/json" \
  -d '{
    "id": "my_kb",
    "name": "我的知识库",
    "description": "个人文档",
    "source_type": "generic"
  }'
```

参数说明：
- `id`: 知识库唯一标识（必填）
- `name`: 显示名称（必填）
- `description`: 描述（可选）
- `source_type`: 来源类型（可选，默认 `generic`）
  - `generic`: 通用知识库，存储到 `PERSIST_DIR`
  - `zotero`: Zotero 文献库，存储到 `ZOTERO_PERSIST_DIR`
  - `obsidian`: Obsidian 笔记库
  - `manual`: 手动创建

响应示例：

```json
{
  "id": "my_kb",
  "name": "我的知识库",
  "description": "个人文档",
  "source_type": "generic",
  "status": "created"
}
```

**错误响应**（知识库已存在）：
```json
{"detail": "知识库 my_kb 已存在"}
```

### 文档导入

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/kbs/{kb_id}/ingest` | 通用文件导入 |
| POST | `/kbs/{kb_id}/ingest/obsidian` | Obsidian 导入 |
| POST | `/kbs/{kb_id}/ingest/zotero` | Zotero 导入 |
| POST | `/kbs/{kb_id}/initialize` | 初始化知识库（清空数据） |
| GET | `/kbs/{kb_id}/topics` | 查看知识库 topics |
| POST | `/kbs/{kb_id}/topics/refresh` | 手动刷新知识库 topics |

### 知识库一致性校验

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/kbs/{kb_id}/consistency` | 校验知识库一致性 |
| POST | `/kbs/{kb_id}/consistency/repair` | 修复知识库一致性 |
| POST | `/consistency/repair-all` | 修复所有知识库的一致性 |

> 导入相关端点统一走 `kb/import_service.py` 的 `ImportApplicationService`。  
> 同一类导入在 API、CLI、脚本三种入口保持同一业务语义与参数解释。

### 文档管理

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/kbs/{kb_id}/documents` | 列出知识库的所有文档 |
| GET | `/kbs/{kb_id}/documents/{doc_id}` | 获取指定文档 |
| DELETE | `/kbs/{kb_id}/documents/{doc_id}` | 删除文档及其 chunks |
| GET | `/kbs/{kb_id}/documents/{doc_id}/chunks` | 列出文档的所有 chunks |
| GET | `/kbs/{kb_id}/chunks/{chunk_id}` | 获取指定 chunk |
| PUT | `/kbs/{kb_id}/chunks/{chunk_id}` | 更新 chunk 文本 |
| POST | `/kbs/{kb_id}/chunks/{chunk_id}/reembed` | 重新生成 chunk embedding |
| DELETE | `/kbs/{kb_id}/chunks/{chunk_id}` | 删除单个 chunk（支持级联删除子 chunk） |
| GET | `/kbs/{kb_id}/chunks/{chunk_id}/children` | 获取 chunk 的子节点列表 |

### 系统设置

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/settings` | 获取系统设置 |
| PUT | `/settings` | 更新系统设置 |

### 管理操作

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/admin/restart-api` | 重启 API 服务 |
| POST | `/admin/restart-scheduler` | 重启任务调度器 |

### 可观测性

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/observability/stats` | 获取模型调用统计（按供应商分组，支持日期范围） |
| POST | `/observability/reset` | 重置所有统计 |
| GET | `/observability/traces` | 获取最近 traces（支持日期范围） |
| GET | `/observability/dates` | 获取有数据的日期列表 |

### 检索查询

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/search` | 向量检索（统一入口） |
| POST | `/query` | RAG 问答（统一入口） |

### 供应商管理

| 方法 | 端点 | 功能 |
|------|------|
| GET | `/vendors` | 列出所有供应商 |
| POST | `/vendors` | 创建供应商 |
| GET | `/vendors/{vendor_id}` | 获取指定供应商 |
| PUT | `/vendors/{vendor_id}` | 更新供应商 |
| DELETE | `/vendors/{vendor_id}` | 删除供应商 |

**供应商类型**:
- **云服务商 (Cloud)**: 需要 API Key（如 SiliconFlow、OpenAI）
- **本地服务商 (Local)**: 无需 API Key（如 Ollama），只需提供 API Base URL

**供应商示例**:
```bash
# 创建供应商
curl -X POST http://localhost:37241/vendors \
  -H "Content-Type: application/json" \
  -d '{
    "id": "siliconflow",
    "name": "SiliconFlow",
    "api_base": "https://api.siliconflow.cn/v1",
    "api_key": "your-api-key"
  }'

# 创建供应商（Ollama不需要API Key）
curl -X POST http://localhost:37241/vendors \
  -H "Content-Type: application/json" \
  -d '{
    "id": "ollama",
    "name": "Ollama",
    "api_base": "http://localhost:11434"
  }'
```

### 模型管理

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/models` | 列出所有模型（支持 `?type=` 筛选） |
| POST | `/models` | 创建模型（供应商不存在时自动创建） |
| GET | `/models/{model_id}` | 获取指定模型 |
| PUT | `/models/{model_id}` | 更新模型 |
| DELETE | `/models/{model_id}` | 删除模型 |
| PUT | `/models/{model_id}/default` | 设置默认模型 |

**模型ID格式**: `{vendor_id}/{model-name}`，如 `siliconflow/DeepSeek-V3.2`、`ollama/lfm2.5-instruct`

**类型筛选**: `?type=llm`、`?type=embedding`、`?type=reranker`

**模型配置 (config)**: 不同类型模型支持不同的配置参数

| 模型类型 | 配置参数 | 说明 | 默认值 |
|---------|---------|------|--------|
| `llm` | `temperature` | 温度参数 (0-2) | 0.7 |
| `llm` | `max_tokens` | 最大 token 数 | 2048 |
| `llm` | `top_p` | Top-p 采样 | 0.9 |
| `llm` | `frequency_penalty` | 频率惩罚 (-2-2) | 0 |
| `embedding` | `dimensions` | 向量维度 | 1024 |
| `embedding` | `batch_size` | 批处理大小 | 32 |
| `embedding` | `pooling` | 池化模式: `mean`/`cls` | `mean` |
| `reranker` | `top_k` | 返回 top k 结果 | 10 |
| `reranker` | `normalize` | 是否归一化分数 | true |

**示例**:
```bash
# 列出所有模型
curl http://localhost:37241/models

# 按类型筛选（llm/embedding/reranker）
curl http://localhost:37241/models?type=llm
curl http://localhost:37241/models?type=embedding

# 创建 LLM 模型（带配置）
curl -X POST http://localhost:37241/models \
  -H "Content-Type: application/json" \
  -d '{
    "id": "ollama/lfm2.5-thinking:latest",
    "vendor_id": "ollama",
    "name": "lfm2.5-thinking:latest",
    "type": "llm",
    "is_default": false,
    "config": {
      "temperature": 0.7,
      "max_tokens": 2048,
      "top_p": 0.9
    }
  }'

# 创建 Embedding 模型（带配置）
curl -X POST http://localhost:37241/models \
  -H "Content-Type: application/json" \
  -d '{
    "id": "ollama/bge-m3:latest",
    "vendor_id": "ollama",
    "name": "bge-m3:latest",
    "type": "embedding",
    "is_default": true,
    "config": {
      "dimensions": 1024,
      "batch_size": 32,
      "pooling": "mean"
    }
  }'

# 使用模型查询
curl -X POST http://localhost:37241/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "测试问题",
    "kb_ids": "my_kb",
    "model_id": "ollama/lfm2.5-thinking:latest"
  }'
```

### Obsidian

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/obsidian/vaults` | 列出 vault 位置 |
| GET | `/obsidian/mappings` | 知识库映射配置 |
| POST | `/obsidian/import-all` | 全库分类导入 |
| GET | `/obsidian/vaults/{name}` | 获取 vault 信息 |

### Zotero

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/zotero/collections` | 列出收藏夹 |
| GET | `/zotero/collections/search` | 搜索收藏夹 |

### 管理

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/admin/tables` | 列出向量表 |
| GET | `/admin/tables/{kb_id}` | 表统计 |
| DELETE | `/admin/tables/{kb_id}` | 删除表 |

---

## 详细接口

### 健康检查

```bash
curl http://localhost:37241/health
```

```json
{"status": "ok", "service": "llamaindex-rag-api", "version": "3.1.0"}
```

---

### 任务队列

#### POST /tasks - 提交任务

```bash
curl -X POST http://localhost:37241/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "obsidian",
    "kb_id": "tech_tools",
    "params": {"rebuild": false},
    "source": "cli"
  }'
```

```json
{"task_id": "abc12345", "status": "pending", "kb_id": "tech_tools", "message": "任务已提交"}
```

#### GET /tasks/{task_id} - 查询任务

```bash
curl http://localhost:37241/tasks/abc12345
```

```json
{
  "task_id": "abc12345",
  "status": "completed",
  "kb_id": "tech_tools",
  "progress": 100,
  "message": "已完成",
  "result": {
    "kb_id": "tech_tools",
    "files": 26,
    "nodes": 248,
    "endpoint_stats": {
      "Ollama-PC": 124,
      "Ollama-Server": 124
    }
  },
  "error": null
}
```

#### GET /tasks - 列出任务

```bash
curl "http://localhost:37241/tasks?status=running&limit=10"
```

#### POST /tasks/{task_id}/cancel - 取消任务

```bash
curl -X POST "http://localhost:37241/tasks/abc12345/cancel"
```

```json
{"status": "cancelled", "task_id": "abc12345", "message": "已取消运行中的任务"}
```

#### POST /tasks/{task_id}/pause - 暂停任务

```bash
curl -X POST "http://localhost:37241/tasks/abc12345/pause"
```

```json
{"status": "paused", "task_id": "abc12345", "message": "任务已暂停"}
```

#### POST /tasks/{task_id}/resume - 恢复任务

```bash
curl -X POST "http://localhost:37241/tasks/abc12345/resume"
```

```json
{"status": "running", "task_id": "abc12345", "message": "任务已恢复"}
```

---

### 文档导入

#### POST /kbs/{kb_id}/ingest

通用文件导入（本地文件、文件夹）：

```bash
curl -X POST "http://localhost:37241/kbs/my_kb/ingest" \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/file.pdf", "async_mode": true, "refresh_topics": true}'
```

> **预验证**：提交任务前会检查路径是否存在、是否有可处理的文件。如果路径不存在或没有找到文件，返回 400 错误。
> 
> **执行语义**：
> - `async_mode=true`：提交后台任务，返回 `task_id`
> - `async_mode=false`：同步执行，直接返回导入统计
> - `refresh_topics`：导入完成后是否刷新 topics

```json
{
  "status": "pending",
  "task_id": "abc12345",
  "message": "导入任务已提交，ID: abc12345，文件数: 5"
}
```

**错误响应**（路径不存在）：
```json
{"detail": "路径不存在: /path/to/file.pdf"}
```

**错误响应**（没有可处理的文件）：
```json
{"detail": "没有找到可处理的文件: /path/to/folder"}
```

#### POST /kbs/{kb_id}/ingest/obsidian

Obsidian vault 导入（多端点并行处理）：

```bash
curl -X POST "http://localhost:37241/kbs/tech_tools/ingest/obsidian" \
  -H "Content-Type: application/json" \
  -d '{
    "vault_path": "/Users/xxx/Documents/Obsidian Vault",
    "folder_path": "IT",
    "recursive": true,
    "async_mode": true,
    "refresh_topics": true
  }'
```

```json
{
  "status": "pending",
  "task_id": "abc12345",
  "message": "Obsidian IT 导入任务已提交，ID: abc12345",
  "source": "obsidian"
}
```

#### POST /kbs/{kb_id}/ingest/zotero

Zotero 收藏夹导入：

```bash
curl -X POST "http://localhost:37241/kbs/swine_nutrition/ingest/zotero" \
  -H "Content-Type: application/json" \
  -d '{
    "collection_name": "营养饲料理论",
    "async_mode": true,
    "refresh_topics": true,
    "chunk_strategy": "hierarchical",
    "chunk_size": 1024,
    "hierarchical_chunk_sizes": [2048, 1024, 512]
  }'
```

请求参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `collection_id` | string | Zotero 收藏夹 ID（精确） |
| `collection_name` | string | 收藏夹名称（可能模糊匹配） |
| `async_mode` | bool | 是否异步处理（默认: true） |
| `rebuild` | bool | 是否清空后重建（默认: false） |
| `refresh_topics` | bool | 导入后是否刷新 topics（默认: true） |
| `chunk_strategy` | string | 分块策略：`hierarchical`（默认）/ `sentence` / `semantic` |
| `chunk_size` | int | 分块大小（默认: 1024） |
| `hierarchical_chunk_sizes` | list[int] | hierarchical 模式分层大小列表 |

```json
{
  "status": "pending",
  "task_id": "xyz67890",
  "message": "Zotero 营养饲料理论 导入任务已提交，ID: xyz67890",
  "source": "zotero"
}
```

#### POST /kbs/{kb_id}/initialize

初始化知识库（清空所有数据，但保留知识库配置）：

```bash
curl -X POST "http://localhost:37241/kbs/tech_tools/initialize"
```

#### GET /kbs/{kb_id}/topics

查看知识库当前 topics：

```bash
curl "http://localhost:37241/kbs/HTE_history/topics"
```

#### POST /kbs/{kb_id}/topics/refresh

手动刷新知识库 topics（可指定是否按"有新文档"模式刷新）：

```bash
curl -X POST "http://localhost:37241/kbs/HTE_history/topics/refresh" \
  -H "Content-Type: application/json" \
  -d '{"has_new_docs": true}'
```

#### GET /kbs/{kb_id}/consistency

校验知识库一致性，比较 documents 表、chunks 表与 LanceDB 实际向量数据：

```bash
curl "http://localhost:37241/kbs/animal_nutrition_breeding/consistency"
```

```json
{
  "kb_id": "animal_nutrition_breeding",
  "status": "issues_found",
  "summary": {
    "doc_count": 221,
    "chunk_count_stored": 1247,
    "chunk_count_actual": 1247,
    "lance_rows": 1200
  },
  "doc_stats": { "accurate": true, "mismatched_count": 0, "issues": [] },
  "embedding_stats": {
    "total": 1247, "success": 1200, "pending": 0, "failed": 47,
    "in_lance": 1200, "missing_in_lance": 0
  },
  "vector_integrity": {
    "status": "missing", "missing_count": 47, "orphan_count": 0, "issues": [...]
  },
  "recommendations": [...]
}
```

**返回值说明：**

| 字段 | 说明 |
|------|------|
| `summary.doc_count` | documents 表的文档数 |
| `summary.chunk_count_actual` | chunks 表的实际 chunk 总数 |
| `summary.lance_rows` | LanceDB 实际向量行数 |
| `embedding_stats.total` | chunks 表总 chunk 数（同 chunk_count_actual） |
| `embedding_stats.success` | emb_status=1 的 chunk 数 |
| `embedding_stats.pending` | emb_status=0 的 chunk 数 |
| `embedding_stats.failed` | emb_status=2 的 chunk 数 |
| `vector_integrity.missing_count` | SQLite 有但 LanceDB 缺少的 chunk 数 |
| `vector_integrity.orphan_count` | LanceDB 有但 SQLite 无的行数 |

#### POST /kbs/{kb_id}/consistency/repair

修复知识库一致性：

```bash
curl -X POST "http://localhost:37241/kbs/animal_nutrition_breeding/consistency/repair" \
  -H "Content-Type: application/json" \
  -d '{"mode": "sync"}'
```

**mode 参数：**

| 值 | 说明 |
|----|------|
| `sync` | 删除 LanceDB 中的 orphan 向量（多余数据） |
| `rebuild` | 重新扫描文件重建（较慢但不丢数据） |
| `dry` | 只报告，不修复 |

#### POST /consistency/repair-all

修复所有知识库的一致性：

```bash
curl -X POST "http://localhost:37241/consistency/repair-all?mode=sync"
```

```json
{
  "total": 5,
  "repaired": 3,
  "failed": 0,
  "results": [...]
}
```

---

### 检索查询

#### POST /search

向量检索的统一入口，支持两种路由模式：

```bash
# 用户选择知识库检索（默认）
curl -X POST "http://localhost:37241/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程", "kb_ids": "tech_tools,academic", "top_k": 5}'

# 自动路由检索
curl -X POST "http://localhost:37241/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程", "route_mode": "auto"}'

# 自动路由 + 指定模型
curl -X POST "http://localhost:37241/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程", "route_mode": "auto", "model_id": "ollama/lfm2.5-instruct:1.2b"}'

# 混合搜索模式
curl -X POST "http://localhost:37241/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程", "kb_ids": "tech_tools", "retrieval_mode": "hybrid"}'
```

**请求参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | string | 必填 | 查询内容 |
| `route_mode` | enum | `"general"` | 路由模式：`general` 或 `auto` |
| `top_k` | int | `5` | 返回结果数量 |
| `retrieval_mode` | enum | `"vector"` | 检索模式：`vector` 或 `hybrid` |
| `model_id` | string | null | 使用的模型ID（如 `siliconflow/DeepSeek-V3.2`, `ollama/lfm2.5-instruct`），不填则使用默认模型（Ollama） |
| `embed_model_id` | string | null | 使用的 Embedding 模型ID（如 `ollama/bge-m3:latest`） |
| `kb_ids` | string | null | 指定知识库 ID（逗号分隔，`route_mode=general` 时必填） |
| `exclude` | string[] | null | 排除的知识库 ID 列表（仅 `route_mode=auto` 时有效） |
| `use_auto_merging` | bool | null | 启用 Auto-Merging（null=使用配置默认值） |

**参数约束：**
- `route_mode=general`：必须提供 `kb_ids`，且不支持 `exclude`
- `route_mode=auto`：可使用 `exclude`，`kb_ids` 可省略

**响应格式：**

```json
[
  {
    "text": "异步编程是 Python 中的重要概念...",
    "score": 0.85,
    "metadata": {"file_path": "IT/Python异步.md"},
    "kb_id": "tech_tools"
  }
]
```

#### POST /query

RAG 问答的统一入口，支持两种路由模式：

```bash
# 用户选择知识库问答（默认）
curl -X POST "http://localhost:37241/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "如何优化 Python 性能？", "kb_ids": "tech_tools,academic", "top_k": 5}'

# 自动路由问答
curl -X POST "http://localhost:37241/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "如何优化 Python 性能？", "route_mode": "auto"}'

# 使用指定模型问答
curl -X POST "http://localhost:37241/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "如何优化 Python 性能？", "kb_ids": "tech_tools", "model_id": "ollama/lfm2.5-thinking:latest"}'
```

**请求参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | string | 必填 | 查询内容 |
| `route_mode` | enum | `"general"` | 路由模式：`general` 或 `auto` |
| `top_k` | int | `5` | 返回结果数量 |
| `retrieval_mode` | enum | `"vector"` | 检索模式：`vector` 或 `hybrid` |
| `model_id` | string | null | 使用的模型ID（如 `siliconflow/DeepSeek-V3.2`, `ollama/lfm2.5-instruct`），不填则使用默认模型 |
| `kb_ids` | string | null | 指定知识库 ID（逗号分隔，`route_mode=general` 时必填） |
| `exclude` | string[] | null | 排除的知识库 ID 列表（仅 `route_mode=auto` 时有效） |
| `use_hyde` | bool | null | 启用 HyDE 查询转换（null=使用配置默认值） |
| `use_multi_query` | bool | null | 启用多查询转换（null=使用配置默认值） |
| `use_auto_merging` | bool | null | 启用 Auto-Merging（null=使用配置默认值） |
| `response_mode` | string | null | 答案生成模式（null=使用配置默认值） |

**参数约束：**
- `route_mode=general`：必须提供 `kb_ids`，且不支持 `exclude`
- `route_mode=auto`：可使用 `exclude`，`kb_ids` 可省略

**响应格式：**

```json
{
  "response": "优化 Python 性能可以从以下几个方面入手...",
  "sources": [
    {"text": "Python 性能优化技巧...", "score": 0.85}
  ]
}
```

### 检索查询扩展功能

#### HyDE 查询转换

HyDE (Hypothetical Document Embeddings) 使用 LLM 生成假设性文档，然后用假设性文档的 embedding 来检索真实文档：

```bash
curl -X POST "http://localhost:37241/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程最佳实践", "kb_ids": "tech_tools", "use_hyde": true}'
```

#### 多查询转换

生成多个查询变体，减少检索遗漏：

```bash
curl -X POST "http://localhost:37241/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "如何优化 Python 性能", "kb_ids": "tech_tools", "use_multi_query": true}'
```

#### Auto-Merging Retriever

自动合并相关子节点为父节点，提供更完整的上下文：

```bash
curl -X POST "http://localhost:37241/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程", "kb_ids": "tech_tools", "use_auto_merging": true}'
```

> **注意**：Auto-Merging 需要知识库使用 `hierarchical` 分块策略（父子节点分块）。如果 KB 使用 `sentence` 或 `semantic` 策略，查询时会自动回退到普通 retriever。

#### 组合使用

HyDE、多查询转换、Auto-Merging 可以任意组合同时使用：

```bash
# 同时启用 HyDE + 多查询 + Auto-Merging
curl -X POST "http://localhost:37241/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "后备母猪营养需要",
    "kb_ids": "animal-nutrition-breeding",
    "use_hyde": true,
    "use_multi_query": true,
    "use_auto_merging": true
  }'
```

组合使用会消耗更多 LLM 调用和检索时间，但通常能获得更好的检索质量。

#### Response Synthesizer

答案生成模式，可通过 `response_mode` 参数动态指定：

```bash
curl -X POST "http://localhost:37241/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 性能优化", "kb_ids": "tech_tools", "response_mode": "tree_summarize"}'
```

| 模式 | 说明 |
|------|------|
| `compact` | 压缩检索结果后生成答案（默认） |
| `refine` | 迭代优化答案 |
| `tree_summarize` | 构建答案树结构 |
| `simple_summarize` | 简单拼接检索结果 |
| `accumulate` | 累积式生成 |
| `generation` | 仅生成答案（不使用检索结果） |
| `compact_accumulate` | 压缩后累积式生成 |

---

### RAG 评估

#### POST /evaluate/{kb_id} - RAG 性能评估

对知识库进行 RAG 评估，使用预设的问题和标准答案：

```bash
curl -X POST "http://localhost:37241/evaluate/tech_tools" \
  -H "Content-Type: application/json" \
  -d '{
    "questions": ["Python 异步编程的要点是什么？", "如何优化代码性能？"],
    "ground_truths": ["异步编程涉及 asyncio、await、async def 等概念...", "代码优化包括算法改进、缓存、并行化..."],
    "top_k": 5
  }'
```

**请求参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `questions` | string[] | 是 | 问题列表 |
| `ground_truths` | string[] | 是 | 标准答案列表（与问题数量一致） |
| `top_k` | int | 否 | 检索返回结果数，默认 5 |

**返回**：

```json
{
  "faithfulness": 0.85,
  "answer_relevancy": 0.78,
  "context_precision": 0.82,
  "context_recall": 0.75
}
```

#### GET /evaluate/metrics - 获取评估指标说明

```bash
curl http://localhost:37241/evaluate/metrics
```

**返回**：

```json
{
  "faithfulness": {
    "name": "忠实度",
    "description": "答案是否忠实于检索到的上下文，没有幻觉",
    "good_range": "> 0.8",
    "bad_range": "< 0.5",
    "优化方向": "提高检索质量，使用更相关的上下文"
  },
  "answer_relevancy": {...},
  "context_precision": {...},
  "context_recall": {...}
}
```

---

## 文档管理

### 列出文档

#### GET /kbs/{kb_id}/documents - 列出知识库的所有文档

```bash
curl http://localhost:37241/kbs/tech_tools/documents
```

```json
{
  "id": "doc-uuid-1234",
  "kb_id": "tech_tools",
  "source_file": "guide.md",
  "source_path": "/path/to/guide.md",
  "file_hash": "abc123...",
  "file_size": 12345,
  "mime_type": "text/markdown",
  "chunk_count": 5,
  "total_chars": 15000,
  "metadata": {},
  "created_at": 1712500000.0,
  "updated_at": 1712500000.0
}
```

### 获取文档详情

#### GET /kbs/{kb_id}/documents/{doc_id} - 获取指定文档

```bash
curl http://localhost:37241/kbs/tech_tools/documents/doc-uuid-1234
```

### 删除文档

#### DELETE /kbs/{kb_id}/documents/{doc_id} - 删除文档及其所有 chunks

```bash
curl -X DELETE http://localhost:37241/kbs/tech_tools/documents/doc-uuid-1234
```

```json
{
  "status": "deleted",
  "doc_id": "doc-uuid-1234",
  "chunks_deleted": 5
}
```

### 列出文档的 Chunks

#### GET /kbs/{kb_id}/documents/{doc_id}/chunks - 列出文档的所有 chunks

```bash
curl http://localhost:37241/kbs/tech_tools/documents/doc-uuid-1234/chunks
```

```json
[
  {
    "id": "chunk-uuid-1",
    "doc_id": "doc-uuid-1234",
    "kb_id": "tech_tools",
    "text": "这是第一个 chunk 的内容...",
    "text_length": 500,
    "chunk_index": 0,
    "parent_chunk_id": null,
    "hierarchy_level": 0,
    "metadata": {},
    "embedding_generated": true,
    "created_at": 1712500000.0,
    "updated_at": 1712500000.0
  }
]
```

## Chunk 管理

### 获取 Chunk

#### GET /kbs/{kb_id}/chunks/{chunk_id} - 获取指定 chunk

```bash
curl http://localhost:37241/kbs/tech_tools/chunks/chunk-uuid-1
```

### 更新 Chunk 文本

#### PUT /kbs/{kb_id}/chunks/{chunk_id} - 更新 chunk 文本

```bash
curl -X PUT http://localhost:37241/kbs/tech_tools/chunks/chunk-uuid-1 \
  -H "Content-Type: application/json" \
  -d '{"text": "更新后的 chunk 内容..."}'
```

### 重新生成 Chunk Embedding

#### POST /kbs/{kb_id}/chunks/{chunk_id}/reembed - 重新生成 embedding

```bash
curl -X POST http://localhost:37241/kbs/tech_tools/chunks/chunk-uuid-1/reembed
```

```json
{
  "status": "success",
  "chunk_id": "chunk-uuid-1",
  "embedding_generated": true
}
```

---

### 删除单个 Chunk

#### DELETE /kbs/{kb_id}/chunks/{chunk_id} - 删除单个 chunk（支持级联）

```bash
# 级联删除（包括子 chunk）
curl -X DELETE "http://localhost:37241/kbs/tech_tools/chunks/chunk-uuid-1?cascade=true"

# 非级联删除（将子 chunk 孤立）
curl -X DELETE "http://localhost:37241/kbs/tech_tools/chunks/chunk-uuid-1?cascade=false"
```

**参数说明：**
- `cascade=true`（默认）：递归删除该 chunk 的所有子 chunk
- `cascade=false`：将该 chunk 的子 chunk 的 `parent_chunk_id` 设为 null（孤立）

**响应示例：**

```json
{
  "status": "success",
  "chunk_id": "chunk-uuid-1",
  "deleted_chunks": 3,
  "deleted_lance": 3,
  "children_orphaned": 0,
  "cascade": true
}
```

**返回字段：**
| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 操作状态 |
| `chunk_id` | string | 被删除的 chunk ID |
| `deleted_chunks` | int | 从 chunk_db 删除的 chunk 数量 |
| `deleted_lance` | int | 从 LanceDB 删除的向量记录数 |
| `children_orphaned` | int | 被孤立的子 chunk 数量（cascade=false 时） |
| `cascade` | bool | 是否执行了级联删除 |

---

#### GET /kbs/{kb_id}/chunks/{chunk_id}/children - 获取子节点列表

```bash
curl http://localhost:37241/kbs/tech_tools/chunks/chunk-uuid-1/children
```

**响应示例：**

```json
{
  "children": [
    {
      "id": "chunk-uuid-2",
      "doc_id": "doc-uuid-1",
      "kb_id": "tech_tools",
      "text": "子 chunk 内容...",
      "text_length": 150,
      "chunk_index": 1,
      "parent_chunk_id": "chunk-uuid-1",
      "hierarchy_level": 1,
      "metadata": {},
      "embedding_generated": true,
      "created_at": 1710000000,
      "updated_at": 1710000000
    }
  ],
  "count": 1
}
```

---

## 系统设置

### 获取系统设置

#### GET /settings - 获取当前系统配置

```bash
curl http://localhost:37241/settings
```

```json
{
  "embed_batch_size": 32,
  "top_k": 5,
  "use_semantic_chunking": false,
  "use_hybrid_search": false,
  "use_auto_merging": false,
  "use_hyde": false,
  "use_multi_query": false,
  "num_multi_queries": 3,
  "hybrid_search_alpha": 0.5,
  "hybrid_search_mode": "relative_score",
  "chunk_strategy": "hierarchical",
  "chunk_size": 1024,
  "chunk_overlap": 100,
  "hierarchical_chunk_sizes": [2048, 1024, 512],
  "use_reranker": true,
  "response_mode": "compact",
  "progress_update_interval": 10,
  "max_concurrent_tasks": 10,
  "max_retries": 5,
  "retry_delay": 2.0
}
```

### 更新系统设置

#### PUT /settings - 更新系统配置

```bash
curl -X PUT http://localhost:37241/settings \
  -H "Content-Type: application/json" \
  -d '{
    "top_k": 10,
    "use_hybrid_search": true,
    "use_auto_merging": true
  }'
```

**设置持久化机制：**

| 设置类别 | 设置项 | 持久化位置 | 生效方式 |
|----------|--------|------------|----------|
| 运行时设置 | `embed_batch_size`, `top_k`, `use_hybrid_search`, `use_auto_merging`, `use_hyde`, `use_multi_query`, `num_multi_queries`, `hybrid_search_alpha`, `use_reranker`, `response_mode`, `max_retries`, `retry_delay` | `.runtime_settings.json` | 立即生效 |
| Chunk 设置 | `chunk_strategy`, `chunk_size`, `chunk_overlap`, `hierarchical_chunk_sizes` | `.runtime_settings.json` | 立即生效，**仅影响新导入的文档** |
| Task 设置 | `progress_update_interval`, `max_concurrent_tasks` | `.runtime_settings.json` | 立即生效 |
| 模型配置 | LLM/Embedding/Reranker 模型 | 模型数据库 | 通过 `models` API 管理 |

**注意：**
- Chunk 设置只对新导入的文档生效，已有的知识库不受影响
- 所有模型配置通过 `/models` 和 `/vendors` API 管理，不再使用环境变量

## 管理操作

### 重启 API 服务

#### POST /admin/restart-api - 重启 API 服务

完全重启 API 服务器。这将中断所有正在进行的请求。

```bash
curl -X POST http://localhost:37241/admin/restart-api
```

```json
{
  "status": "restarting",
  "message": "API 服务正在重启..."
}
```

**注意：**
- 此操作将完全重启 API 服务，中断所有正在处理的请求
- 客户端应等待 2-3 秒后重试连接
- 前端页面会自动刷新

### 重启调度器

#### POST /admin/restart-scheduler - 重启任务调度器

```bash
curl -X POST http://localhost:37241/admin/restart-scheduler
```

```json
{
  "status": "restarting",
  "message": "调度器正在重启..."
}
```

### 重载配置

#### POST /admin/reload-config - 重新加载配置

重新加载模型注册表和运行时设置。用于在修改 LLM/Embedding 配置后使更改生效。

```bash
curl -X POST http://localhost:37241/admin/reload-config
```

```json
{
  "status": "success",
  "message": "配置已重新加载"
}
```

**说明：**
- 重新加载模型注册表（从数据库读取最新的供应商和模型信息）
- 重新加载运行时设置（从 `.runtime_settings.json` 读取最新值）
- 对于 LLM/Embedding 设置的修改，仍需要重启服务才能完全生效

---

## 可观测性

> **数据持久化**: 统计数据存储在 `~/.llamaindex/stats/token_stats.db`（SQLite），支持按日期范围查询历史数据。

### 获取模型调用统计

#### GET /observability/stats - 获取模型调用统计

获取按供应商和模型分组的调用统计信息。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `start_date` | string | - | 开始日期 (YYYY-MM-DD)，支持历史查询 |
| `end_date` | string | - | 结束日期 (YYYY-MM-DD)，支持历史查询 |

```bash
# 查询所有历史
curl http://localhost:37241/observability/stats

# 查询特定日期范围
curl "http://localhost:37241/observability/stats?start_date=2026-04-01&end_date=2026-04-08"

# 查询今天
curl "http://localhost:37241/observability/stats?start_date=2026-04-08&end_date=2026-04-08"
```

**响应（带日期范围查询）：**
```json
{
  "vendor_stats": [...],
  "total_calls": 100,
  "total_tokens": 50000,
  "total_prompt_tokens": 40000,
  "total_completion_tokens": 10000,
  "total_errors": 2,
  "start_date": "2026-04-01",
  "end_date": "2026-04-08"
}
```
```json
{
  "vendor_stats": [
    {
      "vendor_id": "siliconflow",
      "models": [
        {
          "vendor_id": "siliconflow",
          "model_type": "llm",
          "model_id": "Pro/deepseek-ai/DeepSeek-V3.2",
          "call_count": 10,
          "prompt_tokens": 5000,
          "completion_tokens": 2500,
          "total_tokens": 7500,
          "error_count": 0
        },
        {
          "vendor_id": "siliconflow",
          "model_type": "embedding",
          "model_id": "Pro/BAAI/bge-m3",
          "call_count": 5,
          "prompt_tokens": 1200,
          "completion_tokens": 0,
          "total_tokens": 1200,
          "error_count": 0
        }
      ],
      "total_calls": 15,
      "total_prompt_tokens": 6200,
      "total_completion_tokens": 2500,
      "total_tokens": 8700,
      "total_errors": 0
    },
    {
      "vendor_id": "ollama",
      "models": [
        {
          "vendor_id": "ollama",
          "model_type": "llm",
          "model_id": "tomng/lfm2.5-instruct:1.2b",
          "call_count": 3,
          "prompt_tokens": 800,
          "completion_tokens": 400,
          "total_tokens": 1200,
          "error_count": 1
        }
      ],
      "total_calls": 3,
      "total_prompt_tokens": 800,
      "total_completion_tokens": 400,
      "total_tokens": 1200,
      "total_errors": 1
    }
  ],
  "total_calls": 18,
  "total_tokens": 9900
}
```

**统计维度：**

| 字段 | 说明 |
|------|------|
| `vendor_stats` | 按供应商分组的统计数据 |
| `vendor_stats[].vendor_id` | 供应商 ID（如 `ollama`, `siliconflow`） |
| `vendor_stats[].models` | 该供应商下的所有模型统计 |
| `model_type` | 模型类型：`llm`、`embedding`、`reranker` |
| `model_id` | 模型 ID（如 `siliconflow/DeepSeek-V3.2`） |
| `call_count` | 调用次数 |
| `prompt_tokens` | 输入 tokens |
| `completion_tokens` | 输出 tokens（仅 LLM） |
| `total_tokens` | 总 tokens |
| `error_count` | 错误次数 |
| `total_calls` | 该分组内所有调用的总次数 |
| `total_tokens` | 该分组内所有调用的总 tokens |

**统计覆盖范围：**
- LLM 调用（`complete`、`chat`、`predict` 等）
- Embedding 调用（`get_text_embedding`）
- Reranker 调用

---

### 重置统计

#### POST /observability/reset - 重置所有统计

清除所有模型调用统计和 traces。

```bash
curl -X POST http://localhost:37241/observability/reset
```

**响应：**
```json
{
  "status": "reset"
}
```

---

### 获取 Traces

#### GET /observability/traces - 获取最近 traces

获取最近的 RAG 执行 traces。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 100 | 返回条数 |
| `start_date` | string | - | 开始日期 (YYYY-MM-DD) |
| `end_date` | string | - | 结束日期 (YYYY-MM-DD) |

```bash
# 获取最近 50 条
curl "http://localhost:37241/observability/traces?limit=50"

# 查询特定日期范围
curl "http://localhost:37241/observability/traces?start_date=2026-04-01&end_date=2026-04-08&limit=100"
```

**响应：**
```json
{
  "traces": [
    {
      "date": "2026-04-08",
      "timestamp": "2026-04-08T10:30:00",
      "query": "如何设计猪饲料配方？",
      "duration_ms": 123.45,
      "retrieval_count": 5,
      "retrieval_scores": [0.92, 0.88, 0.85, 0.82, 0.78],
      "source_node_count": 3,
      "llm_input_tokens": 500,
      "llm_output_tokens": 100,
      "embedding_tokens": 200,
      "total_tokens": 800,
      "error": null
    }
  ],
  "total": 1,
  "start_date": "2026-04-01",
  "end_date": "2026-04-08"
}
```

---

### 获取可用日期

#### GET /observability/dates - 获取有数据的日期列表

```bash
curl http://localhost:37241/observability/dates
```

**响应：**
```json
{
  "dates": ["2026-04-08", "2026-04-07", "2026-04-06", "2026-04-05"]
}
```

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 100 | 返回的 trace 数量上限 |

**响应：**
```json
{
  "traces": [
    {
      "timestamp": "2024-01-15T10:30:00",
      "query": "如何优化 Python 性能",
      "duration_ms": 1250.5,
      "retrieval_count": 5,
      "retrieval_scores": [0.95, 0.88, 0.82, 0.75, 0.71],
      "source_node_count": 3,
      "llm_input_tokens": 1500,
      "llm_output_tokens": 300,
      "embedding_tokens": 200,
      "total_tokens": 2000
    }
  ],
  "total": 1
}
```

---

## WebSocket 实时推送

### 连接

```javascript
const ws = new WebSocket("ws://localhost:37241/ws/tasks");
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(`进度: ${data.progress}% - ${data.message}`);
};
```

### 推送消息

```json
{
  "type": "task_update",
  "task_id": "abc12345",
  "data": {
    "status": "running",
    "progress": 45,
    "message": "处理 10/26 (25 chunks)"
  }
}
```

---

## 完整示例

### Python

```python
import requests
import time

BASE = "http://localhost:37241"

# 1. 提交导入任务
r = requests.post(f"{BASE}/kbs/tech_tools/ingest/obsidian",
    json={"recursive": True})
task_id = r.json()["task_id"]
print(f"任务 ID: {task_id}")

# 2. 轮询查询状态
while True:
    r = requests.get(f"{BASE}/tasks/{task_id}").json()
    print(f"进度: {r['progress']}% - {r['message']}")
    if r["status"] in ["completed", "failed"]:
        break
    time.sleep(5)

# 3. 查看端点统计
if r["result"]:
    print(f"Ollama-PC: {r['result']['endpoint_stats']['Ollama-PC']}")
    print(f"Ollama-Server: {r['result']['endpoint_stats']['Ollama-Server']}")

# 4. 搜索
r = requests.post(f"{BASE}/search",
    json={"query": "Python", "kb_ids": "tech_tools", "top_k": 5})
print(r.json())
```

### cURL

```bash
# 提交任务
curl -X POST "http://localhost:37241/kbs/tech_tools/ingest/obsidian" \
  -H "Content-Type: application/json" \
  -d '{"recursive": true}'

# 查询状态
curl "http://localhost:37241/tasks/{task_id}"

# 搜索
curl -X POST "http://localhost:37241/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python", "kb_ids": "tech_tools", "top_k": 5}'
```

---

## 任务状态

| 状态 | 说明 |
|------|------|
| `pending` | 等待执行 |
| `running` | 执行中 |
| `completed` | 已完成 |
| `failed` | 失败 |
| `cancelled` | 已取消 |

---

## 任务结果

成功完成的任务返回：

```json
{
  "kb_id": "tech_tools",
  "files": 26,
  "nodes": 248,
  "sources": ["/path/to/file1.md", "/path/to/file2.md"],
  "endpoint_stats": {
    "Ollama-PC": 124,
    "Ollama-Server": 124
  },
  "chunk_strategy": "hierarchical"
}
```

| 字段 | 说明 |
|------|------|
| `kb_id` | 知识库 ID |
| `files` | 处理的文件数 |
| `nodes` | 生成的节点数 |
| `sources` | 处理的源文件路径列表（用于清理） |
| `endpoint_stats` | 每个 Ollama 端点处理的 chunk 数量 |
| `chunk_strategy` | 分块策略：`hierarchical`/`sentence`/`semantic` |

## 知识库详情

`GET /kbs/{kb_id}` 返回：

```json
{
  "id": "tech_tools",
  "name": "技术工具",
  "description": "技术文档知识库",
  "persist_dir": "/path/to/persist",
  "status": "indexed",
  "row_count": 1248,
  "chunk_strategy": "hierarchical"
}
```

| 字段 | 说明 |
|------|------|
| `chunk_strategy` | 知识库的分块策略，用于判断是否支持 Auto-Merging |

---

## 环境变量配置

### 存储路径配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OBSIDIAN_VAULT_ROOT` | `~/Documents/Obsidian Vault` | Obsidian Vault 根目录 |
| `PERSIST_DIR` | `/Volumes/online/llamaindex` | 向量存储目录（通用 KB） |
| `ZOTERO_PERSIST_DIR` | `/Volumes/online/llamaindex/zotero` | Zotero 存储目录 |

### API 服务配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `API_PORT` | `37241` | API 服务端口 |

### Embedding 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_EMBED_MODEL` | `bge-m3` | Embedding 模型名称 |

> **注意**: Ollama 供应商通过 CLI/API 管理（`vendor add` / `model add`），端点配置和模型维度存储在数据库中。

### 任务处理配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CHUNK_SIZE` | `1024` | 文本分块大小 |
| `CHUNK_OVERLAP` | `100` | 文本分块重叠 |
| `PROGRESS_UPDATE_INTERVAL` | `10` | 进度更新间隔 |
| `MAX_CONCURRENT_TASKS` | `10` | 最大并发任务数 |

### 并行 Embedding 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MAX_RETRIES` | `5` | 每个端点最大重试次数 |
| `RETRY_DELAY` | `2.0` | 重试延迟（秒） |
| `EMBED_BATCH_SIZE` | `32` | Embedding 批处理大小 |

### 检索配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TOP_K` | `5` | 每个知识库返回的结果数量 |
| `CHUNK_STRATEGY` | `hierarchical` | 分块策略：`hierarchical`/`sentence`/`semantic` |
| `CHUNK_SIZE` | `1024` | 默认分块大小 |
| `CHUNK_OVERLAP` | `100` | 分块重叠 |
| `HIERARCHICAL_CHUNK_SIZES` | `2048,1024,512` | 层级分块各层大小 |
| `USE_SEMANTIC_CHUNKING` | `false` | 启用语义分块（需重建知识库） |
| `USE_AUTO_MERGING` | `false` | 启用 Auto-Merging Retriever（需知识库使用 hierarchical 分块） |
| `USE_HYBRID_SEARCH` | `false` | 启用混合搜索（向量 + BM25） |
| `HYBRID_SEARCH_ALPHA` | `0.5` | 混合搜索向量权重（0-1，1=仅向量） |
| `HYBRID_SEARCH_MODE` | `relative_score` | 混合搜索融合模式 |
| `USE_HYDE` | `false` | 启用 HyDE 查询转换 |
| `USE_MULTI_QUERY` | `false` | 启用多查询转换 |
| `MULTI_QUERY_NUM` | `3` | 多查询生成变体数量 |
| `RESPONSE_MODE` | `compact` | 答案生成模式 |

### Reranker 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RERANK_MODEL` | `Pro/BAAI/bge-reranker-v2-m3` | 重排序模型名称 |
| `USE_RERANKER` | `true` | 是否启用重排序 |

### 向量数据库配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VECTOR_STORE_TYPE` | `lancedb` | 向量存储类型（lancedb/qdrant） |
| `VECTOR_DB_URI` | 空 | 向量数据库 URI |
| `VECTOR_TABLE_NAME` | `llamaindex` | 向量表名称 |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant 服务器地址 |
| `QDRANT_API_KEY` | 空 | Qdrant API 密钥 |

---

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
│   ├── progress                 # 处理进度
│   ├── knowledge_bases          # 知识库元数据
│   ├── documents                # 文档记录（含去重信息）
│   └── chunks                   # chunk 记录（含 emb_status）
└── tasks.db                     # 任务队列
```

**存储策略：**
- 通用 KB（Obsidian 等）→ `PERSIST_DIR/{kb_id}/`
- Zotero KB → `ZOTERO_PERSIST_DIR/{kb_id}/`
- 知识库元数据全部存储在数据库中，`KNOWLEDGE_BASES` 仅作种子数据

---

## CLI 工具

除了 API，还可以用 CLI：

```bash
# 列出知识库
uv run llamaindex-study kb list

# 检索 / 问答
uv run llamaindex-study search "Python 异步编程" --kb-ids tech_tools -k 5
uv run llamaindex-study query "总结当前知识库重点" --kb-ids tech_tools

# 提交导入任务
uv run llamaindex-study ingest obsidian tech_tools --folder-path IT
uv run llamaindex-study ingest file tech_tools README.md

# 查看任务状态
uv run llamaindex-study task list
uv run llamaindex-study task show <task_id>

# 配置管理
uv run llamaindex-study config list
uv run llamaindex-study config get OLLAMA_EMBED_MODEL
uv run llamaindex-study config set USE_HYBRID_SEARCH true
```
