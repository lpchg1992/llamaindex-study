# LlamaIndex RAG API 文档

## 概述

基于 FastAPI 的 RAG（检索增强生成）API 服务，支持：

- **并行多端点 Ollama** - 本地 + 远程同时处理，大幅提升导入效率
- **任务队列** - 异步任务提交和实时进度查询
- **增量同步** - 基于文件哈希检测变更
- **WebSocket 推送** - 任务进度实时推送
- **Obsidian 笔记导入** - 支持 vault 扫描
- **Zotero 文献导入** - 支持按 ID 或名称搜索收藏夹

## 启动服务

```bash
cd ~/文档/GitHub/llamaindex-study
poetry run python api.py
```

- 服务地址: `http://localhost:8000`
- API 文档: `http://localhost:8000/docs`
- WebSocket: `ws://localhost:8000/ws/tasks`

---

## 核心功能

### 并行多端点 Ollama

导入任务使用**本地 + 远程 Ollama 同时处理**：

```
文件列表 (100个)
    ├── 本地 Ollama ──→ 50 个文件
    └── 远程 Ollama ──→ 50 个文件
```

配置文件路径：
- 本地: `http://localhost:11434`
- 远程: `http://192.168.31.169:11434`

### 任务队列

任务提交后立即返回 `task_id`，后台异步执行：

```bash
# 提交任务
curl -X POST "http://localhost:8000/kbs/tech_tools/ingest/obsidian"

# 返回
{"task_id": "abc12345", "status": "pending"}

# 查询状态
curl "http://localhost:8000/tasks/abc12345"

# 返回
{"task_id": "abc12345", "status": "completed", 
 "progress": 100, "result": {"files": 26, "nodes": 248}}
```

---

## API 端点总览

### 健康检查

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/health` | 服务健康检查 |

### 任务队列

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/tasks` | 提交任务 |
| GET | `/tasks` | 列出任务 |
| GET | `/tasks/{task_id}` | 查询任务状态 |
| DELETE | `/tasks/{task_id}` | 取消任务 |

### 知识库管理

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/kbs` | 列出所有知识库 |
| GET | `/kbs/{kb_id}` | 获取知识库详情 |
| DELETE | `/kbs/{kb_id}` | 删除知识库 |

### 文档导入（并行处理）

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/kbs/{kb_id}/ingest/obsidian` | Obsidian 导入（本地+远程并行） |
| POST | `/kbs/{kb_id}/ingest/zotero` | Zotero 导入 |
| POST | `/kbs/{kb_id}/rebuild` | 重建知识库 |

### 检索查询

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/kbs/{kb_id}/search` | 向量检索 |
| POST | `/kbs/{kb_id}/query` | RAG 问答 |

### Obsidian

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/obsidian/vaults` | 列出 vault 位置 |
| GET | `/obsidian/mappings` | 知识库映射配置 |
| POST | `/obsidian/import-all` | 全库分类导入 |

### 管理

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/admin/tables` | 列出向量表 |
| GET | `/admin/tables/{kb_id}` | 表统计 |

---

## 详细接口

### 健康检查

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok", "service": "llamaindex-rag-api", "version": "3.1.0"}
```

---

### 任务队列

#### POST /tasks - 提交任务

```bash
curl -X POST http://localhost:8000/tasks \
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
curl http://localhost:8000/tasks/abc12345
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
    "nodes": 248
  }
}
```

#### GET /tasks - 列出任务

```bash
curl "http://localhost:8000/tasks?status=running&limit=10"
```

---

### 文档导入

#### POST /kbs/{kb_id}/ingest/obsidian

Obsidian vault 导入（本地+远程并行处理）：

```bash
curl -X POST "http://localhost:8000/kbs/tech_tools/ingest/obsidian" \
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
curl -X POST "http://localhost:8000/kbs/swine_nutrition/ingest/zotero" \
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
curl -X POST "http://localhost:8000/kbs/tech_tools/rebuild"
```

---

### 检索查询

#### POST /kbs/{kb_id}/search

向量检索：

```bash
curl -X POST "http://localhost:8000/kbs/tech_tools/search" \
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
curl -X POST "http://localhost:8000/kbs/tech_tools/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "如何优化 Python 性能？", "mode": "hybrid", "top_k": 5}'
```

```json
{
  "response": "优化 Python 性能可以从以下几个方面入手...",
  "sources": [
    {"text": "Python 性能优化技巧...", "score": 0.85}
  ]
}
```

---

## WebSocket 实时推送

### 连接

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/tasks");
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
    "message": "[本地] 20/50"
  }
}
```

---

## 完整示例

### Python

```python
import requests
import time

BASE = "http://localhost:8000"

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

# 3. 搜索
r = requests.post(f"{BASE}/kbs/tech_tools/search",
    json={"query": "Python", "top_k": 5})
print(r.json())
```

### cURL

```bash
# 提交任务
curl -X POST "http://localhost:8000/kbs/tech_tools/ingest/obsidian" \
  -H "Content-Type: application/json" \
  -d '{"recursive": true}'

# 查询状态
curl "http://localhost:8000/tasks/{task_id}"

# 搜索
curl -X POST "http://localhost:8000/kbs/tech_tools/search" \
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

## 存储位置

```
/Volumes/online/llamaindex/           # 向量数据
~/.llamaindex/                       # SQLite 数据库
├── project.db                      # 项目数据
└── tasks.db                        # 任务队列
```

---

## CLI 工具

除了 API，还可以用 CLI：

```bash
# 列出知识库
poetry run python -m kb.ingest_vdb --list

# 查看变更
poetry run python -m kb.ingest_vdb --show-changes

# 提交导入任务
poetry run python -m kb.ingest_vdb --kb tech_tools

# 查看任务状态
poetry run python -m kb.ingest_vdb --tasks
```
