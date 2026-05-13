import { useState, useEffect } from 'react'
import { useUpdateKB, useCanonicalNames } from '@/api/hooks'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Loader2, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import type { KBInfo } from '@/types/api'

interface KBEditDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  kb: KBInfo
}

export function KBEditDialog({ open, onOpenChange, kb }: KBEditDialogProps) {
  const updateKB = useUpdateKB()
  const { data: canonicalNames } = useCanonicalNames()

  const [name, setName] = useState(kb.name)
  const [description, setDescription] = useState(kb.description)
  const [canonicalName, setCanonicalName] = useState<string | undefined>(kb.canonical_name)

  useEffect(() => {
    if (open) {
      setName(kb.name)
      setDescription(kb.description)
      setCanonicalName(kb.canonical_name)
    }
  }, [open, kb])

  const handleSaveBasic = async () => {
    try {
      await updateKB.mutateAsync({
        kbId: kb.id,
        data: {
          name,
          description,
          canonical_name: canonicalName,
        },
      })
      toast.success('Knowledge base updated')
      onOpenChange(false)
    } catch (error) {
      toast.error('Failed to update knowledge base')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Pencil className="h-5 w-5" />
            Edit Knowledge Base
          </DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="basic" className="flex-1 overflow-hidden">
          <TabsList className="grid w-full grid-cols-1">
            <TabsTrigger value="basic">Basic Info</TabsTrigger>
          </TabsList>

          <TabsContent value="basic" className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="edit-kb-id">ID</Label>
              <Input
                id="edit-kb-id"
                value={kb.id}
                disabled
                className="bg-muted"
              />
              <p className="text-xs text-muted-foreground">ID cannot be changed</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-kb-name">Name</Label>
              <Input
                id="edit-kb-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Knowledge base name"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-kb-desc">Description</Label>
              <Input
                id="edit-kb-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional description"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-kb-canonical">Canonical Name</Label>
              <Select value={canonicalName || '__none__'} onValueChange={(v) => setCanonicalName(v === '__none__' ? undefined : v)}>
                <SelectTrigger>
                  <SelectValue placeholder="None" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">None</SelectItem>
                  {canonicalNames?.map((n) => (
                    <SelectItem key={n.id} value={n.id}>
                      {n.id}{n.description ? ` — ${n.description}` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">Documents: </span>
                <span className="font-medium">{kb.row_count?.toLocaleString() || 0}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Status: </span>
                <Badge variant="secondary" className="capitalize">{kb.status}</Badge>
              </div>
            </div>
          </TabsContent>
        </Tabs>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleSaveBasic}
            disabled={updateKB.isPending}
          >
            {updateKB.isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : null}
            Save Changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}