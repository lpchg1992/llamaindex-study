# Search 参数设计指南

> 📘 **相关文档**: [API 文档](./API.md) | [CLI 文档](./CLI.md) | [架构设计](./ARCHITECTURE.md) | [Query 参数指南](./QUERY_PARAM_GUIDE.md)

本文档指导客户端开发者设计 Search 组件的 UI，帮助用户正确使用纯检索系统的各项参数。

## 核心概念：路由模式 (route_mode)

Search 检索有两种路由方式：

| 模式 | route_mode 值 | 说明 | 使用场景 |
|------|--------------|------|---------|
| **指定知识库** | `"kb"` | 在指定的知识库中检索 | 明确知道问题属于哪个知识库 |
| **自动路由** | `"auto"` | 系统根据 query 内容选择相关知识库 | 不确定问题属于哪个知识库 |
| **所有知识库** | `"all"` | 检索所有知识库 | 需要全面检索时 |

---

## API 端点

| 端点 | 说明 |
|------|------|
| `POST /kbs/{kb_id}/search` | 主要端点，支持所有路由模式 |
| `POST /search` | **已废弃**，请使用上面的端点 |

---

## Search API 参数一览

### 路由参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `route_mode` | string | `"kb"` | 路由模式：`kb`(指定知识库), `auto`(自动路由), `all`(所有知识库) |
| `kb_id` | string | - | URL 路径参数，指定知识库 ID |
| `kb_ids` | string | - | 指定多个知识库（逗号分隔，仅 `route_mode=kb` 时有效） |
| `exclude` | string[] | - | 排除的知识库 ID 列表（仅 `route_mode=auto` 时有效） |

### 检索参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | string | **必填** | 检索内容 |
| `top_k` | int | 5 | 检索返回的结果数量（1-100） |

### 检索增强参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `use_auto_merging` | bool | null | 启用 Auto-Merging 检索 |

---

## 路由模式详解

### route_mode = "kb"（默认）

使用指定的知识库进行检索。

**有效参数**：
- `kb_id`（URL 路径）
- `kb_ids`（body，逗号分隔多个）

**示例**：

```json
POST /kbs/tech_tools/search
{
  "query": "Python 异步编程",
  "route_mode": "kb"
}
```

```json
POST /kbs/tech_tools/search
{
  "query": "Python 和 JavaScript 对比",
  "route_mode": "kb",
  "kb_ids": "tech_tools,programming"
}
```

---

### route_mode = "auto"（自动路由）

系统根据 query 内容自动选择相关知识库。

**有效参数**：
- `exclude`：排除的知识库 ID 列表

**示例**：

```json
POST /kbs/tech_tools/search
{
  "query": "如何配置 Nginx",
  "route_mode": "auto"
}
```

---

### route_mode = "all"（所有知识库）

检索所有知识库。

**有效参数**：
- `exclude`：排除的知识库 ID 列表

**示例**：

```json
POST /kbs/tech_tools/search
{
  "query": "项目总结",
  "route_mode": "all"
}
```

---

## 检索增强参数详解

### use_auto_merging（Auto-Merging 检索）

**作用**：利用层级分块结构，自动合并相关的小块为更大的上下文。

**前提条件**：知识库必须使用 `hierarchical` 分块策略（默认）构建。

**适用场景**：
- 需要更完整上下文的检索
- 需要理解文档结构的检索
- 长文档、深入分析类检索

**副作用**：启用后会进行额外的合并操作，延迟略有增加。

---

## UI 设计建议

### 1. 路由模式选择

建议在 UI 上明确区分三种路由模式：

```
┌─────────────────────────────────────────────────────┐
│  知识库选择                                         │
│                                                     │
│  ○ 指定知识库  ● 自动路由  ○ 所有知识库           │
│                                                     │
│  指定知识库时：                                     │
│  知识库: [tech_tools ▼]                           │
│                                                     │
│  自动路由时（可选排除）：                           │
│  排除: [____] (逗号分隔)                          │
└─────────────────────────────────────────────────────┘
```

