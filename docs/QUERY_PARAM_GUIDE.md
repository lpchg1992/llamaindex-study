# Query 参数设计指南

> 📘 **相关文档**: [API 文档](./API.md) | [CLI 文档](./CLI.md) | [架构设计](./ARCHITECTURE.md)

本文档指导客户端开发者设计 Query 组件的 UI，帮助用户正确使用 RAG 系统的各项参数。

## 核心概念：路由模式 (route_mode)

RAG 查询有两种路由方式：

| 模式 | route_mode 值 | 说明 | 使用场景 |
|------|--------------|------|---------|
| **用户选择** | `"general"` | 用户在前端勾选要查询的知识库 | 明确知道问题属于哪个/哪些知识库 |
| **自动路由** | `"auto"` | 系统根据 query 内容选择相关知识库 | 不确定问题属于哪个知识库 |

---

## API 端点

| 端点 | 说明 |
|------|------|
| `POST /query` | 统一入口，支持所有路由模式 |

---

## Query API 参数一览

### 路由参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `route_mode` | string | `"general"` | 路由模式：`general`(用户选择知识库), `auto`(自动路由) |
| `kb_ids` | string | - | 指定知识库（逗号分隔，`route_mode=general` 时必填） |
| `exclude` | string[] | - | 排除的知识库 ID 列表（仅 `route_mode=auto` 时有效） |

### 检索参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | string | **必填** | 查询内容 |
| `top_k` | int | 5 | 检索返回的结果数量 |
| `retrieval_mode` | string | `"vector"` | 检索模式：`vector`(向量检索), `hybrid`(混合搜索) |

### 检索增强参数（开关类）

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `use_hyde` | bool | null | 启用 HyDE 查询转换 |
| `use_multi_query` | bool | null | 启用多查询转换 |
| `use_auto_merging` | bool | null | 启用 Auto-Merging 检索 |

### 模型参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model_id` | string | null | 使用的模型ID（如 `siliconflow/DeepSeek-V3.2`, `ollama/lfm2.5-instruct`），不填则使用默认模型 |

### 答案生成参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `response_mode` | string | null | 答案生成模式 |

---

## 路由模式详解

### route_mode = "general"（默认）

用户在前端勾选要查询的知识库。

**有效参数**：
- `kb_ids`：指定知识库 ID（逗号分隔，可指定 1 个或多个）

**示例**：

```json
POST /query
{
  "query": "Python 异步编程",
  "route_mode": "general",
  "kb_ids": "tech_tools"
}
```

```json
POST /query
{
  "query": "Python 和 JavaScript 对比",
  "route_mode": "general",
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
POST /query
{
  "query": "如何配置 Nginx",
  "route_mode": "auto"
}
```

---

## 检索增强参数详解

### 1. use_hyde（HyDE 查询转换）

**作用**：使用 LLM 生成假设性答案，再用假设性答案的 embedding 去检索真实文档。

**适用场景**：
- 查询意图模糊时
- 需要发现语义相关但字面不匹配的内容
- 学术探索、知识发现类查询

**副作用**：启用后每次查询会额外消耗 LLM 调用次数。

---

### 2. use_multi_query（多查询转换）

**作用**：使用 LLM 生成 N 个查询变体，分别检索后通过 RRF（Reciprocal Rank Fusion）融合结果。

**配置**：`MULTI_QUERY_NUM` 环境变量控制生成变体数量（默认 3 个）

**适用场景**：
- 查询可能涉及多个方面
- 需要减少检索遗漏
- 复杂问题

**副作用**：启用后会进行多次检索，延迟增加。

---

### 3. use_auto_merging（Auto-Merging 检索）

**作用**：利用层级分块结构，自动合并相关的小块为更大的上下文。

**前提条件**：知识库必须使用 `hierarchical` 分块策略（默认）构建。

**适用场景**：
- 需要更完整上下文的查询
- 需要理解文档结构的查询
- 长答案、深入分析类查询

---

### 4. retrieval_mode（检索模式）

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| `vector` | 纯向量检索（默认） | 通用场景 |
| `hybrid` | 向量检索 + BM25 关键词融合 | 查询包含专有名词、技术术语 |

---

### 5. response_mode（答案生成模式）

