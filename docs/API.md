# LlamaIndex RAG API 文档

> ⚠️ 基于 LlamaIndex v0.14+ 构建，2026-03-30 完成升级（原 v0.10 → v0.14）

## 相关文档

- [Query 参数设计指南](./QUERY_PARAM_GUIDE.md) - **客户端 UI 设计必读**，详细说明 route_mode、retrieval_mode、各检索增强参数的适用场景
- [CLI 使用文档](./CLI.md) - 命令行接口详细说明
- [架构设计](./ARCHITECTURE.md) - 系统架构与设计模式

## 概述

基于 FastAPI 的 RAG（检索增强生成）API 服务，支持：

- **并行多端点 Ollama** - 本地 + 远程自适应负载均衡，快的多处理，慢的少处理
- **失败重试机制** - 每个端点最多重试 3 次
- **任务队列** - 异步提交，随时查询状态
- **增量同步** - 基于文件哈希检测变更
- **资源保护** - 去重串行访问、LanceDB 串行写入
- **混合搜索** - 向量检索 + BM25 关键词融合（需启用）
- **Auto-Merging** - 检索时自动合并相关子节点（需启用）

## 启动服务

```bash
cd ~/文档/GitHub/llamaindex-study
uv run python api.py
```

 - 服务地址: `http://localhost:37241`
 - API 文档: `http://localhost:37241/docs`
 - Markdown API 文档: `http://localhost:37241/api-docs`
 - WebSocket: `ws://localhost:37241/ws/tasks`

---

## 核心功能

### 并行多端点 Ollama（自适应负载均衡）

导入任务使用**本地 + 远程 Ollama 自适应分配**：

- **队列机制**：所有 chunk 进入共享队列
- **自动均衡**：每个端点处理完一个后自动取下一个
- **速度自适应**：处理快的端点分配更多任务，处理慢的少分配

```
Chunk 队列：
[Chunk 1] [Chunk 2] [Chunk 3] [Chunk 4] [Chunk 5] ...

端点分配（快的多处理）：
本地 Ollama  ──→ Chunk 1, Chunk 3, Chunk 5 ...  （假设处理快）
远程 Ollama  ──→ Chunk 2, Chunk 4 ...          （处理较慢）
```

配置文件（环境变量）：
- 本地: `OLLAMA_LOCAL_URL` (默认: `http://localhost:11434`)
- 远程: `OLLAMA_REMOTE_URL` (默认: 空，留空表示禁用第二端点)
- 重试次数: `MAX_RETRIES` (默认: 3)

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
      "本地": 124,
      "远程": 124
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
| DELETE | `/tasks/{task_id}` | 取消任务 |
| POST | `/tasks/{task_id}/pause` | 暂停任务 |
| POST | `/tasks/{task_id}/resume` | 恢复任务 |
| DELETE | `/tasks/{task_id}/delete` | 删除任务（可选 cleanup=true 清理关联数据） |
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

### 文档导入

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/kbs/{kb_id}/ingest` | 通用文件导入 |
| POST | `/kbs/{kb_id}/ingest/obsidian` | Obsidian 导入（并行） |
| POST | `/kbs/{kb_id}/ingest/zotero` | Zotero 导入 |
| POST | `/kbs/{kb_id}/initialize` | 初始化知识库（清空数据） |

### 检索查询

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/search` | 向量检索（统一入口） |
| POST | `/query` | RAG 问答（统一入口） |

### Obsidian

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/obsidian/vaults` | 列出 vault 位置 |
| GET | `/obsidian/mappings` | 知识库映射配置 |
| POST | `/obsidian/import-all` | 全库分类导入 |
| GET | `/obsidian/vaults/{name}` | 获取 vault 信息 |

### 分类规则

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/category/rules` | 列出分类规则 |
| POST | `/category/rules/sync` | 同步分类规则到数据库 |
| POST | `/category/classify` | 分类文件夹 |
| POST | `/category/rules/add` | 添加分类规则 |

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
      "本地": 124,
      "远程": 124
    }
  },
  "error": null
}
```

#### GET /tasks - 列出任务

```bash
curl "http://localhost:37241/tasks?status=running&limit=10"
```

#### DELETE /tasks/{task_id} - 取消任务

```bash
curl -X DELETE "http://localhost:37241/tasks/abc12345"
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
  -d '{"path": "/path/to/file.pdf"}'
```

> **预验证**：提交任务前会检查路径是否存在、是否有可处理的文件。如果路径不存在或没有找到文件，返回 400 错误。

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

Obsidian vault 导入（本地+远程并行处理）：

```bash
curl -X POST "http://localhost:37241/kbs/tech_tools/ingest/obsidian" \
  -H "Content-Type: application/json" \
  -d '{
    "vault_path": "/Users/xxx/Documents/Obsidian Vault",
    "folder_path": "IT",
    "recursive": true
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
  -d '{"collection_name": "营养饲料理论"}'
```

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
```

