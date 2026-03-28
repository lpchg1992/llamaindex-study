# LlamaIndex RAG API 文档

## 概述

基于 FastAPI 的 RAG（检索增强生成）API 服务，支持：
- **任务队列** - 异步任务提交和进度查询
- **通用文件导入** - PDF、Word、Excel、PPTX、Markdown 等
- **Zotero 文献导入** - 支持按 ID 或名称搜索收藏夹，含 OCR 扫描件检测
- **Obsidian 笔记导入** - 支持 vault 扫描，含 wiki 链接和标签处理

## 启动服务

```bash
cd /Users/luopingcheng/Documents/GitHub/llamaindex-study
poetry run python api.py
```

- 服务地址: `http://localhost:8000`
- API 文档: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## API 端点总览

### 任务队列 ⭐ 新功能

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
| POST | `/kbs` | 创建新知识库 |
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
| POST | `/kbs/{kb_id}/ingest/zotero` | Zotero 收藏夹导入 |
| POST | `/kbs/{kb_id}/ingest/obsidian` | Obsidian vault 导入 |
| POST | `/kbs/{kb_id}/rebuild` | 重建知识库 |

### Zotero 接口

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/zotero/collections` | 列出所有收藏夹 |
| GET | `/zotero/collections/search?q=` | 搜索收藏夹 |

### Obsidian 接口

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/obsidian/vaults` | 列出常见 vault 位置 |
| GET | `/obsidian/vaults/{name}` | 获取 vault 信息和文件夹 |

### 系统管理

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/admin/tables` | 列出向量表 |
| GET | `/admin/tables/{name}` | 表统计 |
| DELETE | `/admin/tables/{name}` | 删除表 |

---

## 任务队列 ⭐

### 工作流程

```
1. 提交任务 ──▶ 返回 task_id
       │
       ▼
2. 查询状态 ──▶ GET /tasks/{task_id}
       │
       ▼
3. 任务执行中 ──▶ 实时进度更新
       │
       ▼
4. 完成/失败 ──▶ 获取结果或错误信息
```

### 提交任务 `POST /tasks`

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "zotero",
    "kb_id": "my_kb",
    "params": {"collection_id": 8},
    "source": "zotero:营养饲料理论"
  }'
```

**响应**：
```json
{
  "task_id": "7695ba61",
  "task_type": "zotero",
  "status": "pending",
  "kb_id": "my_kb",
  "progress": 0,
  "current": 0,
  "total": 0,
  "message": "任务已提交",
  "created_at": 1709123456.123
}
```

### 查询任务状态 `GET /tasks/{task_id}`

```bash
curl http://localhost:8000/tasks/7695ba61
```

**响应**：
```json
{
  "task_id": "7695ba61",
  "task_type": "zotero",
  "status": "running",
  "kb_id": "zotero_test",
  "progress": 45,
  "current": 50,
  "total": 108,
  "message": "处理: 某文献标题...",
  "created_at": 1709123456.123,
  "started_at": 1709123456.125,
  "completed_at": null,
  "result": null,
  "error": null
}
```

### 任务状态

| 状态 | 说明 |
|------|------|
| `pending` | 等待执行 |
| `running` | 执行中 |
| `completed` | 已完成 |
| `failed` | 失败 |
| `cancelled` | 已取消 |

### 列出任务 `GET /tasks`

```bash
# 列出所有任务
curl http://localhost:8000/tasks

# 按知识库筛选
curl "http://localhost:8000/tasks?kb_id=zotero_nutrition"

# 按状态筛选
curl "http://localhost:8000/tasks?status=running"

# 限制数量
curl "http://localhost:8000/tasks?limit=10"
```

### 取消任务 `DELETE /tasks/{task_id}`

```bash
curl -X DELETE http://localhost:8000/tasks/7695ba61
```

---

## 异步导入接口

所有导入接口都支持 `async_mode=true` 参数，开启后返回任务 ID。

### Zotero 异步导入 `POST /kbs/{kb_id}/ingest/zotero`

```bash
curl -X POST http://localhost:8000/kbs/my_kb/ingest/zotero \
  -H "Content-Type: application/json" \
  -d '{
    "collection_name": "营养饲料理论",
    "async_mode": true
  }'
```

**响应**：
```json
{
  "status": "pending",
  "task_id": "7695ba61",
  "message": "Zotero 营养饲料理论 导入任务已提交，ID: 7695ba61",
  "source": "zotero"
}
```

**查询进度**：
```bash
curl http://localhost:8000/tasks/7695ba61
```

### Obsidian 异步导入 `POST /kbs/{kb_id}/ingest/obsidian`

```bash
curl -X POST http://localhost:8000/kbs/my_kb/ingest/obsidian \
  -H "Content-Type: application/json" \
  -d '{
    "vault_path": "/Users/me/Documents/Obsidian Vault",
    "folder_path": "工作笔记",
    "async_mode": true
  }'
```

### 通用文件异步导入 `POST /kbs/{kb_id}/ingest`

```bash
curl -X POST http://localhost:8000/kbs/my_kb/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "paths": ["/path/to/folder"],
    "recursive": true,
    "async_mode": true
  }'
```

---

## 详细说明

### 1. 创建知识库 `POST /kbs`

```bash
curl -X POST http://localhost:8000/kbs \
  -H "Content-Type: application/json" \
  -d '{
    "kb_id": "my_kb",
    "name": "我的知识库",
    "chunk_size": 512,
    "chunk_overlap": 50
  }'
```

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| kb_id | string | ✅ | - | 唯一标识 |
| name | string | ✅ | - | 显示名称 |
| chunk_size | int | ❌ | 512 | 切块大小 (128-2048) |
| chunk_overlap | int | ❌ | 50 | 切块重叠 (0-256) |

