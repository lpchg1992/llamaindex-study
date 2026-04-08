import { useState } from 'react'
import { useKBs, useCreateKB, useDeleteKB, useKBTopics, useRefreshTopics, useConsistencyCheck, useConsistencyRepair, useInitializeKB, useRebuildDocstore, useRepairAll } from '@/api/hooks'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Plus, Trash2, Database, RefreshCw, Loader2, AlertTriangle, CheckCircle, Wrench, Trash, FileText, Sparkles, Pencil, WrenchIcon } from 'lucide-react'
import { toast } from 'sonner'
import { KBEditDialog } from '@/components/KBEditDialog'
import { DangerConfirmDialog } from '@/components/DangerConfirmDialog'
import type { KBInfo } from '@/types/api'

function KBDetailsPanel({ kb }: { kb: KBInfo }) {
  const { data: topics, isLoading: topicsLoading, refetch: refetchTopics } = useKBTopics(kb.id)
  const refreshTopics = useRefreshTopics()
  const { data: consistency, isLoading: consistencyLoading } = useConsistencyCheck(kb.id)
  const repairConsistency = useConsistencyRepair()
  const initializeKB = useInitializeKB()
  const rebuildDocstore = useRebuildDocstore()

  const [isRefreshingTopics, setIsRefreshingTopics] = useState(false)
  const [repairMode, setRepairMode] = useState<string>('dry')
  const [isInitializeOpen, setIsInitializeOpen] = useState(false)
  const [isRebuildOpen, setIsRebuildOpen] = useState(false)

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
      const result = await repairConsistency.mutateAsync({ kbId: kb.id, mode: repairMode })
      toast.success(result.message)
    } catch (error) {
      toast.error('Repair failed')
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

  const handleConfirmRebuild = async () => {
    try {
      const result = await rebuildDocstore.mutateAsync({ kbId: kb.id, confirmationName: kb.id })
      toast.success(`Rebuilt ${result.nodes_rebuilt} nodes`)
      setIsRebuildOpen(false)
    } catch (error: any) {
      const message = error?.response?.data?.detail || 'Rebuild failed'
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
          </TabsContent>

          <TabsContent value="topics" className="space-y-4">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium">Knowledge Topics</h4>
              <Button variant="outline" size="sm" onClick={handleRefreshTopics} disabled={refreshTopics.isPending || isRefreshingTopics}>
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
              <h4 className="text-sm font-medium">Consistency Check</h4>
              <Button variant="outline" size="sm" onClick={() => refetchTopics()} disabled={consistencyLoading}>
                {consistencyLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-1" />}
                Check
              </Button>
            </div>
            {consistency ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  {consistency.is_consistent ? (
                    <>
                      <CheckCircle className="h-5 w-5 text-green-500" />
                      <span className="text-sm font-medium text-green-600">Consistent</span>
                    </>
                  ) : (
                    <>
                      <AlertTriangle className="h-5 w-5 text-yellow-500" />
                      <span className="text-sm font-medium text-yellow-600">Issues Found</span>
                    </>
                  )}
                </div>
                {consistency.issues?.length > 0 && (
                  <ScrollArea className="h-32">
                    <ul className="text-sm space-y-1">
                      {consistency.issues.map((issue, index) => (
                        <li key={index} className="text-muted-foreground">• {issue}</li>
                      ))}
                    </ul>
                  </ScrollArea>
                )}
                <div className="flex gap-2">
                  <Select value={repairMode} onValueChange={setRepairMode}>
                    <SelectTrigger className="w-32">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="dry">Dry Run</SelectItem>
                      <SelectItem value="sync">Sync</SelectItem>
                      <SelectItem value="rebuild">Rebuild</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button size="sm" onClick={handleRepair} disabled={repairConsistency.isPending}>
                    {repairConsistency.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wrench className="h-4 w-4 mr-1" />}
                    Repair
                  </Button>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">Click Check to verify consistency</p>
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
                <Button variant="destructive" size="sm" onClick={() => setIsInitializeOpen(true)} disabled={initializeKB.isPending}>
                  {initializeKB.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash className="h-4 w-4 mr-1" />}
                  Initialize
                </Button>
              </div>
              <div className="flex items-center justify-between p-3 border rounded-lg">
                <div className="flex items-center gap-3">
                  <FileText className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium">Rebuild Docstore</p>
                    <p className="text-xs text-muted-foreground">Rebuild docstore from LanceDB data</p>
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={() => setIsRebuildOpen(true)} disabled={rebuildDocstore.isPending}>
                  {rebuildDocstore.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-1" />}
                  Rebuild
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
        <DangerConfirmDialog
          open={isRebuildOpen}
          onOpenChange={setIsRebuildOpen}
          title="重建 Docstore"
          description="此操作将从 LanceDB 数据重建 docstore，可能会覆盖现有数据。"
          kbName={kb.id}
          onConfirm={handleConfirmRebuild}
          variant="rebuild"
        />
      </CardContent>
    </Card>
  )
}

function KBListItem({
  kb,
  isSelected,
  onSelect,
}: {
  kb: KBInfo
  isSelected: boolean
  onSelect: () => void
}) {
  const { data: kbTopics } = useKBTopics(kb.id)
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [isDeleteOpen, setIsDeleteOpen] = useState(false)
  const deleteKB = useDeleteKB()

  const handleConfirmDelete = async () => {
    await deleteKB.mutateAsync({ kbId: kb.id, confirmationName: kb.id })
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
              onClick={(e) => { e.stopPropagation(); setIsEditOpen(true) }}
            >
              <Pencil className="h-4 w-4 text-muted-foreground" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => { e.stopPropagation(); setIsDeleteOpen(true) }}
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
      const result = await repairAll.mutateAsync('sync')
      toast.success(result.message)
    } catch (error) {
      toast.error('Repair all failed')
    }
  }

  const selectedKB = kbs?.find(kb => kb.id === selectedKBId)

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Knowledge Base</h1>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={handleRepairAll}
            disabled={repairAll.isPending || !kbs?.length}
          >
            {repairAll.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <WrenchIcon className="mr-2 h-4 w-4" />}
            Repair All
          </Button>
        </div>

        <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
          <DialogTrigger asChild>
            <Button>
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
                />
              ))}
            </div>
          </div>
          <div>
            {selectedKB ? (
              <KBDetailsPanel kb={selectedKB} />
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