### 2. 参数分组

将参数分为两组，UI 上分区显示：

```
┌─────────────────────────────────────────────────────┐
│  检索内容                                           │
│  [________________________] [检索按钮]              │
├─────────────────────────────────────────────────────┤
│  检索选项 (可选)                                    │
│  ☐ Auto-Merging（需层级分块知识库）               │
│  数量: [5 ▼]                                      │
└─────────────────────────────────────────────────────┘
```

### 3. 预设配置

为简化用户操作，提供预设配置：

| 预设名称 | 参数组合 | 说明 |
|----------|----------|------|
| **快速检索**（默认） | use_auto_merging=false | 通用场景，速度优先 |
| **深度检索** | use_auto_merging=true | 需要更完整上下文 |

### 4. 提示信息

```
💡 自动路由：系统根据检索内容自动选择相关知识库
⚠️ Auto-Merging 仅在知识库使用"层级分块"时有效
```

---

## API 调用示例

### 指定单库检索

```json
POST /kbs/tech_tools/search
{
  "query": "Python 异步编程的要点是什么？",
  "route_mode": "kb"
}
```

### 自动路由检索

```json
POST /kbs/tech_tools/search
{
  "query": "如何配置 Nginx 反向代理",
  "route_mode": "auto"
}
```

### 检索所有知识库

```json
POST /kbs/tech_tools/search
{
  "query": "项目总结报告",
  "route_mode": "all"
}
```

### 深度检索模式

```json
POST /kbs/tech_tools/search
{
  "query": "分析当前经济形势下的投资策略",
  "route_mode": "kb",
  "use_auto_merging": true
}
```

### 多知识库检索

```json
POST /kbs/tech_tools/search
{
  "query": "这个项目涉及哪些技术领域",
  "route_mode": "kb",
  "kb_ids": "tech_tools,programming,devops"
}
```

---

## 响应格式

```json
{
  "results": [
    {
      "text": "asyncio 是 Python 的异步编程框架...",
      "score": 0.85,
      "metadata": {
        "file_name": "async_guide.md",
        "kb_id": "tech_tools"
      }
    }
  ]
}
```

---

## Search vs Query

| 特性 | Search | Query |
|------|--------|-------|
| **功能** | 纯检索 | RAG 问答 |
| **返回值** | 检索结果片段 | 答案 + 检索来源 |
| **LLM 调用** | 无 | 有 |
| **响应速度** | 快 | 较慢 |
| **适用场景** | 仅需文档片段 | 需要生成答案 |

```
┌─────────────────────────────────────────────────────┐
│                      选择模式                       │
├─────────────────────────────────────────────────────┤
│                                                     │
│  只需文档片段 → Search（快速）                      │
│  需要生成答案 → Query（RAG）                       │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 常见问题处理

### Q: 用户不知道该选 Search 还是 Query
A: 告诉用户：
- 只需文档片段 → Search
- 需要生成答案 → Query

### Q: 检索结果不理想
A: 尝试以下组合：
- 上下文不完整 → 启用 `use_auto_merging=true`
- 检索不到 → 切换到 Query 使用 `retrieval_mode=hybrid`

### Q: 响应太慢
A: 关闭 `use_auto_merging`，使用较少的 `top_k`。

---

## 附录：CLI 参数对照

| CLI 参数 | API 参数 | 说明 |
|----------|----------|------|
| `kb_id` | URL 路径 | 指定知识库 |
| `--auto` | `route_mode="auto"` | 自动路由 |
| `--kb-ids` | `kb_ids` | 指定多个知识库 |
| `--exclude` | `exclude` | 排除的知识库 |
| `--auto-merging` | `use_auto_merging=true` | Auto-Merging |
| `--top-k` | `top_k` | 检索数量 |

---

## 附录：参数默认值来源

部分参数默认值为 `null`，表示使用服务端配置默认值。在 `.env` 中可以设置：

```env
USE_AUTO_MERGING=false
```

客户端可以省略这些参数让服务端使用默认值，也可以显式传递覆盖服务端配置。
