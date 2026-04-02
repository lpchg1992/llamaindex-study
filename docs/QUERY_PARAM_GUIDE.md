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
- `model_id`：指定路由和答案生成使用的模型（不填则使用默认 Ollama 模型）

**示例**：

```json
POST /query
{
  "query": "如何配置 Nginx",
  "route_mode": "auto"
}
```

```json
POST /query
{
  "query": "如何配置 Nginx",
  "route_mode": "auto",
  "model_id": "ollama/lfm2.5-instruct:1.2b"
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

### 1. 整体页面布局

建议采用现代化的单页布局，左侧导航 + 右侧内容区：

```
┌──────────────────────────────────────────────────────────────────────┐
│  💬 RAG 问答                                          [⚙️] [❓]     │
├────────────┬─────────────────────────────────────────────────────────┤
│            │                                                         │
│  📊 Dashboard│  ┌─────────────────────────────────────────────────┐ │
│  📚 知识库  │  │  💡 提示：仅需文档片段用 Search，需要答案用 Query  │ │
│  🔍 检索   │  └─────────────────────────────────────────────────┘ │
│  💬 问答   │                                                        │
│  📥 导入   │  ┌─────────────────────────────────────────────────┐ │
│  📋 任务   │  │  查询内容                                         │ │
│  ⚙️ 设置   │  │  ┌───────────────────────────────────────────┐ │ │
│            │  │  │ 小猪腹泻应该怎么治疗？                     │ │ │
│            │  │  └───────────────────────────────────────────┘ │ │
│            │  │                                                   │ │
│            │  │  知识库: [全部 ▼]   [🔍 检索] [🧠 推理]          │ │
│            │  └─────────────────────────────────────────────────┘ │
│            │                                                        │
│            │  ┌─ 答案 ─────────────────────────────────────────┐  │
│            │  │ 根据《猪病学》第三章内容，小猪腹泻多为...         │  │
│            │  │                                                  │  │
│            │  │ [相关文档 1]  [相关文档 2]  [相关文档 3]        │  │
│            │  └────────────────────────────────────────────────┘  │
└────────────┴─────────────────────────────────────────────────────────┘
```

**技术栈推荐**：
| 层级 | 推荐方案 | 理由 |
|------|----------|------|
| 框架 | React 18 + TypeScript | 生态丰富，类型安全 |
| 路由 | React Router v6 | 标准 SPA 路由 |
| 状态 | Zustand / Jotai | 轻量、比 Redux 简单 |
| UI 库 | shadcn/ui + Tailwind | 现代、可定制、copy-paste 友好 |
| HTTP | TanStack Query | 请求缓存、自动重试 |
| 实时 | 原生 WebSocket | 项目已有 WebSocket 支持 |

---

### 2. 路由模式选择组件

建议使用 Segmented Control（分段控制器）明确区分两种路由模式：

```
┌─────────────────────────────────────────────────────────────────────┐
│  知识库选择                                                          │
│                                                                      │
│  ┌─────────────────┐  ┌─────────────────┐                          │
│  │ ○ 用户选择知识库 │  │ ● 自动路由      │   ← Segmented Control  │
│  └─────────────────┘  └─────────────────┘                          │
│                                                                      │
│  ─────────────────────────────────────────────────────────────────  │
│                                                                      │
│  用户选择知识库时：                          自动路由时：            │
│  ┌──────────────────────────────┐          ┌──────────────────────┐ │
│  │ 🔍 搜索知识库...            │          │ 排除的知识库:         │ │
│  │                              │          │ ┌──────────────────┐ │ │
│  │ ☑ ✅ zotero_nutrition      │          │ │ tech_tools    ×  │ │ │
│  │     234 篇 · 猪饲料配方     │          │ │ devops        ×  │ │ │
│  │                              │          │ └──────────────────┘ │ │
│  │ ☑ 🔲 HTE_history           │          │ [添加排除...]        │ │
│  │     156 篇 · 历史资料       │          └──────────────────────┘ │
│  │                              │                                      │
│  │ ☐ 🔲 programming           │                                      │
│  │     89 篇 · 编程笔记       │                                      │
│  └──────────────────────────────┘                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**设计要点**：
- 使用 Checkbox 列表供用户多选知识库
- 显示每个知识库的文档数量和简介
- 支持搜索过滤
- 自动路由模式下显示排除的知识库标签（Tag）

