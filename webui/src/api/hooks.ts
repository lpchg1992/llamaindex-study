import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from './client'
import type {
  KBInfo,
  KBUpdateRequest,
  TaskResponse,
  SearchResult,
  SearchRequest,
  QueryRequest,
  QueryResponse,
  IngestRequest,
  IngestResponse,
  ObsidianIngestRequest,
  ZoteroIngestRequest,
  ModelInfo,
  VendorInfo,
  EvaluateRequest,
  EvaluateResponse,
  TopicInfo,
  ZoteroCollectionsResponse,
  ZoteroCollectionStructure,
  ZoteroCollectionWithItems,
  ObsidianVaultsResponse,
  ObsidianVault,
  ObsidianVaultStructure,
  ObsidianVaultTree,
  LanceTableStats,
  LanceDocSummary,
  LanceNode,
  LanceDuplicate,
  ChatResponse,
  ChatHistoryResponse,
  ChatSessionsResponse,
  ObservabilityStats,
  ObservabilityDatesResponse,
  TracesResponse,
  ConsistencyCheckResult,
  ConsistencyRepairResult,
  TaskBatchResult,
  VendorCreateRequest,
  ModelCreateRequest,
  InitializeKBResponse,
  RefreshTopicsRequest,
  SystemSettings,
  SettingsUpdateRequest,
  RestartResponse,
  DocumentInfo,
  ChunkInfo,
  SelectiveImportRequest,
  FilesImportRequest,
} from '@/types/api'

const API_BASE = ''

export function useKBs() {
  return useQuery<KBInfo[]>({
    queryKey: ['kbs'],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/kbs`)
      return data
    },
  })
}

export function useKB(kbId: string) {
  return useQuery<KBInfo>({
    queryKey: ['kb', kbId],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/kbs/${kbId}`)
      return data
    },
    enabled: !!kbId,
  })
}

export function useCreateKB() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (kb: KBInfo) => {
      const { data } = await apiClient.post(`${API_BASE}/kbs`, kb)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kbs'] })
    },
  })
}

export function useDeleteKB() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ kbId, confirmationName }: { kbId: string; confirmationName: string }) => {
      await apiClient.delete(`${API_BASE}/kbs/${kbId}`, {
        data: { confirmation_name: confirmationName },
      })
      return kbId
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kbs'] })
    },
  })
}

export function useUpdateKB() {
  const queryClient = useQueryClient()
  return useMutation<KBInfo, Error, { kbId: string; data: KBUpdateRequest }>({
    mutationFn: async ({ kbId, data }) => {
      const { data: result } = await apiClient.put<KBInfo>(
        `${API_BASE}/kbs/${kbId}`,
        data
      )
      return result
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kbs'] })
    },
  })
}

export function useUpdateTopics() {
  const queryClient = useQueryClient()
  return useMutation<TopicInfo, Error, { kbId: string; topics: string[] }>({
    mutationFn: async ({ kbId, topics }) => {
      const { data } = await apiClient.put<TopicInfo>(
        `${API_BASE}/kbs/${kbId}/topics`,
        { topics }
      )
      return data
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['kb-topics', variables.kbId] })
    },
  })
}

export function useKBTasks(kbId?: string, status?: string) {
  return useQuery<TaskResponse[]>({
    queryKey: ['tasks', { kbId, status }],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (kbId) params.append('kb_id', kbId)
      if (status) params.append('status', status)
      const { data } = await apiClient.get(`${API_BASE}/tasks?${params}`)
      return data
    },
  })
}

