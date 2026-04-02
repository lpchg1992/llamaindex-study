import { useState } from 'react'
import { useKBs, useCreateKB, useDeleteKB } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Plus, Trash2, Database } from 'lucide-react'
import type { KBInfo } from '@/types/api'

export function KnowledgeBase() {
  const { data: kbs, isLoading } = useKBs()
  const createKB = useCreateKB()
  const deleteKB = useDeleteKB()

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [newKB, setNewKB] = useState<Partial<KBInfo>>({
    id: '',
    name: '',
    description: '',
  })

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

  const handleDelete = async (kbId: string) => {
    if (!confirm(`Delete knowledge base "${kbId}"?`)) return
    try {
      await deleteKB.mutateAsync(kbId)
    } catch (error) {
      console.error('Failed to delete KB:', error)
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Knowledge Base</h1>

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
        <div className="space-y-4">
          {kbs.map((kb) => (
            <Card key={kb.id}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Database className="h-5 w-5 text-muted-foreground" />
                    <CardTitle>{kb.name || kb.id}</CardTitle>
                    <Badge variant="secondary" className="capitalize">
                      {kb.status}
                    </Badge>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleDelete(kb.id)}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="grid gap-2 text-sm md:grid-cols-4">
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
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <p className="text-muted-foreground">No knowledge bases found</p>
      )}
    </div>
  )
}