# Search 参数设计指南

> 📘 **相关文档**: [API 文档](./API.md) | [CLI 文档](./CLI.md) | [架构设计](./ARCHITECTURE.md) | [Query 参数指南](./QUERY_PARAM_GUIDE.md)

本文档指导客户端开发者设计 Search 组件的 UI，帮助用户正确使用纯检索系统的各项参数。

## 核心概念：路由模式 (route_mode)

Search 检索有两种路由方式：

| 模式 | route_mode 值 | 说明 | 使用场景 |
|------|--------------|------|---------|
| **用户选择** | `"general"` | 用户在前端勾选要检索的知识库 | 明确知道问题属于哪个/哪些知识库 |
| **自动路由** | `"auto"` | 系统根据 query 内容选择相关知识库 | 不确定问题属于哪个知识库 |

---

## API 端点

| 端点 | 说明 |
|------|------|
| `POST /search` | 统一入口，支持所有路由模式 |

---

## Search API 参数一览

### 路由参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `route_mode` | string | `"general"` | 路由模式：`general`(用户选择知识库), `auto`(自动路由) |
| `kb_ids` | string | - | 指定知识库（逗号分隔，`route_mode=general` 时必填） |
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

### 模型参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model_id` | string | null | 使用的模型ID（如 `siliconflow/DeepSeek-V3.2`, `ollama/lfm2.5-instruct`），不填则使用默认模型（Ollama） |
| `embed_model_id` | string | null | 使用的 Embedding 模型ID（如 `ollama/bge-m3:latest`） |

---

## 路由模式详解

### route_mode = "general"（默认）

用户在前端勾选要检索的知识库。

**有效参数**：
- `kb_ids`：指定知识库 ID（逗号分隔，可指定 1 个或多个）

**示例**：

```json
POST /search
{
  "query": "Python 异步编程",
  "kb_ids": "tech_tools"
}
```

```json
POST /search
{
  "query": "Python 和 JavaScript 对比",
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
POST /search
{
  "query": "如何配置 Nginx",
  "route_mode": "auto"
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

### 1. 整体页面布局

建议采用现代化的单页布局，左侧导航 + 右侧内容区：

```
┌──────────────────────────────────────────────────────────────────────┐
│  🔍 文档检索                                          [⚙️] [❓]     │
├────────────┬─────────────────────────────────────────────────────────┤
│            │                                                         │
│  📊 Dashboard│  ┌─────────────────────────────────────────────────┐ │
│  📚 知识库  │  │  💡 提示：仅需文档片段用 Search，需要答案用 Query  │ │
│  🔍 检索   │  └─────────────────────────────────────────────────┘ │
│  💬 问答   │                                                        │
│  📥 导入   │  ┌─────────────────────────────────────────────────┐ │
│  📋 任务   │  │  检索内容                                         │ │
│  ⚙️ 设置   │  │  ┌───────────────────────────────────────────┐ │ │
│            │  │  │ Python 异步编程                          │ │ │
│            │  │  └───────────────────────────────────────────┘ │ │
│            │  │                                                   │ │
│            │  │  知识库: [全部 ▼]   数量: [10 ▼]  [🔍 检索]    │ │
│            │  └─────────────────────────────────────────────────┘ │
│            │                                                        │
│            │  ┌─ 结果 (23) ─────────────────────────────────────┐  │
│            │  │                                                   │  │
│            │  │  📄 async_guide.md                   相关度: 95% │  │
│            │  │  "...asyncio 是 Python 的异步编程框架..."        │  │
│            │  │  tech_tools · 2024-01-15                        │  │
│            │  │                                                   │  │
│            │  │  📄 async_tutorial.pdf                 相关度: 89% │  │
│            │  │  "...async/await 关键字用于定义协程..."          │  │
│            │  │  programming · 2024-02-20                      │  │
│            │  │                                                   │  │
│            │  └──────────────────────────────────────────────────┘  │
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
│  用户选择知识库时：                          自动路由时：              │
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

### 3. 检索工具栏

