import { useState } from 'react'
import { useKBTasks, useCancelTask, usePauseTask, useResumeTask, usePauseAllTasks, useResumeAllTasks, useDeleteAllTasks, useCleanupTasks } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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
  DialogTrigger,
} from '@/components/ui/dialog'
import { Pause, Play, X, RefreshCw, Loader2, PauseCircle, PlayCircle, Trash2, Wrench } from 'lucide-react'
import { toast } from 'sonner'
import type { TaskResponse } from '@/types/api'

function TaskCard({ task }: { task: TaskResponse }) {
  const cancelTask = useCancelTask()
  const pauseTask = usePauseTask()
  const resumeTask = useResumeTask()

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
    } catch (error) {
      console.error('Failed to pause:', error)
    }
  }

  const handleResume = async () => {
    try {
      await resumeTask.mutateAsync(task.task_id)
    } catch (error) {
      console.error('Failed to resume:', error)
    }
  }

  const handleCancel = async () => {
    if (!confirm('Cancel this task?')) return
    try {
      await cancelTask.mutateAsync(task.task_id)
    } catch (error) {
      console.error('Failed to cancel:', error)
    }
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-mono">{task.task_id.slice(0, 8)}...</CardTitle>
            <Badge className={statusColors[task.status]}>{task.status}</Badge>
          </div>
          <div className="flex gap-1">
            {task.status === 'running' && (
              <Button variant="ghost" size="icon" onClick={handlePause}>
                <Pause className="h-4 w-4" />
              </Button>
            )}
            {task.status === 'paused' && (
              <Button variant="ghost" size="icon" onClick={handleResume}>
                <Play className="h-4 w-4" />
              </Button>
            )}
            {(task.status === 'pending' || task.status === 'running' || task.status === 'paused') && (
              <Button variant="ghost" size="icon" onClick={handleCancel}>
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">KB:</span>
            <span className="font-mono">{task.kb_id}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Progress:</span>
            <span>{task.progress}%</span>
          </div>
          <p className="text-xs text-muted-foreground">{task.message}</p>
          {task.error && (
            <p className="text-xs text-red-500">Error: {task.error}</p>
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
    if (!confirm(`Delete all ${statusFilter === 'all' ? '' : statusFilter} tasks?${cleanup ? ' This will also clean up knowledge base data.' : ''}`)) return
    try {
      const result = await deleteAllTasks.mutateAsync({ status: statusFilter, cleanup })
      toast.success(result.message)
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
        <h1 className="text-2xl font-bold">Tasks</h1>
        <div className="flex gap-2">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Status</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
              <SelectItem value="running">Running</SelectItem>
              <SelectItem value="completed">Completed</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          
          <Button variant="outline" onClick={handlePauseAll} disabled={pauseAllTasks.isPending}>
            {pauseAllTasks.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <PauseCircle className="mr-2 h-4 w-4" />}
            Pause All
          </Button>
          
          <Button variant="outline" onClick={handleResumeAll} disabled={resumeAllTasks.isPending}>
            {resumeAllTasks.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <PlayCircle className="mr-2 h-4 w-4" />}
            Resume All
          </Button>

          <Dialog open={batchDialog === 'delete'} onOpenChange={(open) => !open && setBatchDialog('')}>
            <DialogTrigger asChild>
              <Button variant="destructive" onClick={() => setBatchDialog('delete')}>
                <Trash2 className="mr-2 h-4 w-4" />
                Delete
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Delete Tasks</DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  This will delete all {statusFilter === 'all' ? '' : statusFilter} tasks. You can also choose to clean up associated knowledge base data.
                </p>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => { handleDeleteAll(false); setBatchDialog('') }}>
                    Delete Tasks Only
                  </Button>
                  <Button variant="destructive" onClick={() => { handleDeleteAll(true); setBatchDialog('') }}>
                    Delete with Cleanup
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>

          <Button variant="outline" onClick={handleCleanup} disabled={cleanupTasks.isPending} title="Clean up orphan tasks">
            {cleanupTasks.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Wrench className="mr-2 h-4 w-4" />}
            Cleanup
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : tasks && tasks.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {tasks.map((task) => (
            <TaskCard key={task.task_id} task={task} />
          ))}
        </div>
      ) : (
        <p className="text-center text-muted-foreground">No tasks found</p>
      )}
    </div>
  )
}