**实现示例（React + shadcn/ui）**：

```tsx
// 路由模式切换
<SegmentedControl
  value={routeMode}
  onValueChange={setRouteMode}
  options={[
    { value: 'general', label: '用户选择知识库' },
    { value: 'auto', label: '自动路由' },
  ]}
/>

// 知识库多选列表
<div className="space-y-2">
  <Input placeholder="🔍 搜索知识库..." />
  {filteredKBs.map(kb => (
    <div key={kb.id} className="flex items-center gap-3 p-3 border rounded-lg hover:bg-accent">
      <Checkbox
        checked={selectedKBs.includes(kb.id)}
        onCheckedChange={(checked) => toggleKB(kb.id, checked)}
      />
      <div className="flex-1">
        <div className="font-medium">{kb.name}</div>
        <div className="text-sm text-muted-foreground">
          {kb.doc_count} 篇 · {kb.description}
        </div>
      </div>
    </div>
  ))}
</div>

// 排除标签（自动路由模式）
{token !== 'general' && (
  <div className="flex flex-wrap gap-2">
    {excludedKBs.map(kb => (
      <Badge key={kb.id} variant="secondary" className="gap-1">
        {kb.name}
        <X className="w-3 h-3 cursor-pointer" onClick={() => removeExcluded(kb.id)} />
      </Badge>
    ))}
    <Button variant="outline" size="sm">+ 添加排除</Button>
  </div>
)}
```

---

### 3. 参数配置面板

建议使用折叠面板（Accordion）对参数分组，提升界面整洁度：

```
┌─────────────────────────────────────────────────────────────────────┐
│  ⚡ 检索增强选项                                             [🔽 展开] │
│  ─────────────────────────────────────────────────────────────────  │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 🧠 HyDE 查询转换                              [ 开关  ]    │    │
│  │    适合探索性查询，可能增加响应时间                          │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 📝 多查询转换                                  [ 开关  ]    │    │
│  │    生成多个查询变体，减少检索遗漏                            │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 🔄 Auto-Merging 检索                          [ 开关  ]    │    │
│  │    需知识库使用层级分块策略                                  │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  📊 检索模式:  ┌────────────┐ ┌────────────┐                     │
│                │ ● 向量检索  │ │ ○ 混合搜索  │                     │
│                └────────────┘ └────────────┘                     │
└─────────────────────────────────────────────────────────────────────┘
```

**设计要点**：
- 使用 Switch 组件代替 Checkbox，更现代化
- 每个开关显示描述文字和警告图标
- 检索模式使用 Radio Group

---

### 4. 模型与生成模式选择

建议将模型选择和答案生成模式放在工具条中：

```
┌─────────────────────────────────────────────────────────────────────┐
│  🤖 模型: [DeepSeek V3.2 (SiliconFlow) ▼]                          │
│                                                                      │
│  📝 生成模式: [Compact (默认) ▼]                                    │
│     └─ Compact · Refine · Tree Summarize · Simple · No Text       │
└─────────────────────────────────────────────────────────────────────┘
```

**分组下拉列表设计**：