**作用**：控制 LLM 如何基于检索结果生成答案。

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| `compact` | 压缩检索结果后生成答案（默认） | 通用场景，平衡速度和效果 |
| `refine` | 迭代优化答案 | 需要详细、全面的答案 |
| `tree_summarize` | 构建答案树结构 | 复杂问题，需要层次化答案 |
| `simple` | 简单拼接检索结果 | 快速查看原始片段 |
| `no_text` | 仅返回检索结果，不生成答案 | 仅需检索，不需要生成 |
| `accumulate` | 累积式生成，遍历所有检索结果 | 长答案，需要覆盖所有上下文 |

---

### 6. model_id（模型选择）

**作用**：指定用于答案生成的 LLM 模型。

**模型ID格式**：`{vendor}/{model-name}`

| vendor | 示例 |
|--------|------|
| `siliconflow` | `siliconflow/DeepSeek-V3.2` |
| `ollama` | `ollama/lfm2.5-thinking:latest` |

**管理模型**：
- API: `GET/POST/DELETE /models`
- CLI: `llamaindex-study model list/add/remove/set-default`

---

## UI 设计建议

### 1. 路由模式选择

建议在 UI 上明确区分两种路由模式：

```
┌─────────────────────────────────────────────────────┐
│  知识库选择                                         │
│                                                     │
│  ○ 用户选择知识库  ● 自动路由                       │
│                                                     │
│  用户选择知识库时：                                 │
│  ☑ tech_tools                                      │
│  ☑ programming                                     │
│  ☑ devops                                         │
│                                                     │
│  自动路由时（可选排除）：                           │
│  排除: [____] (逗号分隔)                          │
└─────────────────────────────────────────────────────┘
```

### 2. 参数分组

将参数分为三组，UI 上分区显示：

```
┌─────────────────────────────────────────────────────┐
│  查询内容                                           │
│  [________________________] [查询按钮]              │
├─────────────────────────────────────────────────────┤
│  检索增强 (可选)                                    │
│  ☐ HyDE 查询转换（适合探索性查询）                 │
│  ☐ 多查询转换（适合复杂问题）                       │
│  ☐ Auto-Merging（需层级分块知识库）               │
├─────────────────────────────────────────────────────┤
│  答案生成                                           │
│  模型: [DeepSeek V3.2 (SiliconFlow) ▼]           │
│  模式: [Compact ▼]                               │
└─────────────────────────────────────────────────────┘
```

### 3. 预设配置

为简化用户操作，提供预设配置：

| 预设名称 | 参数组合 | 说明 |
|----------|----------|------|
| **智能问答**（默认） | retrieval_mode=vector, 其他关闭 | 通用场景 |
| **深度分析** | use_hyde=true, use_auto_merging=true, response_mode=tree_summarize | 复杂问题 |
| **全面检索** | retrieval_mode=hybrid | 可能涉及多方面 |
| **仅检索** | response_mode=no_text | 不生成答案 |

### 4. 模型选择

模型选择下拉列表应显示所有可用的 LLM 模型，供用户选择：

**获取模型列表**：
```bash
GET /models
```

**返回示例**：
```json
[
  {
    "id": "siliconflow/DeepSeek-V3.2",
    "vendor": "siliconflow",
    "name": "DeepSeek V3.2",
    "type": "llm",
    "is_default": true,
    "is_active": true
  },
  {
    "id": "ollama/lfm2.5-thinking:latest",
    "vendor": "ollama",
    "name": "LFM 2.5 Thinking",
    "type": "llm",
    "is_default": false,
    "is_active": true
  }
]
```

**下拉列表设计建议**：

```
┌────────────────────────────────────────────────────────┐
│  模型                                                │
│                                                        │
│  [DeepSeek V3.2 (SiliconFlow) ▼]                    │
│                                                        │
│  ├─ SiliconFlow                                      │
│  │   └─ DeepSeek V3.2 (默认)                       │
│  │                                              │
│  └─ Ollama                                           │
│      └─ LFM 2.5 Thinking                            │
│      └─ LFM 2.5 Instruct                           │
└────────────────────────────────────────────────────────┘
```

**分组显示**：按 vendor 分组显示模型列表，提升用户体验。

**默认值**：以下拉列表应默认选中 `is_default=true` 的模型。

**实现示例（JavaScript）**：