export function useTask(taskId: string) {
  return useQuery<TaskResponse, Error, TaskResponse, ['task', string]>({
    queryKey: ['task', taskId],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/tasks/${taskId}`)
      return data
    },
    enabled: !!taskId,
  })
}

export function useSearch() {
  return useMutation<SearchResult[], Error, SearchRequest>({
    mutationFn: async (req: SearchRequest) => {
      const { data } = await apiClient.post<SearchResult[]>(
        `${API_BASE}/search`,
        req
      )
      return data
    },
  })
}

export function useQueryMutation() {
  return useMutation<QueryResponse, Error, QueryRequest>({
    mutationFn: async (req: QueryRequest) => {
      const { data } = await apiClient.post<QueryResponse>(
        `${API_BASE}/query`,
        req
      )
      return data
    },
  })
}

export function useIngestFile() {
  return useMutation<IngestResponse, Error, { kbId: string; req: IngestRequest }>({
    mutationFn: async ({ kbId, req }) => {
      const { data } = await apiClient.post<IngestResponse>(
        `${API_BASE}/kbs/${kbId}/ingest`,
        req
      )
      return data
    },
  })
}

export function useIngestSelective() {
  return useMutation<IngestResponse, Error, { kbId: string; req: SelectiveImportRequest }>({
    mutationFn: async ({ kbId, req }) => {
      const { data } = await apiClient.post<IngestResponse>(
        `${API_BASE}/kbs/${kbId}/ingest/selective`,
        req
      )
      return data
    },
  })
}

export function useIngestFiles() {
  return useMutation<IngestResponse, Error, { kbId: string; req: FilesImportRequest }>({
    mutationFn: async ({ kbId, req }) => {
      const { data } = await apiClient.post<IngestResponse>(
        `${API_BASE}/kbs/${kbId}/ingest/files`,
        req
      )
      return data
    },
  })
}

export function useIngestObsidian() {
  return useMutation<IngestResponse, Error, { kbId: string; req: ObsidianIngestRequest }>({
    mutationFn: async ({ kbId, req }) => {
      const { data } = await apiClient.post<IngestResponse>(
        `${API_BASE}/kbs/${kbId}/ingest/obsidian`,
        req
      )
      return data
    },
  })
}

export function useIngestZotero() {
  return useMutation<IngestResponse, Error, { kbId: string; req: ZoteroIngestRequest }>({
    mutationFn: async ({ kbId, req }) => {
      const { data } = await apiClient.post<IngestResponse>(
        `${API_BASE}/kbs/${kbId}/ingest/zotero`,
        req
      )
      return data
    },
  })
}

export function useCancelTask() {
  const queryClient = useQueryClient()
  return useMutation<string, Error, string>({
    mutationFn: async (taskId: string) => {
      await apiClient.delete(`${API_BASE}/tasks/${taskId}`)
      return taskId
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

export function usePauseTask() {
  const queryClient = useQueryClient()
  return useMutation<string, Error, string>({
    mutationFn: async (taskId: string) => {
      await apiClient.post(`${API_BASE}/tasks/${taskId}/pause`)
      return taskId
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

export function useResumeTask() {
  const queryClient = useQueryClient()
  return useMutation<string, Error, string>({
    mutationFn: async (taskId: string) => {
      await apiClient.post(`${API_BASE}/tasks/${taskId}/resume`)
      return taskId
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

export function useModels(type?: string) {
  return useQuery<ModelInfo[]>({
    queryKey: ['models', type],
    queryFn: async () => {
      const params = type ? `?type=${type}` : ''
      const { data } = await apiClient.get(`${API_BASE}/models${params}`)
      return data
    },
  })
}

export function useVendors() {
  return useQuery<VendorInfo[]>({
    queryKey: ['vendors'],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/vendors`)
      return data
    },
  })
}

export function useKBTopics(kbId: string) {
  return useQuery<TopicInfo>({
    queryKey: ['kb-topics', kbId],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/kbs/${kbId}/topics`)
      return data
    },
    enabled: !!kbId,
  })
}

export function useEvaluate() {
  return useMutation<EvaluateResponse, Error, { kbId: string; req: EvaluateRequest }>({
    mutationFn: async ({ kbId, req }) => {
      const { data } = await apiClient.post<EvaluateResponse>(
        `${API_BASE}/evaluate/${kbId}`,
        req
      )
      return data
    },
  })
}

export function useEvaluateMetrics() {
  return useQuery({
    queryKey: ['evaluate-metrics'],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/evaluate/metrics`)
      return data
    },
  })
}

export function useRefreshTopics() {
  const queryClient = useQueryClient()
  return useMutation<TopicInfo, Error, { kbId: string; req: RefreshTopicsRequest }>({
    mutationFn: async ({ kbId, req }) => {
      const { data } = await apiClient.post<TopicInfo>(
        `${API_BASE}/kbs/${kbId}/topics/refresh`,
        req
      )
      return data
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['kb-topics', variables.kbId] })
    },
  })
}

