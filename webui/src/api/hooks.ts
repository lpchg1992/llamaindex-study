import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from './client'
import type {
  KBInfo,
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
    mutationFn: async (kbId: string) => {
      await apiClient.delete(`${API_BASE}/kbs/${kbId}`)
      return kbId
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kbs'] })
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