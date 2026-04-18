import { useState } from 'react'
import { useKBTasks, useCancelTask, usePauseTask, useResumeTask, usePauseAllTasks, useResumeAllTasks, useDeleteAllTasks, useCleanupTasks, useTask, useDeleteTask } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Pause, Play, X, RefreshCw, Loader2, PauseCircle, PlayCircle, Trash2, Wrench, Eye, Info, AlertTriangle, Wifi } from 'lucide-react'
import { toast } from 'sonner'
import type { TaskResponse } from '@/types/api'
import { useTaskWebSocket } from '@/lib/websocket'

interface TaskDetailDialogProps {
  taskId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

function TaskDetailDialog({ taskId, open, onOpenChange }: TaskDetailDialogProps) {
  const { data: task, isLoading } = useTask(taskId)

  if (!open) return null

  const fileProgress = task?.file_progress || task?.result?.file_progress || []

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'bg-green-500'
      case 'failed': return 'bg-red-500'
      case 'processing': return 'bg-blue-500'
      case 'embedding': return 'bg-purple-500'
      case 'writing': return 'bg-cyan-500'
      case 'cancelled': return 'bg-gray-500'
      case 'pending': return 'bg-yellow-500'
      default: return 'bg-gray-400'
    }
  }

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'completed': return '完成'
      case 'failed': return '失败'
      case 'processing': return '解析中'
      case 'embedding': return '向量化'
      case 'writing': return '写入中'
      case 'cancelled': return '已取消'
      case 'pending': return '等待中'
      default: return status
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Eye className="h-5 w-5" />
            Task Details
          </DialogTitle>
          <DialogDescription>
            Task ID: {taskId}
          </DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : task ? (
          <ScrollArea className="h-[70vh]">
            <div className="space-y-4 p-1">
              {task.task_type === 'initialize' ? (
                <div className="border rounded-lg p-4 bg-orange-50 dark:bg-orange-950/20">
                  <div className="flex items-center gap-2 mb-3">
                    <Badge variant="outline" className="bg-orange-100 dark:bg-orange-900/30">Initialize</Badge>
                    <span className="text-sm text-muted-foreground">Knowledge Base Initialization</span>
                  </div>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-sm">Status</span>
                      <Badge className={getStatusColor(task.status)}>{task.status}</Badge>
                    </div>
                    {task.message && (
                      <div className="flex items-center justify-between">
                        <span className="text-sm">Current Step</span>
                        <span className="text-sm font-medium">{task.message}</span>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div>
                    <Label className="text-muted-foreground text-xs">Status</Label>
                    <div className="mt-1">
                      <Badge className={getStatusColor(task.status)}>
                        {task.status}
                      </Badge>
                    </div>
                  </div>
                  <div>
                    <Label className="text-muted-foreground text-xs">Progress</Label>
                    <p className="font-medium">{task.progress}%</p>
                  </div>
                  <div>
                    <Label className="text-muted-foreground text-xs">Files</Label>
                    <p className="font-medium">{task.result?.files ?? 0}</p>
                  </div>
                  <div>
                    <Label className="text-muted-foreground text-xs">Failed</Label>
                    <p className="font-medium text-red-500">{task.result?.failed ?? 0}</p>
                  </div>
                </div>
              )}

              {task.message && task.task_type !== 'initialize' && (
                <div>
                  <Label className="text-muted-foreground text-xs">Current Status</Label>
                  <p className="text-sm mt-1">{task.message}</p>
                </div>
              )}

              {fileProgress.length > 0 && (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <Label className="text-muted-foreground text-xs">File Progress ({fileProgress.length} files)</Label>
                    {task.result?.processed_chunks !== undefined && task.result?.total_chunks !== undefined && (
                      <span className="text-xs text-muted-foreground">
                        {task.result.processed_chunks} / {task.result.total_chunks} chunks
                      </span>
                    )}
                  </div>
                  <div className="space-y-2 max-h-80 overflow-y-auto">
                    {fileProgress.map((file: any, idx: number) => (
                      <div key={file.file_id || idx} className="border rounded-lg p-3 text-sm">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <Badge className={getStatusColor(file.status)} variant="outline">
                              {getStatusLabel(file.status)}
                            </Badge>
                            <span className="truncate font-medium" title={file.file_name}>
                              {file.file_name}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            {file.db_written && (
                              <span className="text-xs text-green-600" title="Written to database">DB</span>
                            )}
                            {file.error && (
                              <span className="text-xs text-red-500" title={file.error}>Error</span>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-1.5 bg-secondary rounded-full overflow-hidden">
                            <div
                              className={`h-full transition-all ${file.status === 'embedding' ? 'bg-purple-500' : file.status === 'writing' ? 'bg-cyan-500' : 'bg-primary'}`}
                              style={{
                                width: file.total_chunks > 0
                                  ? `${(file.processed_chunks / file.total_chunks) * 100}%`
                                  : '0%'
                              }}
                            />
                          </div>
                          <span className="text-xs text-muted-foreground w-24 text-right">
                            {file.processed_chunks} / {file.total_chunks} chunks
                          </span>
                        </div>
                        {file.error && (
                          <p className="text-xs text-red-500 mt-1 truncate" title={file.error}>
                            {file.error}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {task.error && (
                <div>
                  <Label className="text-destructive text-xs">Error</Label>
                  <p className="text-sm text-destructive mt-1 p-3 bg-destructive/10 rounded-lg">
                    {task.error}
                  </p>
                </div>
              )}
            </div>
          </ScrollArea>
        ) : (
          <p className="text-center text-muted-foreground py-8">Task not found</p>
        )}
      </DialogContent>
    </Dialog>
  )
}

interface DeleteTaskDialogProps {
  task: TaskResponse | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: (cleanup: boolean) => void
  isDeleting: boolean
}

function DeleteTaskDialog({ task, open, onOpenChange, onConfirm, isDeleting }: DeleteTaskDialogProps) {
  const [confirmText, setConfirmText] = useState('')
  const taskId = task?.task_id || ''

  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen) setConfirmText('')
    onOpenChange(newOpen)
  }

  const isConfirmed = confirmText === taskId

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-5 w-5" />
            Delete Task
          </DialogTitle>
          <DialogDescription>
            This action cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="p-3 bg-muted rounded-lg">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div><span className="text-muted-foreground">KB:</span> <span className="font-mono">{task?.kb_id}</span></div>
              <div><span className="text-muted-foreground">Status:</span> <Badge>{task?.status}</Badge></div>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="delete-confirm">Type task ID to confirm deletion</Label>
            <Input
              id="delete-confirm"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder={taskId}
              className="font-mono"
            />
            <p className="text-xs text-muted-foreground">
              Task ID: <code className="bg-muted px-1 rounded">{taskId}</code>
            </p>
          </div>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={isDeleting}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => onConfirm(false)}
            disabled={!isConfirmed || isDeleting}
          >
            {isDeleting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Delete Task
          </Button>
          {task?.status === 'failed' || task?.status === 'cancelled' ? (
            <Button
              variant="destructive"
              onClick={() => onConfirm(true)}
              disabled={!isConfirmed || isDeleting}
              className="bg-orange-600 hover:bg-orange-700"
            >
              {isDeleting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Delete + Cleanup
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function TaskCard({ task, onShowDetails }: { task: TaskResponse; onShowDetails: (taskId: string) => void }) {
  const cancelTask = useCancelTask()
  const pauseTask = usePauseTask()
  const resumeTask = useResumeTask()
  const deleteTask = useDeleteTask()
  const [deleteDialog, setDeleteDialog] = useState(false)

  const statusColors: Record<string, string> = {
    pending: 'bg-yellow-500',
    running: 'bg-blue-500',
    completed: 'bg-green-500',
    failed: 'bg-red-500',
    cancelled: 'bg-gray-500',
    paused: 'bg-orange-500',
  }

  const handlePause = async () => {
    try {
      await pauseTask.mutateAsync(task.task_id)
      toast.success('Task paused')
    } catch (error) {
      toast.error('Failed to pause task')
    }
  }

  const handleResume = async () => {
    try {
      await resumeTask.mutateAsync(task.task_id)
      toast.success('Task resumed')
    } catch (error) {
      toast.error('Failed to resume task')
    }
  }

  const handleCancel = async () => {
    try {
      await cancelTask.mutateAsync(task.task_id)
      toast.success('Task cancelled')
    } catch (error) {
      toast.error('Failed to cancel task')
    }
  }

  return (
    <>
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => onShowDetails(task.task_id)}>
                <Info className="h-4 w-4" />
              </Button>
              <CardTitle className="text-sm font-mono">{task.task_id.slice(0, 8)}...</CardTitle>
              <Badge className={statusColors[task.status]}>{task.status}</Badge>
            </div>
            <div className="flex gap-1">
              {task.status === 'running' && (
                <Button variant="ghost" size="icon" onClick={handlePause} title="Pause task">
                  <Pause className="h-4 w-4" />
                </Button>
              )}
              {task.status === 'paused' && (
                <Button variant="ghost" size="icon" onClick={handleResume} title="Resume task">
                  <Play className="h-4 w-4" />
                </Button>
              )}
              {(task.status === 'pending' || task.status === 'running' || task.status === 'paused') && (
                <Button variant="ghost" size="icon" onClick={handleCancel} title="Cancel task">
                  <X className="h-4 w-4" />
                </Button>
              )}
              {(task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') && (
                <Button variant="ghost" size="icon" onClick={() => setDeleteDialog(true)} title="Delete task">
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">KB:</span>
              <span className="font-mono">{task.kb_id || 'N/A'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Progress:</span>
              <span>{task.progress}%</span>
            </div>
            <p className="text-xs text-muted-foreground line-clamp-2">{task.message}</p>
            {task.error && (
              <p className="text-xs text-red-500 line-clamp-2">Error: {task.error}</p>
            )}
          </div>
          {task.status === 'running' && (
            <div className="mt-3 h-2 w-full rounded-full bg-secondary">
              <div
                className="h-2 rounded-full bg-primary transition-all"
                style={{ width: `${task.progress}%` }}
              />
            </div>
          )}
        </CardContent>
      </Card>

      <DeleteTaskDialog
        task={task}
        open={deleteDialog}
        onOpenChange={setDeleteDialog}
        onConfirm={async (cleanup) => {
          try {
            await deleteTask.mutateAsync({ taskId: task.task_id, cleanup })
            toast.success('Task deleted')
            setDeleteDialog(false)
          } catch (error) {
            toast.error('Failed to delete task')
          }
        }}
        isDeleting={deleteTask.isPending}
      />
    </>
  )
}

export function Tasks() {
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const { data: tasks, isLoading, refetch } = useKBTasks(
    undefined,
    statusFilter === 'all' ? undefined : statusFilter
  )
  const pauseAllTasks = usePauseAllTasks()
  const resumeAllTasks = useResumeAllTasks()
  const deleteAllTasks = useDeleteAllTasks()
  const cleanupTasks = useCleanupTasks()
  const [batchDialog, setBatchDialog] = useState<string>('')
  const [detailDialog, setDetailDialog] = useState<string | null>(null)
  const [deleteAllConfirm, setDeleteAllConfirm] = useState('')

  useTaskWebSocket(true)

  const handlePauseAll = async () => {
    try {
      const result = await pauseAllTasks.mutateAsync(statusFilter === 'all' ? 'running' : statusFilter)
      toast.success(result.message)
      refetch()
    } catch (error) {
      toast.error('Failed to pause tasks')
    }
  }

  const handleResumeAll = async () => {
    try {
      const result = await resumeAllTasks.mutateAsync()
      toast.success(result.message)
      refetch()
    } catch (error) {
      toast.error('Failed to resume tasks')
    }
  }

  const handleDeleteAll = async (cleanup: boolean) => {
    try {
      const result = await deleteAllTasks.mutateAsync({ status: statusFilter, cleanup })
      toast.success(result.message)
      setBatchDialog('')
      refetch()
    } catch (error) {
      toast.error('Failed to delete tasks')
    }
  }

  const handleCleanup = async () => {
    try {
      const result = await cleanupTasks.mutateAsync()
      toast.success(result.message)
      refetch()
    } catch (error) {
      toast.error('Failed to cleanup tasks')
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">Task Management</h1>
          <Badge variant="outline" className="gap-1">
            <Wifi className="h-3 w-3" />
            Live
          </Badge>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Status</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
              <SelectItem value="running">Running</SelectItem>
              <SelectItem value="completed">Completed</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
              <SelectItem value="cancelled">Cancelled</SelectItem>
              <SelectItem value="paused">Paused</SelectItem>
            </SelectContent>
          </Select>

          <Button variant="outline" onClick={() => refetch()} title="Refresh the task list">
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>

          <div className="relative group">
            <Button variant="outline" onClick={handlePauseAll} disabled={pauseAllTasks.isPending} title="Pause all running tasks">
              {pauseAllTasks.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <PauseCircle className="mr-2 h-4 w-4" />}
              Pause All
            </Button>
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-popover border rounded-lg text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none z-50 shadow-md">
              Pause all running tasks. Tasks can be resumed later.
              <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-popover"></div>
            </div>
          </div>

          <div className="relative group">
            <Button variant="outline" onClick={handleResumeAll} disabled={resumeAllTasks.isPending} title="Resume all paused tasks">
              {resumeAllTasks.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <PlayCircle className="mr-2 h-4 w-4" />}
              Resume All
            </Button>
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-popover border rounded-lg text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none z-50 shadow-md">
              Resume all paused tasks.
              <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-popover"></div>
            </div>
          </div>

          <div className="relative group">
            <Button variant="destructive" onClick={() => setBatchDialog('delete')} title="Delete tasks with confirmation">
              <Trash2 className="mr-2 h-4 w-4" />
              Delete
            </Button>
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-popover border rounded-lg text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none z-50 shadow-md">
              Delete selected tasks. Requires typing "delete" to confirm.
              <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-popover"></div>
            </div>
          </div>

          <div className="relative group">
            <Button variant="outline" onClick={handleCleanup} disabled={cleanupTasks.isPending} title="Clean up orphan tasks">
              {cleanupTasks.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Wrench className="mr-2 h-4 w-4" />}
              Cleanup
            </Button>
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-popover border rounded-lg text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none z-50 shadow-md">
              Remove orphan tasks (tasks whose processes have crashed).
              <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-popover"></div>
            </div>
          </div>
        </div>
      </div>

      <Dialog open={batchDialog === 'delete'} onOpenChange={(open) => !open && setBatchDialog('')}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />
              Delete Tasks
            </DialogTitle>
            <DialogDescription>
              This will delete all {statusFilter === 'all' ? 'tasks' : `${statusFilter} tasks`}. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="p-3 bg-muted rounded-lg text-sm">
              <p><strong>Status filter:</strong> {statusFilter === 'all' ? 'All tasks' : statusFilter}</p>
              <p className="text-muted-foreground mt-1">
                {statusFilter === 'failed' || statusFilter === 'cancelled' ? 'These tasks may have cleanup data available.' : ''}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="batch-delete-confirm">Type "delete" to confirm</Label>
              <Input
                id="batch-delete-confirm"
                value={deleteAllConfirm}
                onChange={(e) => setDeleteAllConfirm(e.target.value)}
                placeholder="delete"
                className="font-mono"
              />
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => { setBatchDialog(''); setDeleteAllConfirm('') }}>
              Cancel
            </Button>
            <Button
              variant="outline"
              onClick={() => { handleDeleteAll(false); setDeleteAllConfirm('') }}
              disabled={deleteAllConfirm !== 'delete'}
            >
              Delete Tasks Only
            </Button>
            <Button
              variant="destructive"
              onClick={() => { handleDeleteAll(true); setDeleteAllConfirm('') }}
              disabled={deleteAllConfirm !== 'delete'}
            >
              Delete + Cleanup KB Data
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <TaskDetailDialog
        taskId={detailDialog || ''}
        open={detailDialog !== null}
        onOpenChange={(open) => !open && setDetailDialog(null)}
      />

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : tasks && tasks.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {tasks.map((task) => (
            <TaskCard key={task.task_id} task={task} onShowDetails={setDetailDialog} />
          ))}
        </div>
      ) : (
        <div className="text-center py-12">
          <p className="text-muted-foreground">No tasks found</p>
          <p className="text-sm text-muted-foreground mt-1">
            {statusFilter === 'all' ? 'Start an import or query to see tasks here' : `No ${statusFilter} tasks`}
          </p>
        </div>
      )}
    </div>
  )
}