**请求参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | string | 必填 | 查询内容 |
| `route_mode` | string | `"general"` | 路由模式：`general`(用户选择知识库), `auto`(自动路由) |
| `top_k` | int | `5` | 返回结果数量 |
| `kb_ids` | string | null | 指定知识库 ID（逗号分隔，`route_mode=general` 时必填） |
| `exclude` | string[] | null | 排除的知识库 ID 列表（仅 `route_mode=auto` 时有效） |
| `use_auto_merging` | bool | null | 启用 Auto-Merging（null=使用配置默认值） |

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
```

**请求参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | string | 必填 | 查询内容 |
| `route_mode` | string | `"general"` | 路由模式：`general`(用户选择知识库), `auto`(自动路由) |
| `top_k` | int | `5` | 返回结果数量 |
| `retrieval_mode` | string | `"vector"` | 检索模式：`vector` 或 `hybrid` |
| `kb_ids` | string | null | 指定知识库 ID（逗号分隔，`route_mode=general` 时必填） |
| `exclude` | string[] | null | 排除的知识库 ID 列表（仅 `route_mode=auto` 时有效） |
| `use_hyde` | bool | null | 启用 HyDE 查询转换（null=使用配置默认值） |
| `use_multi_query` | bool | null | 启用多查询转换（null=使用配置默认值） |
| `use_auto_merging` | bool | null | 启用 Auto-Merging（null=使用配置默认值） |
| `response_mode` | string | null | 答案生成模式（null=使用配置默认值） |

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
| `no_text` | 仅返回检索结果，不生成答案 |
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

### 分类规则

#### GET /category/rules - 列出分类规则

```bash
curl http://localhost:37241/category/rules
```

```json
{
  "rules": [
    {
      "id": 1,
      "kb_id": "tech_tools",
      "rule_type": "folder_path",
      "pattern": "IT",
      "description": "文件夹路径匹配: IT",
      "priority": 100
    }
  ],
  "total": 5
}
```

#### POST /category/classify - 分类文件夹

```bash
curl -X POST "http://localhost:37241/category/classify" \
  -H "Content-Type: application/json" \
  -d '{"folder_path": "/path/to/folder", "use_llm": true}'
```

```json
{
  "kb_id": "tech_tools",
  "matched_by": "llm",
  "confidence": 0.85,
  "reason": "基于 LLM 分析，文件夹内容与 IT 技术相关"
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
    print(f"本地: {r['result']['endpoint_stats']['本地']}")
    print(f"远程: {r['result']['endpoint_stats']['远程']}")

# 4. 搜索
r = requests.post(f"{BASE}/kbs/tech_tools/search",
    json={"query": "Python", "top_k": 5})
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
curl -X POST "http://localhost:37241/kbs/tech_tools/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python", "top_k": 5}'
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
    "本地": 124,
    "远程": 124
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
| `EMBEDDING_DIM` | `1024` | Embedding 向量维度 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | 默认 Ollama 地址 |
| `OLLAMA_LOCAL_URL` | `http://localhost:11434` | 本地 Ollama 地址 |
| `OLLAMA_REMOTE_URL` | 空 | 远程 Ollama 地址，留空表示禁用第二端点 |

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
| `OLLAMA_SHORT_TEXT_THRESHOLD` | `600` | 短文本优先单端点阈值（已废弃，仅保留兼容性） |
| `EMBED_BATCH_SIZE` | `32` | Embedding 批处理大小 |

### 检索配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TOP_K` | `5` | 每个知识库返回的结果数量 |
| `CHUNK_STRATEGY` | `hierarchical` | 分块策略：`hierarchical`/`sentence`/`semantic` |
| `HIERARCHICAL_CHUNK_SIZES` | `2048,512,128` | 层级分块各层大小 |
| `SENTENCE_CHUNK_SIZE` | `512` | 句子分块大小 |
| `SENTENCE_CHUNK_OVERLAP` | `50` | 句子分块重叠 |
| `USE_SEMANTIC_CHUNKING` | `false` | 启用语义分块（需重建知识库） |
| `USE_AUTO_MERGING` | `false` | 启用 Auto-Merging Retriever（需知识库使用 hierarchical 分块） |
| `USE_HYBRID_SEARCH` | `false` | 启用混合搜索（向量 + BM25） |
| `HYBRID_SEARCH_ALPHA` | `0.5` | 混合搜索向量权重（0-1，1=仅向量） |
| `HYBRID_SEARCH_MODE` | `relative_score` | 混合搜索融合模式 |
| `USE_HYDE` | `false` | 启用 HyDE 查询转换 |
| `USE_QUERY_REWRITE` | `false` | 启用 Query Rewriting |
| `USE_MULTI_QUERY` | `false` | 启用多查询转换 |
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

---

## CLI 工具

除了 API，还可以用 CLI：

```bash
# 列出知识库
uv run llamaindex-study kb list

# 检索 / 问答
uv run llamaindex-study search tech_tools "Python 异步编程" -k 5
uv run llamaindex-study query tech_tools "总结当前知识库重点"

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