```javascript
// 获取模型列表
const response = await fetch('/models');
const models = await response.json();

// 过滤 LLM 类型且激活的模型
const llmModels = models.filter(m => m.type === 'llm' && m.is_active);

// 按 vendor 分组
const grouped = llmModels.reduce((acc, model) => {
  const vendor = model.vendor;
  if (!acc[vendor]) acc[vendor] = [];
  acc[vendor].push(model);
  return acc;
}, {});

// 渲染下拉列表
const select = document.getElementById('model-select');
Object.entries(grouped).forEach(([vendor, models]) => {
  const group = document.createElement('optgroup');
  group.label = vendor === 'siliconflow' ? 'SiliconFlow' : 'Ollama';
  models.forEach(model => {
    const option = document.createElement('option');
    option.value = model.id;
    option.textContent = `${model.name}${model.is_default ? ' (默认)' : ''}`;
    group.appendChild(option);
  });
  select.appendChild(group);
});
```

### 5. 提示信息

```
💡 自动路由：系统根据问题内容自动选择相关知识库
⚠️ Auto-Merging 仅在知识库使用"层级分块"时有效
⚠️ 启用 HyDE/多查询会增加响应时间
```

---

## API 调用示例

### 指定单库查询

```json
POST /query
{
  "query": "Python 异步编程的要点是什么？",
  "kb_ids": "tech_tools"
}
```

### 自动路由查询

```json
POST /query
{
  "query": "如何配置 Nginx 反向代理",
  "route_mode": "auto"
}
```

### 多库查询

```json
POST /query
{
  "query": "项目总结报告",
  "kb_ids": "tech_tools,programming,devops"
}
```

### 深度分析模式

```json
POST /query
{
  "query": "分析当前经济形势下的投资策略",
  "kb_ids": "tech_tools",
  "use_hyde": true,
  "use_auto_merging": true,
  "response_mode": "tree_summarize"
}
```

### 全面检索模式

```json
POST /query
{
  "query": "这个项目涉及哪些技术领域",
  "kb_ids": "tech_tools,programming",
  "use_multi_query": true,
  "retrieval_mode": "hybrid"
}
```

### 指定模型查询

```json
POST /query
{
  "query": "如何优化 Python 性能",
  "kb_ids": "tech_tools",
  "model_id": "ollama/lfm2.5-thinking:latest"
}
```

---

## 响应格式

```json
{
  "response": "Python 异步编程的核心要点包括...",
  "sources": [
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

## 常见问题处理

### Q: 用户不知道该选什么参数
A: 默认使用"智能问答"预设即可，大多数场景效果良好。

### Q: 查询结果不理想
A: 尝试以下组合：
- 检索不到 → 启用 `retrieval_mode=hybrid`
- 上下文不完整 → 启用 `use_auto_merging=true`
- 答案不相关 → 启用 `use_hyde=true` 重新检索

### Q: 响应太慢
A: 关闭 `use_hyde`、`use_auto_merging`，使用默认 `compact` 模式。

---

## 附录：CLI 参数对照

| CLI 参数 | API 参数 | 说明 |
|----------|----------|------|
| `--auto` | `route_mode="auto"` | 自动路由 |
| `--kb-ids` | `kb_ids` | 指定知识库（逗号分隔） |
| `--exclude` | `exclude` | 排除的知识库 |
| `--hyde` | `use_hyde=true` | 显式开启 HyDE 查询转换 |
| `--no-hyde` | `use_hyde=false` | 显式关闭 HyDE 查询转换 |
| `--multi-query` | `use_multi_query=true` | 显式开启多查询转换 |
| `--no-multi-query` | `use_multi_query=false` | 显式关闭多查询转换 |
| `--num-multi-queries` | `num_multi_queries=N` | 多查询变体数量 |
| `--auto-merging` | `use_auto_merging=true` | 显式开启 Auto-Merging |
| `--no-auto-merging` | `use_auto_merging=false` | 显式关闭 Auto-Merging |
| `--response-mode` | `response_mode` | 答案生成模式 |
| `--model-id` | `model_id` | 指定使用的模型ID |
| `--embed-model-id` | `embed_model_id` | 指定 Embedding 模型ID |

---

## 附录：参数默认值来源

部分参数默认值为 `null`，表示使用服务端配置默认值。在 `.env` 中可以设置：

```env
USE_HYDE=false
USE_MULTI_QUERY=false
MULTI_QUERY_NUM=3
USE_AUTO_MERGING=false
USE_RERANKER=true
RESPONSE_MODE=compact
RETRIEVAL_MODE=vector
```

客户端可以省略这些参数让服务端使用默认值，也可以显式传递覆盖服务端配置。
