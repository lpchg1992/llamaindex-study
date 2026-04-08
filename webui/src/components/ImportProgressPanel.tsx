import { CheckCircle, Circle, Loader2, XCircle, AlertCircle } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
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
}

export function ImportProgressPanel({
  documents,
  documentsTotal,
  documentsCompleted,
}: ImportProgressPanelProps) {
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
    if (doc.chunksTotal === 0) return null

    const progress = (doc.chunksProcessed / doc.chunksTotal) * 100
    return (
      <div className="mt-1">
        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
          <div
            className={cn(
              'h-full transition-all duration-300',
              doc.status === 'failed' ? 'bg-destructive' : 'bg-primary'
            )}
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">
          {doc.chunksProcessed}/{doc.chunksTotal} chunks
        </p>
      </div>
    )
  }

  const overallProgress =
    documentsTotal > 0 ? Math.round((documentsCompleted / documentsTotal) * 100) : 0

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
        {documents.length === 0 ? (
          <div className="text-center text-muted-foreground py-8 text-sm">
            暂无导入任务
          </div>
        ) : (
          <div className="p-2 space-y-2">
            {documents.map((doc) => (
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
