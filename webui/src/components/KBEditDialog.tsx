import { useState, useEffect } from 'react'
import { useUpdateKB, useUpdateTopics } from '@/api/hooks'
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
import { ScrollArea } from '@/components/ui/scroll-area'
import { X, Plus, Loader2, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import type { KBInfo, TopicInfo } from '@/types/api'

interface KBEditDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  kb: KBInfo
  topics?: TopicInfo
}

export function KBEditDialog({ open, onOpenChange, kb, topics }: KBEditDialogProps) {
  const updateKB = useUpdateKB()
  const updateTopics = useUpdateTopics()

  const [name, setName] = useState(kb.name)
  const [description, setDescription] = useState(kb.description)
  const [chunkStrategy, setChunkStrategy] = useState(kb.chunk_strategy || '')
  const [localTopics, setLocalTopics] = useState<string[]>(topics?.topics || [])
  const [newTopic, setNewTopic] = useState('')
  const [activeTab, setActiveTab] = useState('basic')

  useEffect(() => {
    if (open) {
      setName(kb.name)
      setDescription(kb.description)
      setChunkStrategy(kb.chunk_strategy || '')
      setLocalTopics(topics?.topics || [])
      setNewTopic('')
    }
  }, [open, kb, topics])

  const handleSaveBasic = async () => {
    try {
      await updateKB.mutateAsync({
        kbId: kb.id,
        data: {
          name,
          description,
          chunk_strategy: chunkStrategy || undefined,
        },
      })
      toast.success('Knowledge base updated')
      onOpenChange(false)
    } catch (error) {
      toast.error('Failed to update knowledge base')
    }
  }

  const handleAddTopic = () => {
    const trimmed = newTopic.trim()
    if (!trimmed) return
    if (localTopics.includes(trimmed)) {
      toast.error('Topic already exists')
      return
    }
    setLocalTopics([...localTopics, trimmed])
    setNewTopic('')
  }

  const handleRemoveTopic = (topic: string) => {
    setLocalTopics(localTopics.filter((t) => t !== topic))
  }

  const handleSaveTopics = async () => {
    try {
      await updateTopics.mutateAsync({
        kbId: kb.id,
        topics: localTopics,
      })
      toast.success('Topics updated')
      onOpenChange(false)
    } catch (error) {
      toast.error('Failed to update topics')
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

        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 overflow-hidden">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="basic">Basic Info</TabsTrigger>
            <TabsTrigger value="topics">
              Topics ({localTopics.length})
            </TabsTrigger>
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
              <Label htmlFor="edit-kb-chunk">Chunk Strategy</Label>
              <Input
                id="edit-kb-chunk"
                value={chunkStrategy}
                onChange={(e) => setChunkStrategy(e.target.value)}
                placeholder="e.g., sentence, paragraph, page"
              />
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

          <TabsContent value="topics" className="py-4">
            <div className="space-y-4">
              <div className="flex gap-2">
                <Input
                  value={newTopic}
                  onChange={(e) => setNewTopic(e.target.value)}
                  placeholder="Enter new topic..."
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      handleAddTopic()
                    }
                  }}
                />
                <Button onClick={handleAddTopic} disabled={!newTopic.trim()}>
                  <Plus className="h-4 w-4 mr-1" />
                  Add
                </Button>
              </div>

              <ScrollArea className="h-[300px] border rounded-lg p-4">
                {localTopics.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {localTopics.map((topic, index) => (
                      <Badge
                        key={index}
                        variant="outline"
                        className="pl-3 pr-2 py-1.5 flex items-center gap-1.5"
                      >
                        {topic}
                        <button
                          onClick={() => handleRemoveTopic(topic)}
                          className="ml-1 hover:bg-destructive/10 rounded p-0.5"
                        >
                          <X className="h-3 w-3 text-muted-foreground hover:text-destructive" />
                        </button>
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-full text-muted-foreground">
                    No topics yet. Add some topics above.
                  </div>
                )}
              </ScrollArea>

              <p className="text-xs text-muted-foreground">
                Click the X on a topic to remove it. Press Enter or click Add to add a new topic.
              </p>
            </div>
          </TabsContent>
        </Tabs>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={activeTab === 'basic' ? handleSaveBasic : handleSaveTopics}
            disabled={
              (activeTab === 'basic' && updateKB.isPending) ||
              (activeTab === 'topics' && updateTopics.isPending)
            }
          >
            {updateKB.isPending || updateTopics.isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : null}
            Save Changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}