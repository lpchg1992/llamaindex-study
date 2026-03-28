# LlamaIndex RAG API 文档

## 概述

基于 FastAPI 的 RAG（检索增强生成）API 服务，支持：
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
| GET | `/zotero/collections/search?q=关键词` | 搜索收藏夹 |

### Obsidian 接口

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/obsidian/vaults` | 列出常见 vault 位置 |
| GET | `/obsidian/vaults/{vault_name}` | 获取 vault 信息和文件夹 |

### 系统管理

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/admin/tables` | 列出向量表 |
| GET | `/admin/tables/{name}` | 表统计 |
| DELETE | `/admin/tables/{name}` | 删除表 |

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
  -d '{"collection_name": "营养饲料理论"}'

# 方式2: 通过 ID
curl -X POST http://localhost:8000/kbs/my_kb/ingest/zotero \
  -H "Content-Type: application/json" \
  -d '{"collection_id": 8}'
```

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| collection_id | int | ❌ | - | 收藏夹 ID |
| collection_name | string | ❌ | - | 收藏夹名称（支持模糊匹配） |
| rebuild | bool | ❌ | false | 是否强制重建 |

**常用收藏夹名称**：

| 名称 | ID | 说明 |
|------|-----|------|
| 营养饲料理论 | 8 | 主要文献库 |
| 饲料原料 | 7 | 原料资料 |
| 猪营养专题 | 67 | 猪营养研究 |
| 鸽子料 | 17 | 鸽子饲料 |
| 低蛋白日粮 | 225 | 低蛋白研究 |

**导入内容**：
- 文献元数据（标题、作者、标签）
- 标注和笔记
- PDF 附件（含扫描件 OCR）
- Office 文档附件（Word/Excel/PPTX）

---

### 3. Obsidian Vault 导入 `POST /kbs/{kb_id}/ingest/obsidian`

```bash
# 导入整个 vault
curl -X POST http://localhost:8000/kbs/my_kb/ingest/obsidian \
  -H "Content-Type: application/json" \
  -d '{"vault_path": "/Users/me/Documents/Obsidian Vault"}'

# 导入特定文件夹
curl -X POST http://localhost:8000/kbs/my_kb/ingest/obsidian \
  -H "Content-Type: application/json" \
  -d '{
    "vault_path": "/Users/me/Documents/Obsidian Vault",
    "folder_path": "技术理论及方法",
    "recursive": true
  }'
```

**参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| vault_path | string | ✅ | - | Vault 根目录路径 |
| folder_path | string | ❌ | - | 特定文件夹（可选） |
| recursive | bool | ❌ | true | 递归导入 |
| exclude_patterns | string[] | ❌ | ["*/image/*", ...] | 排除模式 |

**导入内容**：
- Markdown 笔记
- YAML frontmatter 元数据
- Wiki 链接和标签
- PDF 附件（含扫描件 OCR）

---

### 4. 通用文件导入 `POST /kbs/{kb_id}/ingest`

```bash
curl -X POST http://localhost:8000/kbs/my_kb/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "paths": ["/path/to/folder"],
    "recursive": true,
    "exclude_patterns": ["*.xls", "*.DS_Store"]
  }'
```

**支持的文件格式**：
- PDF (.pdf) - 含扫描件检测和 OCR
- Word (.docx, .doc)
- Excel (.xlsx, .xls) - 默认排除
- PPTX (.pptx)
- Markdown (.md)
- 纯文本 (.txt)
- HTML (.html)

---

### 5. 向量检索 `POST /kbs/{kb_id}/search`

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

### 6. RAG 问答 `POST /kbs/{kb_id}/query`

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

### 7. 搜索 Zotero 收藏夹 `GET /zotero/collections/search`

```bash
# 搜索包含关键词的收藏夹
curl "http://localhost:8000/zotero/collections/search?q=%E8%90%A5%E5%85%BB"
```

**响应**：
```json
{
  "collections": [
    {"collectionID": 54, "collectionName": "产品营养水平"},
    {"collectionID": 5, "collectionName": "营养水平"},
    {"collectionID": 8, "collectionName": "营养饲料理论"}
  ],
  "message": "多个匹配结果，请用 collection_id 精确指定"
}
```

---

### 8. 列出 Obsidian Vaults `GET /obsidian/vaults`

```bash
curl http://localhost:8000/obsidian/vaults
```

**响应**：
```json
{
  "vaults": [
    {
      "path": "/Users/me/Documents/Obsidian Vault",
      "name": "Obsidian Vault",
      "note_count": 2248
    }
  ]
}
```

---

## Python 示例

```python
import requests

# 1. 创建知识库
requests.post("http://localhost:8000/kbs", json={
    "kb_id": "my_docs",
    "name": "我的文档",
    "chunk_size": 512
})

# 2. 搜索 Zotero 收藏夹
result = requests.get("http://localhost:8000/zotero/collections/search?q=营养")
print(result.json())

# 3. Zotero 导入（通过名称）
requests.post("http://localhost:8000/kbs/my_docs/ingest/zotero", json={
    "collection_name": "营养饲料理论"
})

# 4. Obsidian 导入
requests.post("http://localhost:8000/kbs/my_docs/ingest/obsidian", json={
    "vault_path": "/Users/me/Documents/Obsidian Vault",
    "folder_path": "工作笔记"
})

# 5. 通用文件导入
requests.post("http://localhost:8000/kbs/my_docs/ingest", json={
    "paths": ["/path/to/folder"],
    "recursive": True
})

# 6. RAG 问答
resp = requests.post("http://localhost:8000/kbs/my_docs/query", json={
    "query": "问题",
    "top_k": 20
})
print(resp.json()["answer"])
```

---

## JavaScript 示例

```javascript
// 搜索 Zotero 收藏夹
const search = await fetch("http://localhost:8000/zotero/collections/search?q=营养");
const result = await search.json();
console.log(result.collections);

// Zotero 导入
await fetch("http://localhost:8000/kbs/my_docs/ingest/zotero", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({collection_name: "营养饲料理论"})
});

// RAG 问答
const answer = await fetch("http://localhost:8000/kbs/my_docs/query", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({query: "问题", top_k: 20})
});
const data = await answer.json();
console.log(data.answer);
```

---

## 存储位置

```
/volumes/online/llamaindex/
├── zotero/
│   └── zotero_nutrition/     # Zotero 文献库
├── hitech_history/            # 高新历史项目库
└── {kb_id}/                 # 自定义知识库
    ├── {kb_id}.lance        # 向量数据
    └── kb_config.json        # 知识库配置
```

---

## 注意事项

1. **Ollama 服务**: 确保 `ollama serve` 在 `localhost:11434` 运行
2. **API 配额**: SiliconFlow API 有调用限制
3. **PDF OCR**: 扫描件会自动检测并调用 MinerU/doc2x 转换
4. **断点续传**: 导入过程中可中断，下次会自动继续
5. **Zotero**: 通过名称搜索时，如果多个匹配会返回错误，请用 collection_id 精确指定
