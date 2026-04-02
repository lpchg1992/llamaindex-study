export interface KBInfo {
  id: string
  name: string
  description: string
  status: string
  row_count: number | null
  persist_dir?: string
  chunk_strategy?: string
}

export interface TaskResponse {
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'paused'
  kb_id: string
  message: string
  progress: number
  result?: {
    kb_id: string
    files: number
    nodes: number
    sources?: string[]
    endpoint_stats?: Record<string, number>
    chunk_strategy?: string
  }
  error?: string
}

export interface SearchResult {
  text: string
  score: number
  metadata: Record<string, unknown>
  kb_id?: string
}

export interface SearchRequest {
  query: string
  top_k?: number
  route_mode: 'general' | 'auto'
  model_id?: string
  embed_model_id?: string
  kb_ids?: string
  exclude?: string[]
  use_auto_merging?: boolean
}

export interface QueryRequest {
  query: string
  top_k?: number
  route_mode: 'general' | 'auto'
  retrieval_mode?: 'vector' | 'hybrid'
  model_id?: string
  embed_model_id?: string
  llm_mode?: string
  kb_ids?: string
  exclude?: string[]
  use_hyde?: boolean
  use_multi_query?: boolean
  num_multi_queries?: number
  use_auto_merging?: boolean
  response_mode?: string
}

export interface QueryResponse {
  response: string
  sources: Array<{
    text: string
    score: number
    metadata?: Record<string, unknown>
  }>
}

export interface IngestRequest {
  path: string
  async_mode?: boolean
  refresh_topics?: boolean
}

export interface IngestResponse {
  status: string
  task_id?: string
  message?: string
  files_processed?: number
  nodes_created?: number
  failed?: number
  source?: string
}

export interface ObsidianIngestRequest {
  vault_path?: string
  folder_path?: string
  recursive?: boolean
  async_mode?: boolean
  exclude_patterns?: string[]
  refresh_topics?: boolean
}

export interface ZoteroIngestRequest {
  collection_id?: string
  collection_name?: string
  async_mode?: boolean
  rebuild?: boolean
  refresh_topics?: boolean
}

export interface ModelInfo {
  id: string
  vendor_id: string
  name: string
  type: 'llm' | 'embedding' | 'reranker'
  is_active: boolean
  is_default: boolean
  config: Record<string, unknown>
}

export interface VendorInfo {
  id: string
  name: string
  api_base?: string
  api_key?: string
  is_active: boolean
}

export interface EvaluateRequest {
  questions: string[]
  ground_truths: string[]
  top_k?: number
}

export interface EvaluateResponse {
  faithfulness: number
  answer_relevancy: number
  context_precision: number
  context_recall: number
}

export interface TopicInfo {
  kb_id: string
  topics: string[]
  topic_count: number
}