```
┌────────────────────────────────────────────────────────┐
│  模型                                                │
│                                                        │
│  [🔍 搜索模型...]                                    │
│  ─────────────────────────────────────────────────── │
│  ├─ 💰 SiliconFlow                                  │
│  │   └─ DeepSeek V3.2                    ✓ 默认     │
│  │   └─ Qwen2.5 72B                                │
│  │                                                  │
│  ├─ 🖥️ Ollama (本地)                               │
│  │   └─ LFM 2.5 Thinking                          │
│  │   └─ LFM 2.5 Instruct                          │
│  │                                                  │
│  └─ 🏠 Ollama HomePC                               │
│      └─ bge-m3 (Embedding)                         │
└────────────────────────────────────────────────────────┘
```

**实现示例**：

```tsx
// 模型选择分组下拉
<Popover>
  <PopoverTrigger asChild>
    <Button variant="outline" className="w-64 justify-start">
      {selectedModel ? (
        <>
          <Badge className="mr-2">{getVendorIcon(selectedModel.vendor)}</Badge>
          {selectedModel.name}
        </>
      ) : (
        "选择模型..."
      )}
    </Button>
  </PopoverTrigger>
  <PopoverContent className="w-80 p-0">
    <Command>
      <CommandInput placeholder="搜索模型..." />
      <CommandList>
        {Object.entries(groupedModels).map(([vendor, models]) => (
          <CommandGroup key={vendor} heading={vendor}>
            {models.map(model => (
              <CommandItem
                key={model.id}
                value={model.id}
                onSelect={() => setSelectedModel(model)}
              >
                <Check
                  className={cn(
                    "mr-2 h-4 w-4",
                    selectedModel?.id === model.id ? "opacity-100" : "opacity-0"
                  )}
                />
                <span>{model.name}</span>
                {model.is_default && (
                  <Badge variant="secondary" className="ml-2">默认</Badge>
                )}
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
      </CommandList>
    </Command>
  </PopoverContent>
</Popover>
```

---

### 5. 预设配置（快捷模式）

提供预设配置卡片，用户可一键切换：

```
┌─────────────────────────────────────────────────────────────────────┐
│  预设模式                                                            │
│                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │   🚀        │  │   🔬        │  │   📚        │  │   📄     │ │
│  │  智能问答   │  │   深度分析   │  │   全面检索   │  │   仅检索  │ │
│  │  (默认)    │  │             │  │             │  │          │ │
│  │  ⭐⭐⭐    │  │   ⭐⭐⭐⭐  │  │   ⭐⭐⭐    │  │   ⭐⭐   │ │
│  │  速度优先  │  │   质量优先   │  │   平衡      │  │   快速查看│ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────┘ │
│                                                                      │
│  当前: 智能问答 (默认)                                               │
│  参数: 向量检索 + Compact 模式                                       │
└─────────────────────────────────────────────────────────────────────┘
```

**预设参数对照**：

| 预设 | retrieval_mode | use_hyde | use_multi_query | use_auto_merging | response_mode |
|------|----------------|----------|-----------------|-------------------|---------------|
| **🚀 智能问答** | vector | false | false | false | compact |
| **🔬 深度分析** | vector | true | false | true | tree_summarize |
| **📚 全面检索** | hybrid | false | true | false | compact |
| **📄 仅检索** | vector | false | false | false | no_text |

---

### 6. 查询结果展示

结果区域应包含答案和引用来源：

