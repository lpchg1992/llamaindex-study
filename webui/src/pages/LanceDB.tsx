import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useKBs, useLanceStats, useLanceDuplicates, useDocuments, useDocumentChunks, useDeleteDocument, useUpdateChunk, useReembedChunk, useDeleteChunk, useChunkChildren, useDocEmbeddingStats } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Database, FileText, AlertTriangle, Loader2, BarChart3, ChevronRight, Trash2, RefreshCw, Edit2, Check } from 'lucide-react'
import { toast } from 'sonner'
import type { DocumentInfo, ChunkInfo } from '@/types/api'

export function LanceDBDialog({ open, onOpenChange, kbId }: { open: boolean; onOpenChange: (open: boolean) => void; kbId: string }) {
  const { data: stats, isLoading: statsLoading } = useLanceStats(kbId)
  const { data: duplicates, isLoading: duplicatesLoading } = useLanceDuplicates(kbId)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-6xl w-[95vw] h-[90vh] flex flex-col overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            LanceDB Management
          </DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="stats" className="flex-1 min-h-0 flex flex-col">
          <TabsList className="grid w-full grid-cols-3 shrink-0">
            <TabsTrigger value="stats">
              <BarChart3 className="mr-2 h-4 w-4" />
              Statistics
            </TabsTrigger>
            <TabsTrigger value="documents">
              <FileText className="mr-2 h-4 w-4" />
              Documents
            </TabsTrigger>
            <TabsTrigger value="duplicates">
              <AlertTriangle className="mr-2 h-4 w-4" />
              Duplicates
            </TabsTrigger>
          </TabsList>

          <TabsContent value="stats" className="mt-4 flex-1 overflow-auto">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Database className="h-5 w-5" />
                  Table Statistics
                </CardTitle>
              </CardHeader>
              <CardContent>
                {statsLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : stats ? (
                  <div className="grid gap-4 grid-cols-3">
                    <div className="p-4 border rounded-lg">
                      <p className="text-sm text-muted-foreground">Total Rows</p>
                      <p className="text-2xl font-bold">{stats.row_count.toLocaleString()}</p>
                    </div>
                    <div className="p-4 border rounded-lg">
                      <p className="text-sm text-muted-foreground">Table Size</p>
                      <p className="text-2xl font-bold">{stats.size_mb.toFixed(2)} MB</p>
                    </div>
                    <div className="p-4 border rounded-lg">
                      <p className="text-sm text-muted-foreground">Knowledge Base</p>
                      <p className="text-2xl font-bold font-mono">{stats.kb_id}</p>
                    </div>
                  </div>
                ) : (
                  <p className="text-muted-foreground text-center py-4">No statistics available</p>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="documents" className="flex-1 min-h-0 overflow-hidden w-full">
            <DocumentManagementTab kbId={kbId} />
          </TabsContent>

          <TabsContent value="duplicates" className="flex-1 min-h-0 overflow-auto">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertTriangle className="h-5 w-5" />
                  Duplicate Sources
                </CardTitle>
              </CardHeader>
              <CardContent>
                {duplicatesLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : duplicates && duplicates.duplicates && duplicates.duplicates.length > 0 ? (
                  <ScrollArea className="h-[400px]">
                    <div className="space-y-3">
                      {duplicates.duplicates.map((dup, index) => (
                        <div key={index} className="p-3 border border-yellow-200 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
                          <p className="font-medium">{dup.source}</p>
                          <p className="text-sm text-muted-foreground mt-1">
                            {dup.count} duplicate entries
                          </p>
                          <div className="flex flex-wrap gap-1 mt-2">
                            {dup.doc_ids.map((id, i) => (
                              <Badge key={i} variant="outline" className="text-xs font-mono">
                                {id.slice(0, 8)}...
                              </Badge>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                ) : (
                  <p className="text-muted-foreground text-center py-4">No duplicates found</p>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}

function DocumentManagementTab({ kbId }: { kbId: string }) {
  const { data: documents, isLoading } = useDocuments(kbId)
  const { data: docStats } = useDocEmbeddingStats(kbId)
  const deleteDoc = useDeleteDocument()
  const [expandedDoc, setExpandedDoc] = useState<string | null>(null)
  const [selectedDocForChunks, setSelectedDocForChunks] = useState<DocumentInfo | null>(null)
  const [editingChunk, setEditingChunk] = useState<ChunkInfo | null>(null)
  const [deletingChunk, setDeletingChunk] = useState<ChunkInfo | null>(null)
  const [editText, setEditText] = useState('')
  const [chunkPage, setChunkPage] = useState(1)
  const [chunkPageSize] = useState(20)
  const [chunkPageInput, setChunkPageInput] = useState('')
  const [chunkFilter, setChunkFilter] = useState<number | null>(null)
  const [reembeddingChunkId, setReembeddingChunkId] = useState<string | null>(null)
  const { data: chunksData, isLoading: chunksLoading, refetch: refetchChunks } = useDocumentChunks(kbId, expandedDoc || '', chunkPage, chunkPageSize, chunkFilter)
  const { data: childrenData, isLoading: childrenLoading } = useChunkChildren(kbId, deletingChunk?.id || '')
  const updateChunk = useUpdateChunk()
  const reembedChunk = useReembedChunk()
  const deleteChunk = useDeleteChunk()
  const queryClient = useQueryClient()

  const docStatsMap = docStats?.docs?.reduce((acc, d) => {
    acc[d.doc_id] = d
    return acc
  }, {} as Record<string, { total: number; in_lance: number; missing: number }>) || {}

  const handleDelete = async (doc: DocumentInfo) => {
    if (confirm(`Delete document "${doc.source_file}" and all its chunks?`)) {
      await deleteDoc.mutateAsync({ kbId, docId: doc.id })
    }
  }

  const handleEditStart = (chunk: ChunkInfo) => {
    setEditingChunk(chunk)
    setEditText(chunk.text)
  }

  const handleEditSave = async () => {
    if (editingChunk) {
      await updateChunk.mutateAsync({ kbId, chunkId: editingChunk.id, text: editText })
      setEditingChunk(null)
    }
  }

  const handleReembed = async (chunk: ChunkInfo) => {
    setReembeddingChunkId(chunk.id)
    try {
      const result = await reembedChunk.mutateAsync({ kbId, chunkId: chunk.id })
      if (result.status === 'success') {
        toast.success('Chunk reembedded successfully')
        refetchChunks()
        queryClient.invalidateQueries({ queryKey: ['doc-embedding-stats', kbId] })
        queryClient.invalidateQueries({ queryKey: ['documents', kbId] })
      } else {
        toast.error(result.message || 'Reembed failed')
      }
    } finally {
      setReembeddingChunkId(null)
    }
  }

  const handleDeleteChunk = async () => {
    if (deletingChunk) {
      await deleteChunk.mutateAsync({ kbId, chunkId: deletingChunk.id, cascade: true })
      toast.success(`Deleted chunk and ${childrenData?.count || 0} child chunks`)
      setDeletingChunk(null)
    }
  }

  if (isLoading) {
    return (
      <div className="flex flex-col h-full w-full bg-card border rounded-lg">
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    )
  }

  if (!documents || documents.length === 0) {
    return (
      <div className="flex flex-col h-full w-full bg-card border rounded-lg">
        <div className="flex-1 flex items-center justify-center">
          <p className="text-muted-foreground text-center">No documents found. Run migration or ingest new documents.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full w-full bg-card border rounded-lg overflow-hidden">
      <div className="flex items-center justify-between p-3 border-b shrink-0">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-muted-foreground" />
          <h3 className="font-medium text-sm">Documents ({documents.length})</h3>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="space-y-3 p-4">
            {documents.map((doc) => (
              <div key={doc.id} className="border rounded-lg overflow-hidden max-w-full">
                <div
                  className="flex items-center p-3 hover:bg-muted/50 cursor-pointer gap-3 max-w-full"
                  onClick={() => setExpandedDoc(expandedDoc === doc.id ? null : doc.id)}
                >
                  <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                  <div className="flex-1 min-w-0 max-w-full overflow-hidden">
                    <p className="font-medium text-sm truncate">{doc.source_file}</p>
                    <p className="text-xs text-muted-foreground truncate">{doc.source_path}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {docStatsMap[doc.id] ? (
                      <>
                        <Badge variant="default" className="bg-green-500 text-xs whitespace-nowrap">
                          ✓ {docStatsMap[doc.id].in_lance}
                        </Badge>
                        {docStatsMap[doc.id].missing > 0 && (
                          <Badge variant="destructive" className="text-xs whitespace-nowrap">
                            ✗ {docStatsMap[doc.id].missing}
                          </Badge>
                        )}
                      </>
                    ) : (
                      <Badge variant="secondary" className="text-xs whitespace-nowrap">{doc.chunk_count} chunks</Badge>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 shrink-0"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDelete(doc)
                      }}
                    >
                      <Trash2 className="h-3 w-3 text-destructive" />
                    </Button>
                    <ChevronRight className={`h-4 w-4 transition-transform shrink-0 ${expandedDoc === doc.id ? 'rotate-90' : ''}`} />
                  </div>
                </div>

                {expandedDoc === doc.id && (
                  <div className="border-t bg-muted/30 p-3 max-w-full overflow-hidden">
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-3 max-w-full overflow-hidden">
                      <div className="min-w-0 max-w-full overflow-hidden">
                        <p className="text-xs text-muted-foreground">ID</p>
                        <p className="text-xs font-mono truncate">{doc.id}</p>
                      </div>
                      {doc.zotero_doc_id && <div className="min-w-0 max-w-full overflow-hidden">
                        <p className="text-xs text-muted-foreground">Zotero ID</p>
                        <p className="text-xs font-mono truncate">{doc.zotero_doc_id}</p>
                      </div>}
                      <div className="min-w-0 max-w-full overflow-hidden">
                        <p className="text-xs text-muted-foreground">File Hash</p>
                        <p className="text-xs font-mono truncate">{doc.file_hash}</p>
                      </div>
                      <div className="min-w-0 max-w-full overflow-hidden">
                        <p className="text-xs text-muted-foreground">Created</p>
                        <p className="text-xs truncate">{new Date(doc.created_at * 1000).toLocaleString()}</p>
                      </div>
                    </div>
                    <Button
                      variant="default"
                      size="sm"
                      onClick={() => setSelectedDocForChunks(doc)}
                    >
                      View All Chunks
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
      </div>

      <Dialog open={!!editingChunk} onOpenChange={() => setEditingChunk(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit Chunk</DialogTitle>
          </DialogHeader>
          {editingChunk && (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-2 text-sm">
                <div className="p-2 bg-muted rounded">
                  <p className="text-muted-foreground">Index</p>
                  <p className="font-mono">{editingChunk.chunk_index}</p>
                </div>
                <div className="p-2 bg-muted rounded">
                  <p className="text-muted-foreground">Level</p>
                  <p className="font-mono">{editingChunk.hierarchy_level}</p>
                </div>
                <div className="p-2 bg-muted rounded">
                  <p className="text-muted-foreground">Chars</p>
                  <p className="font-mono">{editingChunk.text_length}</p>
                </div>
              </div>
              {editingChunk.parent_chunk_id && (
                <p className="text-sm">Parent: <code className="text-xs">{editingChunk.parent_chunk_id}</code></p>
              )}
              <div>
                <label className="text-sm font-medium">Text</label>
                <textarea
                  className="w-full h-48 p-2 border rounded font-mono text-sm mt-1"
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setEditingChunk(null)}>
                  Cancel
                </Button>
                <Button onClick={handleEditSave} disabled={updateChunk.isPending}>
                  {updateChunk.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  Save
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!selectedDocForChunks} onOpenChange={() => { setSelectedDocForChunks(null); setChunkPage(1); setChunkFilter(null) }}>
        <DialogContent className="max-w-6xl w-[95vw] h-[90vh] flex flex-col">
          <DialogHeader className="shrink-0">
            <DialogTitle className="flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Chunks: {selectedDocForChunks?.source_file}
            </DialogTitle>
            <div className="flex items-center gap-4">
              <p className="text-sm text-muted-foreground">
                {chunksLoading ? 'Loading...' : (
                  chunksData ? `Page ${chunksData.page} of ${chunksData.total_pages} - ${chunksData.total} chunks total` : 'No chunks'
                )}
              </p>
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Filter:</span>
                <Select value={chunkFilter === null ? 'all' : String(chunkFilter)} onValueChange={(v) => { setChunkFilter(v === 'all' ? null : Number(v)); setChunkPage(1) }}>
                  <SelectTrigger className="w-32 h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All</SelectItem>
                    <SelectItem value="1">✓ Embedded</SelectItem>
                    <SelectItem value="0">○ Pending</SelectItem>
                    <SelectItem value="2">✗ Failed</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </DialogHeader>
          <ScrollArea className="flex-1 min-h-0">
            {chunksLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="space-y-3 p-4">
                {chunksData?.chunks?.map((chunk) => (
                  <div key={chunk.id} className={`p-4 border rounded-lg ${chunk.embedding_generated === 2 ? 'border-red-300 bg-red-50' : chunk.embedding_generated === 0 ? 'border-yellow-300 bg-yellow-50' : ''}`}>
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <Badge variant="outline" className="text-sm">{chunk.chunk_index}</Badge>
                        <Badge variant="secondary" className="text-sm">L{chunk.hierarchy_level}</Badge>
                        {chunk.embedding_generated === 1 && <Badge variant="default" className="bg-green-500 text-xs">✓ Embedded</Badge>}
                        {chunk.embedding_generated === 0 && <Badge variant="secondary" className="bg-yellow-500 text-xs">○ Pending</Badge>}
                        {chunk.embedding_generated === 2 && <Badge variant="destructive" className="text-xs">✗ Failed</Badge>}
                        <code className="text-xs text-muted-foreground font-mono">{chunk.id}</code>
                      </div>
                      <div className="flex items-center gap-1">
                        {chunk.embedding_generated !== 1 && (
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleReembed(chunk)}
                            disabled={reembeddingChunkId !== null}
                            title="Reembed"
                          >
                            <RefreshCw className={`h-4 w-4 ${reembeddingChunkId === chunk.id ? 'animate-spin' : ''}`} />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleEditStart(chunk)}
                        >
                          <Edit2 className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setDeletingChunk(chunk)}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </div>
                    <p className="text-sm whitespace-pre-wrap break-words">
                        {chunk.text}
                      </p>
                    {chunk.parent_chunk_id && (
                      <p className="text-xs text-muted-foreground mt-2">
                        Parent: <code className="font-mono">{chunk.parent_chunk_id}</code>
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
          {chunksData && chunksData.total_pages > 1 && (
            <div className="flex items-center justify-center gap-1 py-3 border-t shrink-0">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setChunkPage(1)}
                disabled={chunkPage === 1 || chunksLoading}
                className="w-12"
              >
                1
              </Button>
              {chunksData.total_pages > 7 && chunkPage > 4 && (
                <span className="px-1 text-muted-foreground">...</span>
              )}
              {Array.from({
                length: Math.min(5, chunksData.total_pages),
              }, (_, i) => {
                let pageNum: number
                if (chunksData.total_pages <= 7) {
                  pageNum = i + 2
                } else if (chunkPage <= 4) {
                  pageNum = i + 2
                } else if (chunkPage >= chunksData.total_pages - 3) {
                  pageNum = chunksData.total_pages - 5 + i
                } else {
                  pageNum = chunkPage - 2 + i
                }
                if (pageNum < 2 || pageNum > chunksData.total_pages - 1) return null
                return (
                  <Button
                    key={pageNum}
                    variant={chunkPage === pageNum ? "default" : "outline"}
                    size="sm"
                    onClick={() => setChunkPage(pageNum)}
                    disabled={chunksLoading}
                    className="w-12"
                  >
                    {pageNum}
                  </Button>
                )
              })}
              {chunksData.total_pages > 7 && chunkPage < chunksData.total_pages - 3 && (
                <span className="px-1 text-muted-foreground">...</span>
              )}
              {chunksData.total_pages > 1 && (
                <Button
                  variant={chunkPage === chunksData.total_pages ? "default" : "outline"}
                  size="sm"
                  onClick={() => setChunkPage(chunksData.total_pages)}
                  disabled={chunkPage === chunksData.total_pages || chunksLoading}
                  className="w-12"
                >
                  {chunksData.total_pages}
                </Button>
              )}
              <div className="flex items-center gap-1 ml-2 border-l pl-3">
                <Input
                  type="number"
                  min={1}
                  max={chunksData.total_pages}
                  placeholder="页码"
                  value={chunkPageInput}
                  onChange={(e) => setChunkPageInput(e.target.value)}
                  className="w-16 h-8 text-sm"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && chunkPageInput) {
                      const page = parseInt(chunkPageInput)
                      if (page >= 1 && page <= chunksData.total_pages) {
                        setChunkPage(page)
                        setChunkPageInput('')
                      }
                    }
                  }}
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (chunkPageInput) {
                      const page = parseInt(chunkPageInput)
                      if (page >= 1 && page <= chunksData.total_pages) {
                        setChunkPage(page)
                        setChunkPageInput('')
                      }
                    }
                  }}
                  disabled={!chunkPageInput || chunksLoading}
                  className="h-8 px-3"
                >
                  跳转
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!deletingChunk} onOpenChange={() => setDeletingChunk(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              删除 Chunk
            </DialogTitle>
          </DialogHeader>
          {deletingChunk && (
            <div className="space-y-4">
              <div className="p-3 bg-muted rounded-lg">
                <p className="text-sm font-medium mb-1">Chunk ID:</p>
                <code className="text-xs font-mono break-all">{deletingChunk.id}</code>
                <p className="text-sm mt-2 line-clamp-2 text-muted-foreground">{deletingChunk.text}</p>
              </div>
              {childrenLoading ? (
                <div className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span className="text-sm text-muted-foreground">检查子节点...</span>
                </div>
              ) : childrenData && childrenData.count > 0 ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-yellow-600">
                    <AlertTriangle className="h-4 w-4" />
                    <span className="text-sm font-medium">此 chunk 有 {childrenData.count} 个子 chunk</span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {childrenData.children.slice(0, 5).map((child) => (
                      <Badge key={child.id} variant="outline" className="text-xs">
                        L{child.hierarchy_level} [{child.chunk_index}]
                      </Badge>
                    ))}
                    {childrenData.count > 5 && (
                      <Badge variant="outline" className="text-xs">
                        +{childrenData.count - 5} more
                      </Badge>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground">
                    选择"级联删除"将同时删除所有子 chunk。
                  </p>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">此 chunk 没有子节点。</p>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setDeletingChunk(null)}>
                  取消
                </Button>
                <Button
                  variant="destructive"
                  onClick={handleDeleteChunk}
                  disabled={deleteChunk.isPending}
                >
                  {deleteChunk.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : childrenData && childrenData.count > 0 ? (
                    '级联删除'
                  ) : (
                    '删除'
                  )}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

export function LanceDB() {
  const { data: kbs } = useKBs()
  const [selectedKB, setSelectedKB] = useState<string>('')
  const { data: stats, isLoading: statsLoading } = useLanceStats(selectedKB)
  const { data: duplicates, isLoading: duplicatesLoading } = useLanceDuplicates(selectedKB)

  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-bold">LanceDB Management</h1>

      <div className="mb-6">
        <label className="text-sm font-medium mb-2 block">Knowledge Base</label>
        <Select value={selectedKB} onValueChange={setSelectedKB}>
          <SelectTrigger className="w-64">
            <SelectValue placeholder="Select a knowledge base..." />
          </SelectTrigger>
          <SelectContent>
            {kbs?.map((kb) => (
              <SelectItem key={kb.id} value={kb.id}>
                {kb.name || kb.id}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {selectedKB ? (
        <>
          <Tabs defaultValue="stats" className="w-full">
            <TabsList>
              <TabsTrigger value="stats">
                <BarChart3 className="mr-2 h-4 w-4" />
                Statistics
              </TabsTrigger>
              <TabsTrigger value="documents">
                <FileText className="mr-2 h-4 w-4" />
                Documents
              </TabsTrigger>
              <TabsTrigger value="duplicates">
                <AlertTriangle className="mr-2 h-4 w-4" />
                Duplicates
              </TabsTrigger>
            </TabsList>

            <TabsContent value="stats" className="mt-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Database className="h-5 w-5" />
                    Table Statistics
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {statsLoading ? (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                    </div>
                  ) : stats ? (
                    <div className="grid gap-4 md:grid-cols-3">
                      <div className="p-4 border rounded-lg">
                        <p className="text-sm text-muted-foreground">Total Rows</p>
                        <p className="text-2xl font-bold">{stats.row_count.toLocaleString()}</p>
                      </div>
                      <div className="p-4 border rounded-lg">
                        <p className="text-sm text-muted-foreground">Table Size</p>
                        <p className="text-2xl font-bold">{stats.size_mb.toFixed(2)} MB</p>
                      </div>
                      <div className="p-4 border rounded-lg">
                        <p className="text-sm text-muted-foreground">Knowledge Base</p>
                        <p className="text-2xl font-bold font-mono">{stats.kb_id}</p>
                      </div>
                    </div>
                  ) : (
                    <p className="text-muted-foreground text-center py-4">No statistics available</p>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="documents" className="mt-4">
              <DocumentManagementTab kbId={selectedKB} />
            </TabsContent>

            <TabsContent value="duplicates" className="mt-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <AlertTriangle className="h-5 w-5" />
                    Duplicate Sources
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {duplicatesLoading ? (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                    </div>
                  ) : duplicates && duplicates.duplicates && duplicates.duplicates.length > 0 ? (
                    <ScrollArea className="h-96">
                      <div className="space-y-3">
                        {duplicates.duplicates.map((dup, index) => (
                          <div key={index} className="p-3 border border-yellow-200 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
                            <p className="font-medium">{dup.source}</p>
                            <p className="text-sm text-muted-foreground mt-1">
                              {dup.count} duplicate entries
                            </p>
                            <div className="flex flex-wrap gap-1 mt-2">
                              {dup.doc_ids.map((id, i) => (
                                <Badge key={i} variant="outline" className="text-xs font-mono">
                                  {id.slice(0, 8)}...
                                </Badge>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </ScrollArea>
                  ) : (
                    <p className="text-muted-foreground text-center py-4">No duplicates found</p>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </>
      ) : (
        <div className="flex items-center justify-center h-64 border rounded-lg">
          <p className="text-muted-foreground">Select a knowledge base to view LanceDB data</p>
        </div>
      )}
    </div>
  )
}

export function LanceDBPage() {
  return <LanceDB />
}