建议将检索选项放在工具栏中，紧凑排列：

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  🔍 检索内容                                                          │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 🔍 搜索文档...                                    [🗑️ 清空] │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ 知识库: [全部 ▼]  │  数量: [10 ▼]  │  ☐ Auto-Merging          │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│                              [🔍 检索]  [⚡ 快速检索]                 │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**设计要点**：
- 检索输入框宽度占满，支持实时搜索
- 知识库选择、数量选择使用 Select 下拉
- 启用 Auto-Merging 使用 Switch 组件
- 提供「快速检索」和「深度检索」两种模式按钮

---

### 4. 检索结果卡片

结果以卡片列表形式展示，每个结果包含文件名、摘要、相关度等信息：

```
┌─────────────────────────────────────────────────────────────────────┐
│  📊 检索结果                                        (23 个结果)      │
│  ─────────────────────────────────────────────────────────────────  │
│  排序: [相关度 ▼]  [时间 ▼]  [名称 ▼]                                │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 📄 async_guide.md                               相关度: 95%   │    │
│  │                                                                │    │
│  │ ...asyncio 是 Python 的异步编程框架，提供协程和任务调度功能...  │    │
│  │                                                                │    │
│  │ 🏷️ tech_tools · 📅 2024-01-15 · 📝 2.3KB                     │    │
│  │                                                                │    │
│  │ [查看文档]  [复制链接]  [⭕ 相关片段]                          │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 📄 async_tutorial.pdf                             相关度: 89%   │    │
│  │                                                                │    │
│  │ ...async/await 关键字用于定义协程，asyncio.run() 用于运行...   │    │
│  │                                                                │    │
│  │ 🏷️ programming · 📅 2024-02-20 · 📝 156KB                    │    │
│  │                                                                │    │
│  │ [查看文档]  [复制链接]  [⭕ 相关片段]                          │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ... 更多结果 ...                                                     │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                         < 1 2 3 ... 5 >                     │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**设计要点**：
- 卡片显示文件名、相关度分数、摘要片段
- 元信息行显示知识库名称、日期、大小
- 操作按钮组：查看文档、复制链接、查看相关片段
- 支持排序和分页

**实现示例**：

```tsx
// 结果卡片组件
<div className="space-y-4">
  {/* 工具栏 */}
  <div className="flex items-center gap-4 flex-wrap">
    <Select value={topK} onValueChange={setTopK}>
      <SelectTrigger className="w-24">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {[5, 10, 20, 50, 100].map(n => (
          <SelectItem key={n} value={n}>{n} 条</SelectItem>
        ))}
      </SelectContent>
    </Select>

    <Select value={sortBy} onValueChange={setSortBy}>
      <SelectTrigger className="w-28">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="score">相关度</SelectItem>
        <SelectItem value="time">时间</SelectItem>
        <SelectItem value="name">名称</SelectItem>
      </SelectContent>
    </Select>

    <div className="flex items-center gap-2">
      <span className="text-sm text-muted-foreground">Auto-Merging</span>
      <Switch
        checked={useAutoMerging}
        onCheckedChange={setUseAutoMerging}
      />
    </div>
  </div>

  {/* 结果数量 */}
  <div className="text-sm text-muted-foreground">
    找到 {total} 个结果
  </div>

  {/* 结果列表 */}
  <div className="space-y-3">
    {results.map((result, index) => (
      <Card key={index} className="hover:shadow-md transition-shadow">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileIcon className="w-4 h-4" />
              <span className="font-medium">{result.metadata.file_name}</span>
            </div>
            <Badge variant={getScoreVariant(result.score)}>
              {Math.round(result.score * 100)}%
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground line-clamp-2 mb-3">
            {result.text}
          </p>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <Tag className="w-3 h-3" />
              {result.metadata.kb_id}
            </span>
            <span className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {result.metadata.date}
            </span>
          </div>
          <div className="flex gap-2 mt-3">
            <Button variant="outline" size="sm">
              查看文档
            </Button>
            <Button variant="ghost" size="sm">
              相关片段
            </Button>
          </div>
        </CardContent>
      </Card>
    ))}
  </div>

  {/* 分页 */}
  <div className="flex justify-center">
    <Pagination>
      <PaginationContent>
        <PaginationItem>
          <PaginationPrevious href="#" />
        </PaginationItem>
        {[1, 2, 3, '...', 5].map((page, i) => (
          <PaginationItem key={i}>
            <PaginationLink href="#" isActive={page === 1}>
              {page}
            </PaginationLink>
          </PaginationItem>
        ))}
        <PaginationItem>
          <PaginationNext href="#" />
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  </div>
</div>
```

---

### 5. 预设配置（快捷模式）

提供预设配置按钮，一键切换检索模式：

```
┌─────────────────────────────────────────────────────────────────────┐
│  预设模式                                                            │
│                                                                      │
│  ┌─────────────────┐    ┌─────────────────┐                       │
│  │    ⚡           │    │    🔬           │                       │
│  │  快速检索       │    │  深度检索       │                       │
│  │  (默认)        │    │                 │                       │
│  │  速度优先      │    │  上下文完整     │                       │
│  └─────────────────┘    └─────────────────┘                       │
│                                                                      │
│  当前: ⚡ 快速检索                                                   │
│  参数: top_k=10, use_auto_merging=false                             │
└─────────────────────────────────────────────────────────────────────┘
```

**预设参数对照**：

| 预设 | top_k | use_auto_merging | 说明 |
|------|-------|------------------|------|
| **⚡ 快速检索** | 10 | false | 通用场景，速度优先 |
| **🔬 深度检索** | 20 | true | 需要更完整上下文 |

---

### 6. 文档片段详情（展开视图）

点击「相关片段」可展开查看完整的相关段落：

```
┌─────────────────────────────────────────────────────────────────────┐
│  📄 async_guide.md                                      [✕ 关闭]    │
│  ─────────────────────────────────────────────────────────────────  │
│                                                                      │
│  📍 位置: tech_tools/guides/async_guide.md · 第 45-67 行            │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                                                              │    │
│  │  asyncio 是 Python 的异步编程框架，提供协程和任务调度功能。  │    │
│  │                                                              │    │
│  │  核心概念：                                                  │    │
│  │  - 协程 (Coroutine): 使用 async def 定义                    │    │
│  │  - 任务 (Task): asyncio.create_task() 创建                  │    │
│  │  - 事件循环 (Event Loop): asyncio.run() 启动                │    │
│  │                                                              │    │
│  │  基本用法：                                                   │    │
│  │  ```python                                                   │    │
│  │  import asyncio                                              │    │
│  │                                                              │    │
│  │  async def main():                                           │    │
│  │      await asyncio.sleep(1)                                  │    │
│  │      print('Hello')                                          │    │
│  │                                                              │    │
│  │  asyncio.run(main())                                         │    │
│  │  ```                                                         │    │
│  │                                                              │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  相关度: 95%                                                         │
│                                                                      │
│  [⬆️ 上一片段]  [⬇️ 下一片段]                    [📋 复制] [🔗 分享] │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**设计要点**：
- 使用 Dialog 或 Drawer 展示详情
- 显示文档路径和行号位置
- 支持代码高亮（如果包含代码）
- 提供上一片段/下一片段导航

