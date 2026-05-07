import { useEffect, useRef, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'

export interface TaskWebSocketMessage {
  type: 'task_update'
  task_id: string
  data: {
    status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'paused'
    progress: number
    current?: number
    total?: number
    message: string
    result?: {
      kb_id: string
      files: number
      nodes: number
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
}

interface FileProgressItem {
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

export function useTaskWebSocket(enabled: boolean = true) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const queryClient = useQueryClient()

  const connect = useCallback(() => {
    if (!enabled) return

    let wsUrl: string
    if (import.meta.env.VITE_API_BASE) {
      const base = import.meta.env.VITE_API_BASE
      const protocol = base.startsWith('https') ? 'wss:' : 'ws:'
      const host = base.replace(/^https?:\/\//, '')
      wsUrl = `${protocol}//${host}/ws/tasks`
    } else {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      wsUrl = `${protocol}//${window.location.host}/ws/tasks`
    }

    try {
      wsRef.current = new WebSocket(wsUrl)

      wsRef.current.onopen = () => {
        console.log('Task WebSocket connected')
      }

      wsRef.current.onmessage = (event) => {
        try {
          const message: TaskWebSocketMessage = JSON.parse(event.data)
          
          if (message.type === 'task_update') {
            queryClient.setQueryData<TaskResponse>(['task', message.task_id], (oldData) => {
              if (!oldData) return oldData
              return {
                ...oldData,
                status: message.data.status,
                progress: message.data.progress,
                current: message.data.current,
                total: message.data.total,
                message: message.data.message,
                result: message.data.result,
                error: message.data.error,
                file_progress: message.data.file_progress || oldData.file_progress,
              }
            })

            queryClient.setQueryData<TaskResponse[]>(['tasks'], (oldData) => {
              if (!oldData) return oldData
              
              const taskIndex = oldData.findIndex(t => t.task_id === message.task_id)
              if (taskIndex === -1) {
                return [{
                  task_id: message.task_id,
                  status: message.data.status,
                  kb_id: message.data.result?.kb_id || '',
                  message: message.data.message,
                  progress: message.data.progress,
                  current: message.data.current,
                  total: message.data.total,
                  result: message.data.result,
                  error: message.data.error,
                  file_progress: message.data.file_progress,
                } as TaskResponse, ...oldData]
              }

              const updatedTasks = [...oldData]
              updatedTasks[taskIndex] = {
                ...updatedTasks[taskIndex],
                status: message.data.status,
                progress: message.data.progress,
                current: message.data.current,
                total: message.data.total,
                message: message.data.message,
                result: message.data.result,
                error: message.data.error,
                file_progress: message.data.file_progress || updatedTasks[taskIndex].file_progress,
              }
              return updatedTasks
            })

            if (message.data.status === 'completed' || message.data.status === 'failed') {
              queryClient.invalidateQueries({ queryKey: ['tasks'] })
            }
          }
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error)
        }
      }

      wsRef.current.onclose = () => {
        console.log('Task WebSocket disconnected')
        if (enabled) {
          reconnectTimeoutRef.current = setTimeout(connect, 3000)
        }
      }

      wsRef.current.onerror = (error) => {
        console.warn('Task WebSocket error (may be expected if API is not running):', error.type)
      }
    } catch (error) {
      console.error('Failed to connect WebSocket:', error)
    }
  }, [enabled, queryClient])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  useEffect(() => {
    if (enabled) {
      connect()
    } else {
      disconnect()
    }

    return () => {
      disconnect()
    }
  }, [enabled, connect, disconnect])

  return { disconnect, reconnect: connect }
}

interface TaskResponse {
  task_id: string
  task_type: 'zotero' | 'obsidian' | 'obsidian_folder' | 'generic' | 'initialize' | 'selective'
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
  }
  error?: string
  file_progress?: FileProgressItem[]
}

export default useTaskWebSocket