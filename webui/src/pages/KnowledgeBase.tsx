import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useKBs, useCreateKB, useDeleteKB, useKBTopics, useRefreshTopics, useConsistencyCheck, useConsistencyRepair, useInitializeKB, useRepairAll, useCheckAndMarkFailed, useRevectorTask, useEmbeddingStats } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Plus, Trash2, Database, RefreshCw, Loader2, AlertTriangle, CheckCircle, Wrench, Trash, Sparkles, Pencil, WrenchIcon, HardDrive, Upload, Check } from 'lucide-react'
import { toast } from 'sonner'
import { KBEditDialog } from '@/components/KBEditDialog'
import { DangerConfirmDialog } from '@/components/DangerConfirmDialog'
import { LanceDBDialog } from './LanceDB'
import { ImportDialog } from '@/components/ImportDialog'
import type { KBInfo } from '@/types/api'

function KBDetailsPanel({ kb }: { kb: KBInfo }) {
  const navigate = useNavigate()
  const { data: topics, isLoading: topicsLoading } = useKBTopics(kb.id)
  const refreshTopics = useRefreshTopics()
  const { data: consistency, isLoading: consistencyLoading, refetch: refetchConsistency } = useConsistencyCheck(kb.id)
  const repairConsistency = useConsistencyRepair()
  const initializeKB = useInitializeKB()
  const checkAndMarkFailed = useCheckAndMarkFailed()
  const revectorTask = useRevectorTask()
  const { data: embeddingStats } = useEmbeddingStats(kb.id)
  const [isRefreshingTopics, setIsRefreshingTopics] = useState(false)
  const [isInitializeOpen, setIsInitializeOpen] = useState(false)

  const handleRefreshTopics = async () => {
    setIsRefreshingTopics(true)
    try {
      await refreshTopics.mutateAsync({ kbId: kb.id, req: { has_new_docs: true } })
      toast.success('Topics refreshed')
    } catch (error) {
      toast.error('Failed to refresh topics')
    } finally {
      setIsRefreshingTopics(false)
    }
  }

  const handleRepair = async () => {
    try {
      const result = await repairConsistency.mutateAsync(kb.id)
      toast.success(result.message)
      refetchConsistency()
    } catch (error) {
      toast.error('Repair failed')
    }
  }

  const handleCheckAndMarkFailed = async () => {
    try {
      const result = await checkAndMarkFailed.mutateAsync(kb.id)
      if (result.task_id) {
        toast.success(`任务已提交: ${result.task_id}`)
        navigate('/tasks')
      } else {
        toast.success(result.message)
        refetchConsistency()
      }
    } catch (error) {
      toast.error('Check and mark failed failed')
    }
  }

  const handleSyncAllMissing = async (maxChunks?: number) => {
    try {
      const result = await revectorTask.mutateAsync({
        kbId: kb.id,
        includePending: true,
        includeFailed: true,
        includeEmbedded: false,
        limit: maxChunks,
      })
      if (result.task_id) {
        toast.success(`任务已提交: ${result.task_id}`)
        navigate('/tasks')
      } else {
        toast.success(result.message)
        refetchConsistency()
      }
    } catch (error) {
      toast.error('Sync failed')
    }
  }

  const handleConfirmInitialize = async () => {
    try {
      const result = await initializeKB.mutateAsync({ kbId: kb.id, confirmationName: kb.id, asyncMode: true })
      if (result.task_id) {
        toast.success(`Initialization started: ${result.task_id}`)
      }
      setIsInitializeOpen(false)
    } catch (error: any) {
      const message = error?.response?.data?.detail || 'Initialization failed'
      toast.error(message)
      throw error
    }
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-muted-foreground" />
          <CardTitle>{kb.name || kb.id}</CardTitle>
          <Badge variant="secondary" className="capitalize">
            {kb.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="overview" className="w-full">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="topics">Topics</TabsTrigger>
            <TabsTrigger value="consistency">Consistency</TabsTrigger>
            <TabsTrigger value="maintenance">Maintenance</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-4">
            <div className="grid gap-2 text-sm md:grid-cols-2">
              <div>
                <span className="text-muted-foreground">ID: </span>
                <span className="font-mono">{kb.id}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Documents: </span>
                <span>{kb.row_count?.toLocaleString() || 0}</span>
              </div>
              {kb.chunk_strategy && (
                <div>
                  <span className="text-muted-foreground">Chunk: </span>
                  <span>{kb.chunk_strategy}</span>
                </div>
              )}
              {kb.description && (
                <div className="md:col-span-2">
                  <span className="text-muted-foreground">Description: </span>
                  <span>{kb.description}</span>
                </div>
              )}
            </div>

            {embeddingStats && (
              <div className="p-4 border rounded-lg bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">
                <div className="flex items-center gap-2 mb-3">
                  <Sparkles className="h-4 w-4 text-primary" />
                  <span className="text-sm font-medium">向量状态</span>
                </div>
                <div className="grid grid-cols-4 gap-3">
                  <div className="text-center p-2 bg-white dark:bg-slate-800 rounded-lg shadow-sm">
                    <p className="text-xs text-muted-foreground">总数</p>
                    <p className="text-lg font-semibold">{embeddingStats.total?.toLocaleString() || 0}</p>
                  </div>
                  <div className="text-center p-2 bg-green-50 dark:bg-green-900/20 rounded-lg shadow-sm">
                    <p className="text-xs text-green-600 dark:text-green-400">成功</p>
                    <p className="text-lg font-semibold text-green-600 dark:text-green-400">{embeddingStats.success?.toLocaleString() || 0}</p>
                  </div>
                  <div className="text-center p-2 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg shadow-sm">
                    <p className="text-xs text-yellow-600 dark:text-yellow-400">待处理</p>
                    <p className="text-lg font-semibold text-yellow-600 dark:text-yellow-400">{embeddingStats.pending?.toLocaleString() || 0}</p>
                  </div>
                  <div className="text-center p-2 bg-red-50 dark:bg-red-900/20 rounded-lg shadow-sm">
                    <p className="text-xs text-red-600 dark:text-red-400">失败</p>
                    <p className="text-lg font-semibold text-red-600 dark:text-red-400">{embeddingStats.failed?.toLocaleString() || 0}</p>
                  </div>
                </div>
              </div>
            )}
          </TabsContent>

          <TabsContent value="topics" className="space-y-4">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium">Knowledge Topics</h4>
              <Button variant="outline" size="sm" onClick={handleRefreshTopics} disabled={refreshTopics.isPending || isRefreshingTopics} title="刷新知识主题">
                {isRefreshingTopics || refreshTopics.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4 mr-1" />
                )}
                Refresh
              </Button>
            </div>
            {topicsLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : topics && topics.topics.length > 0 ? (
              <ScrollArea className="h-48">
                <div className="flex flex-wrap gap-2">
                  {topics.topics.map((topic, index) => (
                    <Badge key={index} variant="outline">
                      {topic}
                    </Badge>
                  ))}
                </div>
              </ScrollArea>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">No topics available</p>
            )}
            <p className="text-xs text-muted-foreground">{topics?.topic_count || 0} topics</p>
          </TabsContent>

          <TabsContent value="consistency" className="space-y-4">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium">一致性检查</h4>
              <Button variant="outline" size="sm" onClick={() => refetchConsistency()} disabled={consistencyLoading}>
                {consistencyLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-1" />}
                检查
              </Button>
            </div>

            {consistency ? (
              <div className="space-y-4">
                {consistency.status === "ok" ? (
                  <div className="flex items-center gap-2 p-4 bg-green-50 rounded-lg">
                    <CheckCircle className="h-5 w-5 text-green-500" />
                    <span className="text-sm font-medium text-green-700">知识库正常</span>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {/* Summary Stats */}
                    <div className="grid grid-cols-3 gap-2 text-xs">
                      <div className="p-2 bg-muted rounded">
                        <p className="text-muted-foreground">文档数</p>
                        <p className="font-medium">{consistency.summary?.doc_count}</p>
                      </div>
                      <div className="p-2 bg-muted rounded">
                        <p className="text-muted-foreground">LanceDB</p>
                        <p className="font-medium">{consistency.summary?.lance_rows?.toLocaleString()}</p>
                      </div>
                      <div className="p-2 bg-muted rounded">
                        <p className="text-muted-foreground">SQLite</p>
                        <p className="font-medium">{consistency.summary?.chunk_count_actual?.toLocaleString()}</p>
                      </div>
                    </div>

                    {/* Embedding Stats Breakdown */}
                    {consistency.embedding_stats && (
                      <div className="p-3 border rounded-lg">
                        <div className="flex items-center gap-2 mb-2">
                          <Database className="h-4 w-4 text-muted-foreground" />
                          <span className="text-sm font-medium">向量状态明细</span>
                        </div>
                        <div className="grid grid-cols-3 gap-2 text-xs">
                          <div className="p-2 bg-green-50 rounded">
                            <p className="text-muted-foreground">✓ LanceDB 向量数</p>
                            <p className="font-medium text-green-700">{consistency.summary?.lance_rows?.toLocaleString()}</p>
                          </div>
                          <div className="p-2 bg-muted rounded">
                            <p className="text-muted-foreground">SQLite Chunk 总数</p>
                            <p className="font-medium">{consistency.summary?.chunk_count_actual?.toLocaleString()}</p>
                          </div>
                          <div className="p-2 bg-red-50 rounded">
                            <p className="text-muted-foreground">✗ 缺失向量数</p>
                            <p className="font-medium text-red-700">{consistency.vector_integrity?.missing_count?.toLocaleString()}</p>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Doc Stats Issues */}
                    {!consistency.doc_stats?.accurate && (
                      <div className="p-3 border rounded-lg">
                        <div className="flex items-center gap-2 mb-2">
                          <AlertTriangle className="h-4 w-4 text-yellow-500" />
                          <span className="text-sm font-medium">文档统计不准确</span>
                        </div>
                        <p className="text-xs text-muted-foreground mb-2">
                          {consistency.doc_stats?.mismatched_count} 个文档的 chunk_count 记录与实际不符
                        </p>
                        <ScrollArea className="h-24">
                          <ul className="text-xs space-y-1">
                            {consistency.doc_stats?.issues?.slice(0, 10).map((issue: any, idx: number) => (
                              <li key={idx} className="flex justify-between">
                                <span className="truncate max-w-[150px]">{issue.source_file || issue.doc_id}</span>
                                <span className="font-mono ml-2">{issue.stored} → {issue.actual}</span>
                              </li>
                            ))}
                          </ul>
                        </ScrollArea>
                      </div>
                    )}

                    {/* Vector Integrity Issues */}
                    {consistency.vector_integrity?.issues?.length > 0 && (
                      <div className="p-3 border rounded-lg">
                        <div className="flex items-center gap-2 mb-2">
                          <AlertTriangle className="h-4 w-4 text-orange-500" />
                          <span className="text-sm font-medium">向量完整性问题</span>
                        </div>
                        <ul className="text-xs space-y-1">
                          {consistency.vector_integrity?.issues?.map((issue: any, idx: number) => (
                            <li key={idx} className="text-muted-foreground">• {issue.description}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Recommendations */}
                    {consistency.recommendations?.length > 0 && (
                      <div className="p-3 bg-blue-50 rounded-lg">
                        <p className="text-xs font-medium text-blue-700 mb-2">建议操作</p>
                        <ul className="text-xs space-y-1">
                          {consistency.recommendations?.map((rec: any, idx: number) => (
                            <li key={idx} className="text-blue-600">• {rec.description}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Fix Button */}
                    <Button size="sm" variant="default" onClick={handleRepair} disabled={repairConsistency.isPending}>
                      {repairConsistency.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wrench className="h-4 w-4 mr-1" />}
                      修正文档统计
                    </Button>

                    {/* Check and Mark Failed Button */}
                    <Button size="sm" variant="outline" onClick={handleCheckAndMarkFailed} disabled={checkAndMarkFailed.isPending}>
                      {checkAndMarkFailed.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4 mr-1" />}
                      检查并标记失败
                    </Button>

                    {/* Sync All Missing Button */}
                    {(consistency.vector_integrity?.missing_count ?? 0) > 0 && (
                      <Button size="sm" variant="default" onClick={() => handleSyncAllMissing()} disabled={revectorTask.isPending}>
                        {revectorTask.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-1" />}
                        同步所有缺失向量 ({consistency.vector_integrity?.missing_count?.toLocaleString()})
                      </Button>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">点击"检查"开始一致性检查</p>
            )}
          </TabsContent>

          <TabsContent value="maintenance" className="space-y-4">
            <div className="grid gap-3">
              <div className="flex items-center justify-between p-3 border rounded-lg">
                <div className="flex items-center gap-3">
                  <Sparkles className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium">Initialize KB</p>
                    <p className="text-xs text-muted-foreground">Clear all data in this knowledge base</p>
                  </div>
                </div>
                <Button variant="destructive" size="sm" onClick={() => setIsInitializeOpen(true)} disabled={initializeKB.isPending} title="清空知识库所有数据">
                  {initializeKB.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash className="h-4 w-4 mr-1" />}
                  Initialize
                </Button>
              </div>
            </div>
          </TabsContent>
        </Tabs>
        <DangerConfirmDialog
          open={isInitializeOpen}
          onOpenChange={setIsInitializeOpen}
          title="初始化知识库"
          description="此操作将清空知识库的所有数据，且无法恢复。"
          kbName={kb.id}
          onConfirm={handleConfirmInitialize}
          variant="initialize"
        />
      </CardContent>
    </Card>
  )
}

function KBListItem({
  kb,
  isSelected,
  onSelect,
  onDeleteSuccess,
}: {
  kb: KBInfo
  isSelected: boolean
  onSelect: () => void
  onDeleteSuccess?: () => void
}) {
  const { data: kbTopics } = useKBTopics(kb.id)
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [isDeleteOpen, setIsDeleteOpen] = useState(false)
  const [isLanceOpen, setIsLanceOpen] = useState(false)
  const [isImportOpen, setIsImportOpen] = useState(false)
  const deleteKB = useDeleteKB()

  const handleConfirmDelete = async () => {
    await deleteKB.mutateAsync({ kbId: kb.id, confirmationName: kb.id })
    onDeleteSuccess?.()
  }

  return (
    <>
      <div
        className={`p-3 border rounded-lg cursor-pointer transition-colors ${
          isSelected ? 'border-primary bg-primary/5' : 'hover:border-primary/50'
        }`}
        onClick={onSelect}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium">{kb.name || kb.id}</span>
            <Badge variant="secondary" className="text-xs">
              {kb.row_count?.toLocaleString() || 0} docs
            </Badge>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => { e.stopPropagation(); setIsImportOpen(true) }}
              title="导入文档到该知识库"
            >
              <Upload className="h-4 w-4 text-muted-foreground" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => { e.stopPropagation(); setIsLanceOpen(true) }}
              title="查看 LanceDB 数据"
            >
              <HardDrive className="h-4 w-4 text-muted-foreground" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => { e.stopPropagation(); setIsEditOpen(true) }}
              title="编辑知识库信息"
            >
              <Pencil className="h-4 w-4 text-muted-foreground" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => { e.stopPropagation(); setIsDeleteOpen(true) }}
              title="删除知识库"
            >
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          </div>
        </div>
      </div>
      <KBEditDialog
        open={isEditOpen}
        onOpenChange={setIsEditOpen}
        kb={kb}
        topics={kbTopics}
      />
      <DangerConfirmDialog
        open={isDeleteOpen}
        onOpenChange={setIsDeleteOpen}
        title="删除知识库"
        description="此操作将永久删除知识库及其所有数据，且无法恢复。"
        kbName={kb.id}
        onConfirm={handleConfirmDelete}
        variant="delete"
      />
      <LanceDBDialog
        open={isLanceOpen}
        onOpenChange={setIsLanceOpen}
        kbId={kb.id}
      />
      <ImportDialog
        open={isImportOpen}
        onOpenChange={setIsImportOpen}
        kbId={kb.id}
        kbName={kb.name || kb.id}
      />
    </>
  )
}

export function KnowledgeBase() {
  const { data: kbs, isLoading } = useKBs()
  const createKB = useCreateKB()
  const repairAll = useRepairAll()

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [newKB, setNewKB] = useState<Partial<KBInfo>>({
    id: '',
    name: '',
    description: '',
  })
  const [selectedKBId, setSelectedKBId] = useState<string | null>(null)

  const handleCreate = async () => {
    if (!newKB.id) return
    try {
      await createKB.mutateAsync(newKB as KBInfo)
      setIsCreateOpen(false)
      setNewKB({ id: '', name: '', description: '' })
    } catch (error) {
      console.error('Failed to create KB:', error)
    }
  }

  const handleRepairAll = async () => {
    if (!confirm('Repair consistency for all knowledge bases?')) return
    try {
      const result = await repairAll.mutateAsync()
      toast.success(result.message)
    } catch (error) {
      toast.error('Repair all failed')
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Knowledge Base</h1>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={handleRepairAll}
            disabled={repairAll.isPending || !kbs?.length}
            title="修复所有知识库的一致性问题"
          >
            {repairAll.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <WrenchIcon className="mr-2 h-4 w-4" />}
            Repair All
          </Button>
        </div>

        <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
          <DialogTrigger asChild>
            <Button title="创建新的知识库">
              <Plus className="mr-2 h-4 w-4" />
              Create KB
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create Knowledge Base</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="kb-id">ID</Label>
                <Input
                  id="kb-id"
                  value={newKB.id}
                  onChange={(e) =>
                    setNewKB({ ...newKB, id: e.target.value.toLowerCase().replace(/\s+/g, '_') })
                  }
                  placeholder="my_knowledge_base"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="kb-name">Name</Label>
                <Input
                  id="kb-name"
                  value={newKB.name}
                  onChange={(e) => setNewKB({ ...newKB, name: e.target.value })}
                  placeholder="My Knowledge Base"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="kb-desc">Description</Label>
                <Input
                  id="kb-desc"
                  value={newKB.description}
                  onChange={(e) =>
                    setNewKB({ ...newKB, description: e.target.value })
                  }
                  placeholder="Optional description"
                />
              </div>
              <Button onClick={handleCreate} disabled={!newKB.id || createKB.isPending}>
                {createKB.isPending ? 'Creating...' : 'Create'}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : kbs && kbs.length > 0 ? (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="space-y-4">
            <h2 className="text-lg font-semibold">Knowledge Bases</h2>
            <div className="space-y-2">
              {kbs.map((kb) => (
                <KBListItem
                  key={kb.id}
                  kb={kb}
                  isSelected={selectedKBId === kb.id}
                  onSelect={() => setSelectedKBId(kb.id)}
                  onDeleteSuccess={() => {
                    if (selectedKBId === kb.id) {
                      setSelectedKBId(null)
                    }
                  }}
                />
              ))}
            </div>
          </div>
          <div>
            {selectedKBId ? (
              <KBDetailsPanel kb={kbs.find(kb => kb.id === selectedKBId)!} />
            ) : (
              <div className="flex items-center justify-center h-64 border rounded-lg">
                <p className="text-muted-foreground">Select a knowledge base to view details</p>
              </div>
            )}
          </div>
        </div>
      ) : (
        <p className="text-muted-foreground">No knowledge bases found</p>
      )}
    </div>
  )
}