---

### 7. 提示信息与帮助

使用 Tooltip 和 Alert 组件提供上下文帮助：

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  💡 提示组件示例                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ ℹ️ 自动路由：系统根据检索内容自动选择相关知识库               │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ⚠️ 警告组件示例                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ ⚠️ Auto-Merging 仅在知识库使用"层级分块"时有效              │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ❌ 错误组件示例                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ ❌ 检索失败，请检查网络连接或重试                             │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**设计要点**：
- 警告信息使用黄色/橙色标识
- 错误信息使用红色标识
- 每个参数旁边使用 `?` 图标触发 Tooltip 解释

---

### 8. Search vs Query 模式选择

在首页或顶部提供清晰的选择入口：

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                      │
│    您想要做什么？                                                     │
│                                                                      │
│    ┌──────────────────────────────┐  ┌────────────────────────────┐ │
│    │                              │  │                            │ │
│    │         🔍                  │  │           💬               │ │
│    │                              │  │                            │ │
│    │      仅检索文档               │  │       RAG 问答             │ │
│    │      (快速，仅返回片段)       │  │   (生成答案+引用来源)      │ │
│    │                              │  │                            │ │
│    │      ⚡ 快速                  │  │      🧠 智能               │ │
│    │                              │  │                            │ │
│    │      [开始检索]              │  │      [开始问答]            │ │
│    │                              │  │                            │ │
│    └──────────────────────────────┘  └────────────────────────────┘ │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**设计要点**：
- 两个大卡片并列，对比鲜明
- 清晰说明各自特点：Search 快但仅返回片段，Query 生成答案但较慢
- 图标区分：🔍 vs 💬
- 引导用户根据需求选择