export function useInitializeKB() {
  const queryClient = useQueryClient()
  return useMutation<InitializeKBResponse, Error, { kbId: string; confirmationName: string; asyncMode?: boolean }>({
    mutationFn: async ({ kbId, confirmationName, asyncMode = true }) => {
      const { data } = await apiClient.post<InitializeKBResponse>(
        `${API_BASE}/kbs/${kbId}/initialize`,
        { confirmation_name: confirmationName },
        { params: { async_mode: asyncMode } }
      )
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kbs'] })
    },
  })
}

export function useDeleteTask() {
  const queryClient = useQueryClient()
  return useMutation<{ status: string; message?: string }, Error, { taskId: string; cleanup?: boolean }>({
    mutationFn: async ({ taskId, cleanup }) => {
      const { data } = await apiClient.delete(`${API_BASE}/tasks/${taskId}/delete`, {
        params: { cleanup },
      })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

export function useDeleteAllTasks() {
  const queryClient = useQueryClient()
  return useMutation<TaskBatchResult, Error, { status?: string; cleanup?: boolean }>({
    mutationFn: async ({ status = 'completed', cleanup = false }) => {
      const { data } = await apiClient.delete(`${API_BASE}/tasks/delete-all`, {
        params: { status, cleanup },
      })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

export function usePauseAllTasks() {
  const queryClient = useQueryClient()
  return useMutation<TaskBatchResult, Error, string>({
    mutationFn: async (status = 'running') => {
      const { data } = await apiClient.post<TaskBatchResult>(`${API_BASE}/tasks/pause-all`, null, {
        params: { status },
      })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

export function useResumeAllTasks() {
  const queryClient = useQueryClient()
  return useMutation<TaskBatchResult, Error, void>({
    mutationFn: async () => {
      const { data } = await apiClient.post<TaskBatchResult>(`${API_BASE}/tasks/resume-all`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

export function useCleanupTasks() {
  const queryClient = useQueryClient()
  return useMutation<TaskBatchResult, Error, void>({
    mutationFn: async () => {
      const { data } = await apiClient.post<TaskBatchResult>(`${API_BASE}/tasks/cleanup`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

export function useZoteroCollections() {
  return useQuery<ZoteroCollectionsResponse, Error>({
    queryKey: ['zotero-collections'],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/zotero/collections`)
      return data
    },
  })
}

export function useSearchZoteroCollections() {
  return useMutation<ZoteroCollectionsResponse, Error, string>({
    mutationFn: async (q) => {
      const { data } = await apiClient.get(`${API_BASE}/zotero/collections/search`, {
        params: { q },
      })
      return data
    },
  })
}

export function useZoteroCollectionStructure(collectionId: string) {
  return useQuery<ZoteroCollectionStructure, Error>({
    queryKey: ['zotero-collection-structure', collectionId],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/zotero/collections/${collectionId}/structure`)
      return data
    },
    enabled: !!collectionId,
  })
}

export function useAllZoteroCollectionsWithItems() {
  return useQuery<{ collections: ZoteroCollectionWithItems[] }, Error>({
    queryKey: ['zotero-collections-with-items'],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/zotero/collections/with-items`)
      return data
    },
  })
}

export function useObsidianVaults() {
  return useQuery<ObsidianVaultsResponse, Error>({
    queryKey: ['obsidian-vaults'],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/obsidian/vaults`)
      return data
    },
  })
}

export function useObsidianVault(vaultName: string) {
  return useQuery<ObsidianVault, Error>({
    queryKey: ['obsidian-vault', vaultName],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/obsidian/vaults/${vaultName}`)
      return data
    },
    enabled: !!vaultName,
  })
}

export function useObsidianVaultStructure(vaultName: string, folderPath?: string) {
  return useQuery<ObsidianVaultStructure, Error>({
    queryKey: ['obsidian-vault-structure', vaultName, folderPath],
    queryFn: async () => {
      const params = folderPath ? { folder_path: folderPath } : {}
      const { data } = await apiClient.get(`${API_BASE}/obsidian/vaults/${vaultName}/structure`, { params })
      return data
    },
    enabled: !!vaultName,
  })
}

export function useObsidianVaultTree(vaultName: string) {
  return useQuery<ObsidianVaultTree, Error>({
    queryKey: ['obsidian-vault-tree', vaultName],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/obsidian/vaults/${vaultName}/tree`)
      return data
    },
    enabled: !!vaultName,
  })
}

export function useLanceTables() {
  return useQuery<{ tables: string[] }, Error>({
    queryKey: ['lance-tables'],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/lance/tables`)
      return data
    },
  })
}

export function useLanceStats(kbId: string, tableName?: string) {
  return useQuery<LanceTableStats, Error>({
    queryKey: ['lance-stats', kbId, tableName],
    queryFn: async () => {
      const params = tableName ? { table_name: tableName } : {}
      const { data } = await apiClient.get(`${API_BASE}/lance/${kbId}/stats`, { params })
      return data
    },
    enabled: !!kbId,
  })
}

export function useLanceDocs(kbId: string, tableName?: string) {
  return useQuery<{ docs: LanceDocSummary[] }, Error>({
    queryKey: ['lance-docs', kbId, tableName],
    queryFn: async () => {
      const params = tableName ? { table_name: tableName } : {}
      const { data } = await apiClient.get(`${API_BASE}/lance/${kbId}/docs`, { params })
      return data
    },
    enabled: !!kbId,
  })
}

export function useLanceNodes(kbId: string, docId?: string, limit?: number) {
  return useQuery<{ nodes: LanceNode[] }, Error>({
    queryKey: ['lance-nodes', kbId, docId, limit],
    queryFn: async () => {
      const params: Record<string, unknown> = {}
      if (docId) params.doc_id = docId
      if (limit) params.limit = limit
      const { data } = await apiClient.get(`${API_BASE}/lance/${kbId}/nodes`, { params })
      return data
    },
    enabled: !!kbId,
  })
}

export function useLanceDuplicates(kbId: string, tableName?: string) {
  return useQuery<{ duplicates: LanceDuplicate[]; count: number }, Error>({
    queryKey: ['lance-duplicates', kbId, tableName],
    queryFn: async () => {
      const params = tableName ? { table_name: tableName } : {}
      const { data } = await apiClient.get(`${API_BASE}/lance/${kbId}/duplicates`, { params })
      return data
    },
    enabled: !!kbId,
  })
}

export function useChat(kbId: string) {
  return useMutation<ChatResponse, Error, { message: string; sessionId?: string }>({
    mutationFn: async ({ message, sessionId }) => {
      const { data } = await apiClient.post<ChatResponse>(
        `${API_BASE}/chat/${kbId}`,
        { message, session_id: sessionId }
      )
      return data
    },
  })
}

export function useChatSessions(kbId: string) {
  return useQuery<ChatSessionsResponse, Error>({
    queryKey: ['chat-sessions', kbId],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/chat/${kbId}/sessions`)
      return data
    },
    enabled: !!kbId,
  })
}

export function useChatHistory(kbId: string, sessionId: string, limit?: number) {
  return useQuery<ChatHistoryResponse, Error>({
    queryKey: ['chat-history', kbId, sessionId, limit],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/chat/${kbId}/history/${sessionId}`, {
        params: { limit },
      })
      return data
    },
    enabled: !!kbId && !!sessionId,
  })
}

export function useDeleteChatSession() {
  const queryClient = useQueryClient()
  return useMutation<{ deleted: boolean; session_id: string }, Error, { kbId: string; sessionId: string }>({
    mutationFn: async ({ kbId, sessionId }) => {
      const { data } = await apiClient.delete(`${API_BASE}/chat/${kbId}/sessions/${sessionId}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
    },
  })
}

export function useObservabilityStats(startDate?: string, endDate?: string) {
  return useQuery<ObservabilityStats, Error>({
    queryKey: ['observability-stats', startDate, endDate],
    queryFn: async () => {
      const params: Record<string, string> = {}
      if (startDate) params.start_date = startDate
      if (endDate) params.end_date = endDate
      const { data } = await apiClient.get(`${API_BASE}/observability/stats`, { params })
      return data
    },
  })
}

export function useResetObservability() {
  return useMutation<{ status: string }, Error, void>({
    mutationFn: async () => {
      const { data } = await apiClient.post(`${API_BASE}/observability/reset`)
      return data
    },
  })
}

export function useTraces(limit?: number, startDate?: string, endDate?: string) {
  return useQuery<TracesResponse, Error>({
    queryKey: ['traces', limit, startDate, endDate],
    queryFn: async () => {
      const params: Record<string, string | number> = {}
      if (limit) params.limit = limit
      if (startDate) params.start_date = startDate
      if (endDate) params.end_date = endDate
      const { data } = await apiClient.get(`${API_BASE}/observability/traces`, { params })
      return data
    },
  })
}

export function useObservabilityDates() {
  return useQuery<ObservabilityDatesResponse, Error>({
    queryKey: ['observability-dates'],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/observability/dates`)
      return data
    },
  })
}

export function useCreateVendor() {
  const queryClient = useQueryClient()
  return useMutation<VendorInfo, Error, VendorCreateRequest>({
    mutationFn: async (req) => {
      const { data } = await apiClient.post(`${API_BASE}/vendors`, req)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vendors'] })
    },
  })
}

export function useDeleteVendor() {
  const queryClient = useQueryClient()
  return useMutation<{ status: string; vendor_id: string }, Error, string>({
    mutationFn: async (vendorId) => {
      const { data } = await apiClient.delete(`${API_BASE}/vendors/${vendorId}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vendors'] })
    },
  })
}

export function useUpdateVendor() {
  const queryClient = useQueryClient()
  return useMutation<VendorInfo, Error, VendorCreateRequest>({
    mutationFn: async (req) => {
      const { data } = await apiClient.put<VendorInfo>(`${API_BASE}/vendors/${req.id}`, req)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vendors'] })
    },
  })
}

export function useCreateModel() {
  const queryClient = useQueryClient()
  return useMutation<ModelInfo, Error, ModelCreateRequest>({
    mutationFn: async (req) => {
      const { data } = await apiClient.post(`${API_BASE}/models`, req)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
  })
}

export function useDeleteModel() {
  const queryClient = useQueryClient()
  return useMutation<{ status: string; model_id: string }, Error, string>({
    mutationFn: async (modelId) => {
      const { data } = await apiClient.delete(`${API_BASE}/models/${modelId}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
  })
}

export function useUpdateModel() {
  const queryClient = useQueryClient()
  return useMutation<ModelInfo, Error, { modelId: string; data: ModelCreateRequest }>({
    mutationFn: async ({ modelId, data }) => {
      const { data: result } = await apiClient.put<ModelInfo>(`${API_BASE}/models/${modelId}`, data)
      return result
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
  })
}

export function useSetDefaultModel() {
  const queryClient = useQueryClient()
  return useMutation<{ status: string; model_id: string }, Error, string>({
    mutationFn: async (modelId) => {
      const { data } = await apiClient.put(`${API_BASE}/models/${modelId}/default`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
  })
}

export function useConsistencyCheck(kbId: string) {
  return useQuery<ConsistencyCheckResult, Error>({
    queryKey: ['consistency-check', kbId],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/kbs/${kbId}/consistency`)
      return data
    },
    enabled: !!kbId,
  })
}

export function useConsistencyRepair() {
  const queryClient = useQueryClient()
  return useMutation<ConsistencyRepairResult, Error, { kbId: string; mode: string }>({
    mutationFn: async ({ kbId, mode }) => {
      const { data } = await apiClient.post(`${API_BASE}/kbs/${kbId}/consistency/repair`, { mode })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kbs'] })
    },
  })
}

export function useRepairAll() {
  const queryClient = useQueryClient()
  return useMutation<{ repaired: number; message: string }, Error, string>({
    mutationFn: async (mode) => {
      const { data } = await apiClient.post(`${API_BASE}/consistency/repair-all`, null, {
        params: { mode },
      })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kbs'] })
    },
  })
}

export function useRebuildDocstore() {
  const queryClient = useQueryClient()
  return useMutation<{ kb_id: string; nodes_rebuilt: number }, Error, { kbId: string; confirmationName: string }>({
    mutationFn: async ({ kbId, confirmationName }) => {
      const { data } = await apiClient.post(`${API_BASE}/kbs/${kbId}/docstore/rebuild`, {
        confirmation_name: confirmationName,
      })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kbs'] })
    },
  })
}

export function useSettings() {
  return useQuery<SystemSettings>({
    queryKey: ['settings'],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/settings`)
      return data
    },
  })
}

export function useUpdateSettings() {
  const queryClient = useQueryClient()
  return useMutation<SystemSettings, Error, SettingsUpdateRequest>({
    mutationFn: async (req: SettingsUpdateRequest) => {
      const { data } = await apiClient.put<SystemSettings>(`${API_BASE}/settings`, req)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })
}

export function useRestartScheduler() {
  const queryClient = useQueryClient()
  return useMutation<RestartResponse, Error, void>({
    mutationFn: async () => {
      const { data } = await apiClient.post<RestartResponse>(`${API_BASE}/admin/restart-scheduler`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

export function useReloadConfig() {
  const queryClient = useQueryClient()
  return useMutation<RestartResponse, Error, void>({
    mutationFn: async () => {
      const { data } = await apiClient.post<RestartResponse>(`${API_BASE}/admin/reload-config`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
  })
}

export function useRestartApi() {
  return useMutation<RestartResponse, Error, void>({
    mutationFn: async () => {
      const { data } = await apiClient.post<RestartResponse>(`${API_BASE}/admin/restart-api`)
      return data
    },
  })
}

export function useDocuments(kbId: string) {
  return useQuery<DocumentInfo[]>({
    queryKey: ['documents', kbId],
    queryFn: async () => {
      const { data } = await apiClient.get<DocumentInfo[]>(`${API_BASE}/kbs/${kbId}/documents`)
      return data
    },
    enabled: !!kbId,
  })
}

export function useDocument(kbId: string, docId: string) {
  return useQuery<DocumentInfo>({
    queryKey: ['document', kbId, docId],
    queryFn: async () => {
      const { data } = await apiClient.get<DocumentInfo>(`${API_BASE}/kbs/${kbId}/documents/${docId}`)
      return data
    },
    enabled: !!kbId && !!docId,
  })
}

interface PaginatedChunksResponse {
  chunks: ChunkInfo[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export function useDocumentChunks(kbId: string, docId: string, page: number = 1, pageSize: number = 20) {
  return useQuery<PaginatedChunksResponse>({
    queryKey: ['document-chunks', kbId, docId, page, pageSize],
    queryFn: async () => {
      const { data } = await apiClient.get<PaginatedChunksResponse>(
        `${API_BASE}/kbs/${kbId}/documents/${docId}/chunks`,
        { params: { page, page_size: pageSize } }
      )
      return data
    },
    enabled: !!kbId && !!docId,
  })
}

export function useDeleteDocument() {
  const queryClient = useQueryClient()
  return useMutation<{ status: string; doc_id: string; chunks_deleted: number }, Error, { kbId: string; docId: string }>({
    mutationFn: async ({ kbId, docId }) => {
      const { data } = await apiClient.delete(`${API_BASE}/kbs/${kbId}/documents/${docId}`)
      return data
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['documents', variables.kbId] })
    },
  })
}

export function useUpdateChunk() {
  return useMutation<ChunkInfo, Error, { kbId: string; chunkId: string; text: string }>({
    mutationFn: async ({ kbId, chunkId, text }) => {
      const { data } = await apiClient.put<ChunkInfo>(`${API_BASE}/kbs/${kbId}/chunks/${chunkId}`, { text })
      return data
    },
  })
}

export function useReembedChunk() {
  return useMutation<{ status: string; chunk_id: string; message: string }, Error, { kbId: string; chunkId: string }>({
    mutationFn: async ({ kbId, chunkId }) => {
      const { data } = await apiClient.post(`${API_BASE}/kbs/${kbId}/chunks/${chunkId}/reembed`)
      return data
    },
  })
}

export function useDeleteChunk() {
  const queryClient = useQueryClient()
  return useMutation<
    { status: string; chunk_id: string; deleted_chunks: number; deleted_lance: number; children_orphaned: number },
    Error,
    { kbId: string; chunkId: string; cascade?: boolean }
  >({
    mutationFn: async ({ kbId, chunkId, cascade = true }) => {
      const { data } = await apiClient.delete(`${API_BASE}/kbs/${kbId}/chunks/${chunkId}`, {
        params: { cascade },
      })
      return data
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['documents', variables.kbId] })
      queryClient.invalidateQueries({ queryKey: ['document-chunks', variables.kbId] })
    },
  })
}

export function useChunkChildren(kbId: string, chunkId: string) {
  return useQuery<{ children: ChunkInfo[]; count: number }, Error>({
    queryKey: ['chunk-children', kbId, chunkId],
    queryFn: async () => {
      const { data } = await apiClient.get(`${API_BASE}/kbs/${kbId}/chunks/${chunkId}/children`)
      return data
    },
    enabled: !!kbId && !!chunkId,
  })
}