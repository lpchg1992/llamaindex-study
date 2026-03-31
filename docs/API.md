# LlamaIndex RAG API 文档

> ⚠️ 基于 LlamaIndex v0.14+ 构建，2026-03-30 完成升级（原 v0.10 → v0.14）

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
poetry run python api.py
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
| DELETE | `/tasks/{task_id}/delete` | 删除任务（可选 cleanup=true 清理关联数据） |

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
| POST | `/kbs/{kb_id}/rebuild` | 重建知识库 |

### 检索查询

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/kbs/{kb_id}/search` | 向量检索（指定知识库） |
| POST | `/kbs/{kb_id}/query` | RAG 问答（指定知识库） |
| POST | `/search` | 自动路由检索 |
| POST | `/query` | 自动路由 RAG 问答 |

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

---

### 文档导入

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

#### POST /kbs/{kb_id}/rebuild

重建知识库（清空后重新导入）：

```bash
curl -X POST "http://localhost:37241/kbs/tech_tools/rebuild"
```

---

### 检索查询

#### POST /kbs/{kb_id}/search

向量检索：

```bash
curl -X POST "http://localhost:37241/kbs/tech_tools/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程", "top_k": 5}'
```

```json
[
  {
    "text": "异步编程是 Python 中的重要概念...",
    "score": 0.85,
    "metadata": {"file_path": "IT/Python异步.md"}
  }
]
```

#### POST /kbs/{kb_id}/query

RAG 问答：

```bash
curl -X POST "http://localhost:37241/kbs/tech_tools/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "如何优化 Python 性能？", "mode": "vector", "top_k": 5}'
```

> **检索模式**：`mode` 参数支持 `vector`（默认）和 `hybrid`（向量+BM25融合）。混合搜索需设置环境变量 `USE_HYBRID_SEARCH=true`。

```json
{
  "response": "优化 Python 性能可以从以下几个方面入手...",
  "sources": [
    {"text": "Python 性能优化技巧...", "score": 0.85}
  ]
}
```

#### POST /search - 自动路由检索

自动选择知识库进行向量检索：

```bash
curl -X POST "http://localhost:37241/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程", "top_k": 5}'
```

```json
[
  {
    "text": "Python asyncio 使用指南...",
    "score": 0.92,
    "metadata": {"kb_id": "tech_tools"}
  }
]
```

**排除指定知识库：**

```bash
curl -X POST "http://localhost:37241/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 异步编程", "top_k": 5, "exclude": ["academic", "industry_news"]}'
```

#### POST /query - 自动路由 RAG 问答

自动选择知识库进行 RAG 问答：

```bash
curl -X POST "http://localhost:37241/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "猪饲料中氨基酸平衡的关键点是什么？", "top_k": 5}'
```

```json
{
  "response": "猪饲料中氨基酸平衡需要考虑以下关键点...",
  "sources": [
    {"kb_id": "swine_nutrition", "text": "氨基酸平衡是...", "score": 0.88}
  ]
}
```

**排除指定知识库：**

```bash
curl -X POST "http://localhost:37241/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "猪饲料中氨基酸平衡的关键点是什么？", "top_k": 5, "exclude": ["tech_tools"]}'
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
  "endpoint_stats": {
    "本地": 124,
    "远程": 124
  }
}
```

`endpoint_stats` 显示每个 Ollama 端点处理的 chunk 数量。

---

## 环境变量配置

### 存储路径配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OBSIDIAN_VAULT_ROOT` | `~/Documents/Obsidian Vault` | Obsidian Vault 根目录 |
| `PERSIST_DIR` | `~/.llamaindex/storage` | 向量存储目录 |
| `ZOTERO_STORAGE_DIR` | `~/.llamaindex/storage/zotero` | Zotero 存储目录 |

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

---

## 存储位置

```
~/.llamaindex/                    # 本地存储根目录
├── storage/                      # 向量数据
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

---

## CLI 工具

除了 API，还可以用 CLI：

```bash
# 列出知识库
poetry run llamaindex-study kb list

# 检索 / 问答
poetry run llamaindex-study search tech_tools "Python 异步编程" -k 5
poetry run llamaindex-study query tech_tools "总结当前知识库重点"

# 提交导入任务
poetry run llamaindex-study ingest obsidian tech_tools --folder-path IT
poetry run llamaindex-study ingest file tech_tools README.md

# 查看任务状态
poetry run llamaindex-study task list
poetry run llamaindex-study task show <task_id>
```