---

### 9. 移动端适配

移动端采用底部标签栏替代侧边导航：

```
┌─────────────────────────────┐
│  🔍 文档检索          [⚙️]  │
├─────────────────────────────┤
│                             │
│  ┌───────────────────────┐  │
│  │ 🔍 搜索文档...        │  │
│  └───────────────────────┘  │
│                             │
│  [tech_tools ▼] [10条 ▼]   │
│                             │
│  [⚡ 快速]  [🔬 深度]       │
│                             │
│  ─────────────────────────  │
│                             │
│  📄 async_guide.md  95% ▶  │
│  ─────────────────────────  │
│  📄 async_tutorial.pdf 89% │
│  ─────────────────────────  │
│  📄 asyncio_doc.md    82%  │
│                             │
├─────────────────────────────┤
│ [🏠] [📚] [🔍] [💬] [📋]  │  ← 底部 Tab Bar
└─────────────────────────────┘
```

**移动端优化**：
- 参数面板改为垂直堆叠
- 结果卡片简化为单行摘要
- 使用原生滑动返回

---

## API 调用示例

### 指定单库检索

```json
POST /search
{
  "query": "Python 异步编程的要点是什么？",
  "kb_ids": "tech_tools"
}
```

### 自动路由检索

```json
POST /search
{
  "query": "如何配置 Nginx 反向代理",
  "route_mode": "auto"
}
```

### 自动路由 + 指定模型

```json
POST /search
{
  "query": "如何配置 Nginx 反向代理",
  "route_mode": "auto",
  "model_id": "ollama/lfm2.5-instruct:1.2b"
}
```

### 多知识库检索

```json
POST /search
{
  "query": "这个项目涉及哪些技术领域",
  "kb_ids": "tech_tools,programming,devops"
}
```

### 深度检索模式

```json
POST /search
{
  "query": "分析当前经济形势下的投资策略",
  "kb_ids": "tech_tools",
  "use_auto_merging": true
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
| **LLM 调用** | 仅自动路由时调用 | 有 |
| **响应速度** | 快（普通检索） | 较慢 |
| **适用场景** | 仅需文档片段 | 需要生成答案 |
| **模型选择** | ✅ 支持 `model_id`（用于自动路由和答案生成） | ✅ 支持 `model_id` |

> 💡 **说明**：
> - Search 在**自动路由模式**下会调用 LLM 选择知识库，此时 `model_id` 控制路由使用的模型
> - 在**多知识库查询**时，`model_id` 也用于在拼接上下文后生成综合答案
> - Query 全程使用 LLM 生成答案

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
| `--auto` | `route_mode="auto"` | 自动路由 |
| `--kb-ids` | `kb_ids` | 指定知识库（逗号分隔） |
| `--exclude` | `exclude` | 排除的知识库 |
| `--model-id` | `model_id` | 指定使用的模型ID（用于自动路由） |
| `--embed-model-id` | `embed_model_id` | 指定 Embedding 模型 |
| `--auto-merging` | `use_auto_merging=true` | 显式开启 Auto-Merging |
| `--no-auto-merging` | `use_auto_merging=false` | 显式关闭 Auto-Merging |
| `--top-k` | `top_k` | 检索数量 |

---

## 附录：参数默认值来源

部分参数默认值为 `null`，表示使用服务端配置默认值。在 `.env` 中可以设置：

```env
USE_AUTO_MERGING=false
```

客户端可以省略这些参数让服务端使用默认值，也可以显式传递覆盖服务端配置。
