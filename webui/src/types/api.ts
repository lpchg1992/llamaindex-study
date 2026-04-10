export interface KBInfo {
  id: string
  name: string
  description: string
  status: string
  row_count: number | null
  chunk_count?: number
  persist_dir?: string
  chunk_strategy?: string
}

export interface KBUpdateRequest {
  name?: string
  description?: string
  chunk_strategy?: string
}

export interface TopicUpdateRequest {
  topics: string[]
}

export interface DangerousOperationRequest {
  confirmation_name: string
}

export interface FileProgressItem {
  file_id: string
  file_name: string
  status: 'pending' | 'processing' | 'embedding' | 'writing' | 'completed' | 'failed' | 'cancelled'
  total_chunks: number
  processed_chunks: number
  db_written: boolean
  error?: string
  started_at?: number
  completed_at?: number
}

export interface TaskResponse {
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'paused'
  kb_id: string
  message: string
  progress: number
  current?: number
  total?: number
  result?: {
    kb_id: string
    files: number
    nodes: number
    sources?: string[]
    endpoint_stats?: Record<string, number>
    chunk_strategy?: string
    failed?: number
    processed_chunks?: number
    total_chunks?: number
    file_progress?: FileProgressItem[]
  }
  error?: string
  file_progress?: FileProgressItem[]
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
  retrieval_mode?: 'vector' | 'hybrid'
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

export interface SelectiveImportItem {
  type: string
  id?: string
  path?: string
  options?: {
    force_ocr?: boolean
  }
}

export interface SelectiveImportRequest {
  source_type: string
  items: SelectiveImportItem[]
  async_mode?: boolean
  refresh_topics?: boolean
  prefix?: string
}

export interface FilesImportRequest {
  paths: string[]
  async_mode?: boolean
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

// Zotero
export interface ZoteroCollection {
  collectionID: string
  collectionName: string
  parentCollectionID?: string
  numItems?: number
}

export interface ZoteroCollectionsResponse {
  collections: ZoteroCollection[]
}

export interface ZoteroCollectionStructure {
  collection_id: string
  collection_name: string
  parent_id: number | null
  sub_collections: Array<{
    collection_id: number
    name: string
  }>
  items: Array<{
    item_id: number
    title: string
    creators: string[]
    has_file: boolean
    has_annotations: boolean
    has_notes: boolean
  }>
  item_count: number
}

export interface ZoteroCollectionWithItems {
  collection_id: string
  collection_name: string
  parent_id: number | null
  items: Array<{
    item_id: number
    title: string
    has_file: boolean
  }>
  item_count: number
}

// Zotero Preview
export interface ZoteroPreviewItem {
  item_id: number
  title: string
  creators: string[]
  has_attachment: boolean
  attachment_path: string | null
  attachment_type: string | null
  is_scanned_pdf: boolean
  has_md_cache: boolean
  is_eligible: boolean
  ineligible_reason: string | null
  is_duplicate: boolean
}

export interface ZoteroPreviewResponse {
  total_items: number
  eligible_items: number
  ineligible_items: number
  duplicate_items: number
  items: ZoteroPreviewItem[]
  filtering_rules: string[]
}

export interface ZoteroPreviewRequest {
  kb_id: string
  item_ids?: number[]
  collection_id?: string
  prefix?: string
}


// Obsidian
export interface ObsidianVault {
  name: string
  path: string
  exists: boolean
  note_count?: number
}

export interface ObsidianVaultsResponse {
  vaults: ObsidianVault[]
}

export interface ObsidianVaultStructure {
  vault_name: string
  vault_path: string
  folder_path: string
  items: ObsidianVaultItem[]
}

export interface ObsidianVaultItem {
  type: 'folder' | 'file'
  name: string
  path: string
  md_count?: number
  size?: number
  has_children?: boolean
  children?: ObsidianVaultItem[]
}

export interface ObsidianVaultTree {
  vault_name: string
  vault_path: string
  items: ObsidianVaultItem[]
}

// LanceDB
export interface LanceTableStats {
  kb_id: string
  table_name?: string
  row_count: number
  size_mb: number
}

export interface LanceDocSummary {
  doc_id: string
  source_file: string | null
  node_count: number
  total_chars: number
  first_node_id: string
  last_node_id: string
}

export interface LanceNode {
  id: string
  doc_id: string
  text: string
  text_length: number
  metadata: Record<string, unknown>
  score?: number
}

export interface LanceDuplicate {
  source: string
  doc_ids: string[]
  count: number
}

// Document Management
export interface DocumentInfo {
  id: string
  kb_id: string
  source_file: string
  source_path: string
  file_hash: string
  zotero_doc_id: string | null
  file_size: number
  mime_type: string
  chunk_count: number
  total_chars: number
  metadata: Record<string, unknown>
  created_at: number
  updated_at: number
}

export interface ChunkInfo {
  id: string
  doc_id: string
  kb_id: string
  text: string
  text_length: number
  chunk_index: number
  parent_chunk_id: string | null
  hierarchy_level: number
  metadata: Record<string, unknown>
  embedding_generated: boolean
  created_at: number
  updated_at: number
}

// Chat
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
}

export interface ChatSession {
  session_id: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface ChatHistoryResponse {
  session_id: string
  history: ChatMessage[]
}

export interface ChatSessionsResponse {
  sessions: ChatSession[]
}

export interface ChatResponse {
  response: string
  session_id: string
  kb_id: string
  history: ChatMessage[]
}

// Observability
export interface ModelStats {
  vendor_id: string
  model_type: string
  model_id: string
  call_count: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  error_count: number
}

export interface VendorStats {
  vendor_id: string
  models: ModelStats[]
  total_calls: number
  total_prompt_tokens: number
  total_completion_tokens: number
  total_tokens: number
  total_errors: number
}

export interface ObservabilityStats {
  vendor_stats: VendorStats[]
  total_calls: number
  total_tokens: number
  total_prompt_tokens?: number
  total_completion_tokens?: number
  total_errors?: number
  start_date?: string
  end_date?: string
}

export interface TraceEvent {
  timestamp: string
  query: string
  duration_ms: number
  retrieval_count: number
  retrieval_scores: number[]
  source_node_count: number
  llm_input_tokens: number
  llm_output_tokens: number
  embedding_tokens: number
  total_tokens: number
  error?: string
}

export interface TracesResponse {
  traces: TraceEvent[]
  total: number
  start_date?: string
  end_date?: string
}

export interface ObservabilityDatesResponse {
  dates: string[]
}

// Consistency
export interface ConsistencyCheckResult {
  kb_id: string
  is_consistent: boolean
  issues: string[]
  details?: Record<string, unknown>
}

export interface ConsistencyRepairResult {
  kb_id: string
  mode: string
  repaired: number
  deleted: number
  message: string
}

// Task batch operations
export interface TaskBatchResult {
  affected: number
  message: string
}

// Vendor & Model requests
export interface VendorCreateRequest {
  id: string
  name: string
  api_base?: string
  api_key?: string
  is_active?: boolean
}

export interface ModelCreateRequest {
  id: string
  vendor_id: string
  name?: string
  type: 'llm' | 'embedding' | 'reranker'
  is_active?: boolean
  is_default?: boolean
  config?: Record<string, unknown>
}

// Initialize KB
export interface InitializeKBResponse {
  status: string
  task_id?: string
  message: string
}

// Refresh Topics
export interface RefreshTopicsRequest {
  has_new_docs?: boolean
}

// Extract
export interface ExtractRequest {
  text: string
  schema_definition: Record<string, unknown>
  prompt_template?: string
}

export interface ExtractResponse {
  data: Record<string, unknown>
  error?: string
}

// Settings
export interface SystemSettings {
  llm_mode: string
  default_llm_model: string | null
  ollama_embed_model: string
  ollama_base_url: string
  top_k: number
  use_hybrid_search: boolean
  use_auto_merging: boolean
  use_hyde: boolean
  use_multi_query: boolean
  num_multi_queries: number
  hybrid_search_alpha: number
  chunk_strategy: string
  chunk_size: number
  chunk_overlap: number
  use_reranker: boolean
  rerank_model: string
  response_mode: string
}

export interface SettingsUpdateRequest {
  llm_mode?: string
  default_llm_model?: string | null
  ollama_embed_model?: string
  ollama_base_url?: string
  top_k?: number
  use_hybrid_search?: boolean
  use_auto_merging?: boolean
  use_hyde?: boolean
  use_multi_query?: boolean
  num_multi_queries?: number
  hybrid_search_alpha?: number
  chunk_strategy?: string
  chunk_size?: number
  chunk_overlap?: number
  use_reranker?: boolean
  rerank_model?: string
  response_mode?: string
}

export interface RestartResponse {
  status: string
  message: string
}