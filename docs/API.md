# LlamaIndex RAG API 文档

## 概述

基于 FastAPI 的 RAG（检索增强生成）API 服务，支持：
- **任务队列** - 异步任务提交和进度查询
- **WebSocket 实时推送** - 任务进度实时推送
- **增量更新** - 检测文件变化，只导入修改的文件
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
- WebSocket: `ws://localhost:8000/ws/tasks`

---

## API 端点总览

### 任务队列 + WebSocket ⭐

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/tasks` | 提交任务 |
| GET | `/tasks` | 列出任务 |
| GET | `/tasks/{task_id}` | 查询任务状态 |
| DELETE | `/tasks/{task_id}` | 取消任务 |
| WS | `/ws/tasks` | WebSocket 实时进度 |
| WS | `/ws` | WebSocket 全局广播 |

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
| POST | `/kbs/{kb_id}/search` | 向量检索（同步） |
| POST | `/kbs/{kb_id}/query` | RAG 问答（同步） |

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
| GET | `/obsidian/vaults/{name}` | 获取 vault 信息 |

---

## WebSocket 实时推送 ⭐

### 连接方式

```javascript
// 方式1: 接收所有任务更新
const ws = new WebSocket("ws://localhost:8000/ws/tasks");

// 方式2: 只接收指定任务更新
const ws = new WebSocket("ws://localhost:8000/ws/tasks?task_id=abc123");

// 方式3: 全局广播（接收所有系统消息）
const ws = new WebSocket("ws://localhost:8000/ws");

// 接收消息
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(data);
};

// 发送心跳
setInterval(() => ws.send("ping"), 30000);
```

### 推送消息格式

```json
{
  "type": "task_update",
  "task_id": "7695ba61",
  "data": {
    "task_id": "7695ba61",
    "task_type": "zotero",
    "status": "running",
    "progress": 45,
    "current": 50,
    "total": 108,
    "message": "处理: 某文献标题..."
  }
}
```

### Python WebSocket 客户端示例

```python
import asyncio
import websockets
import json

async def listen():
    uri = "ws://localhost:8000/ws/tasks"
    async with websockets.connect(uri) as ws:
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            print(f"进度: {data['data']['progress']}% - {data['data']['message']}")

asyncio.run(listen())
```

---

## 任务队列

### 工作流程

```
1. 提交任务 ──▶ 返回 task_id
       │
       ▼
2. WebSocket 连接 ──▶ 实时推送进度
       │
       ▼
3. 完成/失败 ──▶ 获取结果
```

### 提交任务 `POST /tasks`

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "zotero",
    "kb_id": "my_kb",
    "params": {"collection_id": 8}
  }'
```

### 查询任务 `GET /tasks/{task_id}`

```bash
curl http://localhost:8000/tasks/7695ba61
```

### 任务状态

| 状态 | 说明 |
|------|------|
| `pending` | 等待执行 |
| `running` | 执行中 |
| `completed` | 已完成 |
| `failed` | 失败 |
| `cancelled` | 已取消 |

---

## 增量更新 ⭐

默认启用增量更新模式：
- 计算文件 MD5 哈希（仅读取 1MB）
- 检测文件变化，只导入修改/新增的文件
- 已处理且未修改的文件自动跳过

```python
# 禁用增量更新（强制重新导入）
config = DocumentProcessorConfig(incremental=False)
```

---

## Python 完整示例

```python
import requests
import asyncio
import websockets
import json

# 1. 提交导入任务
result = requests.post(
    "http://localhost:8000/kbs/my_kb/ingest/zotero",
    json={"collection_name": "营养饲料理论"}
)
task_id = result.json()["task_id"]
print(f"任务 ID: {task_id}")

# 2. WebSocket 监听进度
async def watch_task(task_id):
    uri = f"ws://localhost:8000/ws/tasks?task_id={task_id}"
    async with websockets.connect(uri) as ws:
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            task = data["data"]
            print(f"进度: {task['progress']}% - {task['message']}")
            
            if task["status"] in ["completed", "failed"]:
                break

asyncio.run(watch_task(task_id))

# 3. 查询结果
task = requests.get(f"http://localhost:8000/tasks/{task_id}").json()
print(f"状态: {task['status']}")
if task["error"]:
    print(f"错误: {task['error']}")
```

---

## JavaScript 完整示例

```javascript
// 1. 提交任务
const submit = await fetch("http://localhost:8000/kbs/my_kb/ingest/zotero", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({collection_name: "营养饲料理论"})
});
const {task_id} = await submit.json();

// 2. WebSocket 监听
const ws = new WebSocket(`ws://localhost:8000/ws/tasks?task_id=${task_id}`);
ws.onmessage = (e) => {
  const data = JSON.parse(e.data);
  const {progress, message, status} = data.data;
  console.log(`${progress}% - ${message}`);
  
  if (status === "completed" || status === "failed") {
    ws.close();
  }
};
```

---

## 增量导入示例

```bash
# 首次导入（导入所有文件）
curl -X POST http://localhost:8000/kbs/my_kb/ingest \
  -d '{"paths": ["/path/to/docs"]}'

# 第二次导入（只导入修改/新增的文件）
curl -X POST http://localhost:8000/kbs/my_kb/ingest \
  -d '{"paths": ["/path/to/docs"]}'
# 输出: {"status": "success", "message": "成功导入 X 个文件，跳过 Y 个未变化文件"}
```

---

## 存储位置

```
/volumes/online/llamaindex/           # 向量数据
├── zotero/
├── hitech_history/
└── tech_tools/

~/.llamaindex/                        # 任务队列数据
├── tasks.db                        # SQLite 数据库
└── *.json                           # 进度记录
```

---

## 注意事项

1. **Ollama 服务**: 确保 `ollama serve` 在 `localhost:11434`
2. **WebSocket 心跳**: 建议每 30 秒发送 `ping`
3. **增量更新**: 默认启用，禁用需设置 `incremental=False`
4. **任务持久化**: 重启服务后任务状态仍可查询
