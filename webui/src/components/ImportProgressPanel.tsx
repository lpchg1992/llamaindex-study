import { useState, useEffect } from 'react'
import { CheckCircle, Circle, Loader2, XCircle, AlertCircle } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useTaskWebSocket } from '@/lib/websocket'
import { cn } from '@/lib/utils'

export interface DocumentProgress {
  id: string
  name: string
  status: 'pending' | 'processing' | 'success' | 'failed'
  chunksTotal: number
  chunksProcessed: number
  error?: string
}

interface ImportProgressPanelProps {
  documents: DocumentProgress[]
  documentsTotal: number
  documentsCompleted: number
  taskId?: string
}

export function ImportProgressPanel({
  documents,
  documentsTotal,
  documentsCompleted,
  taskId,
}: ImportProgressPanelProps) {
  const [localDocuments, setLocalDocuments] = useState<DocumentProgress[]>(documents)

  useTaskWebSocket(!!taskId)

  useEffect(() => {
    setLocalDocuments(documents)
  }, [documents])

  useEffect(() => {
    if (!taskId) return

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
    const ws = new WebSocket(wsUrl)

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data)
        if (message.type === 'task_update' && message.task_id === taskId) {
          const data = message.data

          if (data.status === 'completed' || data.status === 'failed') {
            ws.close()
            return
          }

          // Use structured file_progress data — works for ALL import types
          // (obsidian, generic, selective, zotero, revector)
          const fileProgress: Array<{
            file_id: string
            file_name: string
            status: string
            total_chunks: number
            processed_chunks: number
            error?: string
          }> = data.file_progress || []

          if (fileProgress.length > 0) {
            const statusMap: Record<string, DocumentProgress['status']> = {
              completed: 'success',
              failed: 'failed',
              cancelled: 'failed',
              processing: 'processing',
              embedding: 'processing',
              writing: 'processing',
            }
            setLocalDocuments(prev => {
              const prevMap = new Map(prev.map(d => [d.id, d]))
              fileProgress.forEach(fp => {
                prevMap.set(fp.file_id, {
                  id: fp.file_id,
                  name: fp.file_name,
                  status: statusMap[fp.status] || 'pending',
                  chunksTotal: fp.total_chunks,
                  chunksProcessed: fp.processed_chunks,
                  error: fp.error,
                })
              })
              return Array.from(prevMap.values())
            })
          }
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e)
      }
    }

    ws.onerror = () => {
      console.warn('WebSocket error (may be expected)')
    }

    return () => {
      ws.close()
    }
  }, [taskId])

  const getStatusIcon = (status: DocumentProgress['status']) => {
    switch (status) {
      case 'pending':
        return <Circle className="h-4 w-4 text-muted-foreground shrink-0" />
      case 'processing':
        return <Loader2 className="h-4 w-4 animate-spin text-primary shrink-0" />
      case 'success':
        return <CheckCircle className="h-4 w-4 text-green-500 shrink-0" />
      case 'failed':
        return <XCircle className="h-4 w-4 text-destructive shrink-0" />
    }
  }

  const getProgressBar = (doc: DocumentProgress) => {
    if (doc.chunksTotal === 0 && doc.status !== 'processing') return null

    const progress = doc.chunksTotal > 0 ? (doc.chunksProcessed / doc.chunksTotal) * 100 : 0
    return (
      <div className="mt-1">
        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
          {doc.chunksTotal > 0 ? (
            <div
              className={cn(
                'h-full transition-all duration-300',
                doc.status === 'failed' ? 'bg-destructive' : 'bg-primary'
              )}
              style={{ width: `${progress}%` }}
            />
          ) : (
            <div className="h-full bg-primary animate-pulse rounded-full" style={{ width: '60%' }} />
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">
          {doc.chunksTotal > 0 ? `${doc.chunksProcessed}/${doc.chunksTotal} chunks` : '处理中...'}
        </p>
      </div>
    )
  }

  const overallProgress =
    documentsTotal > 0 ? Math.round((documentsCompleted / documentsTotal) * 100) : 0

  const displayDocuments = taskId ? localDocuments : documents

  return (
    <div className="flex flex-col h-full border rounded-lg">
      <div className="p-3 border-b bg-muted/30">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium">导入进度</span>
          <span className="text-sm text-muted-foreground">
            {documentsCompleted}/{documentsTotal}
          </span>
        </div>
        <div className="h-2 bg-muted rounded-full overflow-hidden">
          <div
            className="h-full bg-primary transition-all duration-300"
            style={{ width: `${overallProgress}%` }}
          />
        </div>
      </div>
      <ScrollArea className="flex-1">
        {displayDocuments.length === 0 ? (
          <div className="text-center text-muted-foreground py-8 text-sm">
            暂无导入任务
          </div>
        ) : (
          <div className="p-2 space-y-2">
            {displayDocuments.map((doc) => (
              <div
                key={doc.id}
                className={cn(
                  'p-3 border rounded-lg',
                  doc.status === 'processing' && 'bg-primary/5 border-primary/20',
                  doc.status === 'success' && 'bg-green-500/5',
                  doc.status === 'failed' && 'bg-destructive/5'
                )}
              >
                <div className="flex items-start gap-2">
                  {getStatusIcon(doc.status)}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{doc.name}</p>
                    {doc.status === 'failed' && doc.error && (
                      <p className="text-xs text-destructive mt-0.5 flex items-center gap-1">
                        <AlertCircle className="h-3 w-3" />
                        {doc.error}
                      </p>
                    )}
                    {getProgressBar(doc)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