---

### 2. Zotero 收藏夹导入 `POST /kbs/{kb_id}/ingest/zotero`

支持两种方式指定收藏夹：
- **collection_id**: 直接指定收藏夹 ID
- **collection_name**: 通过名称搜索（支持模糊匹配）

```bash
# 方式1: 通过名称（推荐）
curl -X POST http://localhost:8000/kbs/my_kb/ingest/zotero \
  -H "Content-Type: application/json" \
  -d '{"collection_name": "营养饲料理论", "async_mode": true}'

# 方式2: 通过 ID
curl -X POST http://localhost:8000/kbs/my_kb/ingest/zotero \
  -H "Content-Type: application/json" \
  -d '{"collection_id": 8, "async_mode": true}'
```

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| collection_id | int | ❌ | - | 收藏夹 ID |
| collection_name | string | ❌ | - | 收藏夹名称（支持模糊匹配） |
| rebuild | bool | ❌ | false | 是否强制重建 |
| async_mode | bool | ❌ | true | 是否异步执行 |

---

### 3. Obsidian Vault 导入 `POST /kbs/{kb_id}/ingest/obsidian`

```bash
curl -X POST http://localhost:8000/kbs/my_kb/ingest/obsidian \
  -H "Content-Type: application/json" \
  -d '{
    "vault_path": "/Users/me/Documents/Obsidian Vault",
    "folder_path": "技术理论及方法",
    "async_mode": true
  }'
```

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| vault_path | string | ✅ | - | Vault 根目录路径 |
| folder_path | string | ❌ | - | 特定文件夹（可选） |
| recursive | bool | ❌ | true | 递归导入 |
| async_mode | bool | ❌ | true | 是否异步执行 |

---

### 4. 向量检索 `POST /kbs/{kb_id}/search`

```bash
curl -X POST http://localhost:8000/kbs/zotero_nutrition/search \
  -H "Content-Type: application/json" \
  -d '{"query": "后备母猪", "top_k": 5}'
```

**响应**：
```json
[
  {
    "text": "后备母猪配种体重应至少达到135公斤...",
    "score": 0.92,
    "metadata": {"source": "zotero_pdf", "title": "The gestating and lactating sow"}
  }
]
```

---

### 5. RAG 问答 `POST /kbs/{kb_id}/query`

```bash
curl -X POST http://localhost:8000/kbs/zotero_nutrition/query \
  -H "Content-Type: application/json" \
  -d '{"query": "后备母猪什么体重可以配种", "top_k": 20}'
```

**响应**：
```json
{
  "answer": "后备母猪配种体重应至少达到135公斤...",
  "source_nodes": [...],
  "total_nodes": 20
}
```

---

## Python 示例

```python
import requests

# 1. 异步提交 Zotero 导入任务
result = requests.post(
    "http://localhost:8000/kbs/my_kb/ingest/zotero",
    json={"collection_name": "营养饲料理论", "async_mode": True}
)
task_id = result.json()["task_id"]
print(f"任务 ID: {task_id}")

# 2. 轮询查询任务状态
import time
while True:
    task = requests.get(f"http://localhost:8000/tasks/{task_id}").json()
    print(f"进度: {task['progress']}% - {task['message']}")
    
    if task["status"] in ["completed", "failed", "cancelled"]:
        if task["status"] == "completed":
            print("任务完成!")
        else:
            print(f"任务失败: {task['error']}")
        break
    
    time.sleep(2)  # 每 2 秒查询一次

# 3. 同步导入（不推荐用于大任务）
result = requests.post(
    "http://localhost:8000/kbs/my_kb/ingest/zotero",
    json={"collection_name": "营养饲料理论", "async_mode": False}
)
```

---

## JavaScript 示例

```javascript
// 1. 异步提交任务
const submit = await fetch("http://localhost:8000/kbs/my_kb/ingest/zotero", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({collection_name: "营养饲料理论", async_mode: true})
});
const {task_id} = await submit.json();

// 2. 轮询查询任务状态
async function waitForTask(taskId) {
  while (true) {
    const task = await fetch(`http://localhost:8000/tasks/${taskId}`).then(r => r.json());
    console.log(`进度: ${task.progress}% - ${task.message}`);
    
    if (task.status === "completed") {
      console.log("任务完成!");
      break;
    } else if (task.status === "failed") {
      console.log(`任务失败: ${task.error}`);
      break;
    }
    
    await new Promise(r => setTimeout(r, 2000)); // 等待 2 秒
  }
}

await waitForTask(task_id);

// 3. 列出所有运行中的任务
const tasks = await fetch("http://localhost:8000/tasks?status=running").then(r => r.json());
console.log(tasks);
```

---

## 存储位置

```
/volumes/online/llamaindex/           # 向量数据
├── zotero/
│   └── zotero_nutrition/           # Zotero 文献库
├── hitech_history/                   # 高新历史项目库
└── tech_tools/                      # 技术工具库

~/.llamaindex/                        # 任务队列数据
└── tasks.db                         # SQLite 数据库
```

---

## 注意事项

1. **Ollama 服务**: 确保 `ollama serve` 在 `localhost:11434` 运行
2. **API 配额**: SiliconFlow API 有调用限制
3. **PDF OCR**: 扫描件会自动检测并调用 MinerU/doc2x 转换
4. **任务持久化**: 任务存储在 SQLite，重启后仍可查询
5. **异步模式**: 大任务建议使用异步模式，避免超时
