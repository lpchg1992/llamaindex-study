import { useState } from 'react'
import { useCanonicalNames, useCreateCanonicalName, useDeleteCanonicalName } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import { Plus, Trash2, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

export function CanonicalNamesPanel() {
  const { data: names, isLoading } = useCanonicalNames()
  const createMutation = useCreateCanonicalName()
  const deleteMutation = useDeleteCanonicalName()
  const [open, setOpen] = useState(false)
  const [newId, setNewId] = useState('')
  const [newType, setNewType] = useState('embedding')
  const [newDesc, setNewDesc] = useState('')

  const handleCreate = async () => {
    if (!newId.trim()) return
    try {
      await createMutation.mutateAsync({
        id: newId.trim(),
        model_type: newType,
        description: newDesc || undefined,
      })
      toast.success(`Canonical name "${newId}" created`)
      setOpen(false)
      setNewId('')
      setNewDesc('')
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Failed to create')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteMutation.mutateAsync(id)
      toast.success(`"${id}" deleted`)
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Failed to delete')
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Canonical Names</CardTitle>
        <Button size="sm" onClick={() => setOpen(true)}>
          <Plus className="mr-1 h-4 w-4" /> Add
        </Button>
      </CardHeader>
      <CardContent>
        <p className="text-xs text-muted-foreground mb-4">
          Canonical names identify models that are the same across different vendors
          (e.g., bge-m3 on Ollama vs SiliconFlow). Models reference these names rather
          than entering free-form text.
        </p>
        {isLoading ? (
          <div className="flex justify-center py-4"><Loader2 className="h-5 w-5 animate-spin" /></div>
        ) : (
          <div className="space-y-2">
            {names?.map((n) => (
              <div key={n.id} className="flex items-center justify-between p-3 border rounded-lg">
                <div className="flex items-center gap-3">
                  <span className="font-mono font-medium">{n.id}</span>
                  <Badge variant="outline">{n.model_type}</Badge>
                  {n.description && (
                    <span className="text-xs text-muted-foreground">{n.description}</span>
                  )}
                </div>
                <Button variant="ghost" size="icon" onClick={() => handleDelete(n.id)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            {(!names || names.length === 0) && (
              <p className="text-sm text-muted-foreground text-center py-4">No canonical names defined</p>
            )}
          </div>
        )}
      </CardContent>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Canonical Name</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label htmlFor="cn-id">Name ID</Label>
              <Input id="cn-id" value={newId} onChange={(e) => setNewId(e.target.value)}
                placeholder="e.g. bge-m3" className="font-mono" />
            </div>
            <div>
              <Label htmlFor="cn-type">Model Type</Label>
              <Select value={newType} onValueChange={setNewType}>
                <SelectTrigger id="cn-type"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="embedding">embedding</SelectItem>
                  <SelectItem value="llm">llm</SelectItem>
                  <SelectItem value="reranker">reranker</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="cn-desc">Description (optional)</Label>
              <Input id="cn-desc" value={newDesc} onChange={(e) => setNewDesc(e.target.value)}
                placeholder="e.g. BGE-M3 多语言 embedding 模型" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!newId.trim() || createMutation.isPending}>
              {createMutation.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