```
┌─────────────────────────────────────────────────────────────────────┐
│  📖 回答                                        [📋 复制] [🔄 重答] │
│  ─────────────────────────────────────────────────────────────────  │
│                                                                      │
│  根据《猪病学》第三章内容，小猪腹泻多为消化不良或病原感染所致...       │
│                                                                      │
│  ─────────────────────────────────────────────────────────────────  │
│                                                                      │
│  📚 引用来源 (3)                                        [显示设置 ▼]  │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 1. 📄 猪病学.pdf                              相关度: 92%   │    │
│  │    "...小猪腹泻的治疗方法包括：1. 调整饲料配方..."           │    │
│  │    [查看详情]                                                │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 2. 📄 饲料配方.doc                            相关度: 87%   │    │
│  │    "...腹泻期间应减少蛋白质含量，增加纤维素..."               │    │
│  │    [查看详情]                                                │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 3. 📄 养殖手册.md                              相关度: 81%   │    │
│  │    "...预防腹泻的关键是保持饲料新鲜..."                       │    │
│  │    [查看详情]                                                │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**设计要点**：
- 答案区域使用 Markdown 渲染
- 引用卡片显示文件类型图标、名称、相关度分数
- 支持展开查看完整引用片段
- 提供复制和重新回答按钮

**实现示例**：

```tsx
// 结果展示
<div className="space-y-4">
  {/* 答案区域 */}
  <Card>
    <CardHeader className="flex flex-row items-center justify-between">
      <CardTitle className="text-lg font-medium">📖 回答</CardTitle>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={copyAnswer}>
          <Copy className="w-4 h-4 mr-1" /> 复制
        </Button>
        <Button variant="outline" size="sm" onClick={rerunQuery}>
          <RefreshCw className="w-4 h-4 mr-1" /> 重答
        </Button>
      </div>
    </CardHeader>
    <CardContent>
      <ReactMarkdown className="prose prose-sm max-w-none">
        {response}
      </ReactMarkdown>
    </CardContent>
  </Card>

  {/* 引用来源 */}
  <Card>
    <CardHeader>
      <CardTitle className="text-lg">
        📚 引用来源 ({sources.length})
      </CardTitle>
    </CardHeader>
    <CardContent className="space-y-3">
      {sources.map((source, index) => (
        <div
          key={index}
          className="p-4 border rounded-lg hover:bg-accent/50 transition-colors"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <FileIcon className="w-4 h-4 text-muted-foreground" />
              <span className="font-medium">{source.metadata.file_name}</span>
            </div>
            <Badge variant="outline">
              相关度: {Math.round(source.score * 100)}%
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground line-clamp-2">
            {source.text}
          </p>
          <Button variant="ghost" size="sm" className="mt-2 h-8">
            查看详情
          </Button>
        </div>
      ))}
    </CardContent>
  </Card>
</div>
```

---

### 7. 提示信息与帮助

使用 Tooltip 和 Alert 组件提供上下文帮助：

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  💡 提示组件示例                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ ℹ️ 自动路由：系统根据问题内容自动选择相关知识库               │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ⚠️ 警告组件示例                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ ⚠️ Auto-Merging 仅在知识库使用"层级分块"时有效              │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ❌ 错误组件示例                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ ❌ 请求失败，请检查网络连接或重试                             │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**设计要点**：
- 警告信息使用黄色/橙色标识
- 错误信息使用红色标识
- 每个参数旁边使用 `?` 图标触发 Tooltip 解释

---

### 8. 移动端适配

移动端采用底部标签栏替代侧边导航：

```
┌─────────────────────────────┐
│  💬 RAG 问答          [⚙️]  │
├─────────────────────────────┤
│                             │
│  ┌───────────────────────┐  │
│  │ 小猪腹泻应该怎么治疗？ │  │
│  └───────────────────────┘  │
│                             │
│  [🔍 检索] [🧠 推理]        │
│                             │
│  ─────────────────────────  │
│                             │
│  📖 回答                    │
│  根据《猪病学》第三章...     │
│                             │
│  ┌───────────────────────┐  │
│  │ 猪病学.pdf  92%   ▶  │  │
│  └───────────────────────┘  │
│  ┌───────────────────────┐  │
│  │ 饲料配方.doc  87% ▶  │  │
│  └───────────────────────┘  │
│                             │
├─────────────────────────────┤
│ [🏠] [📚] [🔍] [💬] [📋]  │  ← 底部 Tab Bar
└─────────────────────────────┘
```

**移动端优化**：
- 参数面板改为底部抽屉（Bottom Sheet）
- 结果卡片改为垂直列表
- 使用原生滑动返回

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
