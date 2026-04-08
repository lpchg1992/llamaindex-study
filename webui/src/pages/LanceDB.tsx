import { useState } from 'react'
import { useKBs, useLanceStats, useLanceDuplicates, useDocuments, useDocumentChunks, useDeleteDocument, useUpdateChunk, useReembedChunk } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
import { Database, FileText, AlertTriangle, Loader2, BarChart3, ChevronRight, Trash2, RefreshCw, Edit2, X, Check } from 'lucide-react'
import type { DocumentInfo, ChunkInfo } from '@/types/api'

function DocumentManagementTab({ kbId }: { kbId: string }) {
  const { data: documents, isLoading } = useDocuments(kbId)
  const deleteDoc = useDeleteDocument()
  const [expandedDoc, setExpandedDoc] = useState<string | null>(null)
  const [selectedDocForChunks, setSelectedDocForChunks] = useState<DocumentInfo | null>(null)
  const [editingChunk, setEditingChunk] = useState<ChunkInfo | null>(null)
  const [editText, setEditText] = useState('')
  const { data: chunks, isLoading: chunksLoading } = useDocumentChunks(kbId, expandedDoc || '')
  const updateChunk = useUpdateChunk()
  const reembedChunk = useReembedChunk()

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
    await reembedChunk.mutateAsync({ kbId, chunkId: chunk.id })
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!documents || documents.length === 0) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center h-48">
          <p className="text-muted-foreground">No documents found. Run migration or ingest new documents.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            Documents ({documents.length})
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[500px]">
          <div className="space-y-2">
            {documents.map((doc) => (
              <div key={doc.id} className="border rounded-lg overflow-hidden">
                <div
                  className="flex items-center justify-between p-3 hover:bg-muted/50 cursor-pointer"
                  onClick={() => setExpandedDoc(expandedDoc === doc.id ? null : doc.id)}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-muted-foreground" />
                      <p className="font-medium truncate">{doc.source_file}</p>
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge variant="secondary">{doc.chunk_count} chunks</Badge>
                      <Badge variant="outline">{doc.total_chars.toLocaleString()} chars</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1 truncate">
                      {doc.source_path}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <code className="text-xs text-muted-foreground font-mono">
                      {doc.id.slice(0, 8)}...
                    </code>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDelete(doc)
                      }}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                    <ChevronRight className={`h-4 w-4 transition-transform ${expandedDoc === doc.id ? 'rotate-90' : ''}`} />
                  </div>
                </div>

                {expandedDoc === doc.id && (
                  <div className="border-t bg-muted/30">
                    <div className="p-3">
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="font-medium text-sm">Chunks</h4>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setSelectedDocForChunks(doc)}
                        >
                          View All Chunks
                        </Button>
                      </div>
                      <div className="text-xs text-muted-foreground space-y-1">
                        <p>ID: {doc.id}</p>
                        <p>File Hash: {doc.file_hash.slice(0, 16)}...</p>
                        <p>Created: {new Date(doc.created_at * 1000).toLocaleString()}</p>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>

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

      <Dialog open={!!selectedDocForChunks} onOpenChange={() => setSelectedDocForChunks(null)}>
        <DialogContent className="max-w-4xl max-h-[80vh]">
          <DialogHeader>
            <DialogTitle>Chunks: {selectedDocForChunks?.source_file}</DialogTitle>
          </DialogHeader>
          <div className="flex items-center justify-between p-2 bg-muted rounded">
            <span className="text-sm text-muted-foreground">
              {chunksLoading ? 'Loading...' : `${chunks?.length || 0} chunks`}
            </span>
            <Button variant="ghost" size="icon" onClick={() => setSelectedDocForChunks(null)}>
              <X className="h-4 w-4" />
            </Button>
          </div>
          <ScrollArea className="h-[500px]">
            {chunksLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="space-y-2">
                {chunks?.map((chunk) => (
                  <div key={chunk.id} className="p-3 border rounded-lg">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{chunk.chunk_index}</Badge>
                        <Badge variant="secondary">L{chunk.hierarchy_level}</Badge>
                        <code className="text-xs text-muted-foreground">{chunk.id.slice(0, 12)}...</code>
                      </div>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleEditStart(chunk)}
                        >
                          <Edit2 className="h-3 w-3" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleReembed(chunk)}
                          disabled={reembedChunk.isPending}
                        >
                          <RefreshCw className={`h-3 w-3 ${reembedChunk.isPending ? 'animate-spin' : ''}`} />
                        </Button>
                      </div>
                    </div>
                    <p className="text-sm mt-2 line-clamp-3">{chunk.text}</p>
                    {chunk.parent_chunk_id && (
                      <p className="text-xs text-muted-foreground mt-1">
                        Parent: <code>{chunk.parent_chunk_id.slice(0, 12)}...</code>
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </Card>
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
