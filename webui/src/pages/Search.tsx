import { useState } from 'react'
import { useKBs, useSearch, useModels } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Search as SearchIcon, FileText } from 'lucide-react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'sonner'
import type { SearchResult } from '@/types/api'

export function SearchPage() {
  const { data: kbs } = useKBs()
  const { data: embeddingModels } = useModels('embedding')
  const searchMutation = useSearch()

  const [query, setQuery] = useState('')
  const [selectedKBs, setSelectedKBs] = useState<string[]>([])
  const [results, setResults] = useState<SearchResult[]>([])
  const [hasSearched, setHasSearched] = useState(false)
  const [retrievalMode, setRetrievalMode] = useState<'vector' | 'hybrid'>('vector')
  const [embedModelId, setEmbedModelId] = useState<string>('')
  const [useAutoMerging, setUseAutoMerging] = useState(false)
  const [kbSearch, setKbSearch] = useState('')

  const filteredKBs = kbs?.filter(kb =>
    (kb.name || kb.id).toLowerCase().includes(kbSearch.toLowerCase())
  ) || []

  const toggleKB = (kbId: string) => {
    setSelectedKBs((prev) =>
      prev.includes(kbId) ? prev.filter((id) => id !== kbId) : [...prev, kbId]
    )
  }

  const handleSearch = async () => {
    if (!query || selectedKBs.length === 0) return
    setHasSearched(true)
    try {
      const response = await searchMutation.mutateAsync({
        query,
        kb_ids: selectedKBs.join(','),
        top_k: 10,
        route_mode: 'general',
        retrieval_mode: retrievalMode,
        embed_model_id: embedModelId || undefined,
        use_auto_merging: useAutoMerging || undefined,
      })
      setResults(response)
    } catch (error) {
      console.error('Search failed:', error)
      toast.error('Search failed')
    }
  }

  const selectAllKBs = () => {
    setSelectedKBs(filteredKBs.map(kb => kb.id))
  }

  const clearAllKBs = () => {
    setSelectedKBs([])
  }

  return (
    <div className="flex h-full">
      <div className="w-80 border-r p-4 flex flex-col">
        <h2 className="mb-4 text-lg font-semibold">Search Settings</h2>

        <div className="space-y-4 flex-1 overflow-y-auto">
          <div className="space-y-2">
            <Label>Retrieval Mode</Label>
            <Select value={retrievalMode} onValueChange={(v) => setRetrievalMode(v as 'vector' | 'hybrid')}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="vector">Vector Search</SelectItem>
                <SelectItem value="hybrid">Hybrid (Vector + BM25)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Embedding Model</Label>
            <Select value={embedModelId} onValueChange={setEmbedModelId}>
              <SelectTrigger>
                <SelectValue placeholder="Default model" />
              </SelectTrigger>
              <SelectContent>
                {embeddingModels?.map((model) => (
                  <SelectItem key={model.id} value={model.id}>
                    {model.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="auto-merging" className="text-sm">Auto-Merging</Label>
              <p className="text-xs text-muted-foreground">For hierarchical chunks</p>
            </div>
            <Switch
              id="auto-merging"
              checked={useAutoMerging}
              onCheckedChange={setUseAutoMerging}
            />
          </div>

          <div className="border-t pt-4">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Knowledge Bases</Label>
                <div className="flex gap-1">
                  <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={selectAllKBs}>
                    All
                  </Button>
                  <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={clearAllKBs}>
                    Clear
                  </Button>
                </div>
              </div>
              <Input
                placeholder="Search KBs..."
                value={kbSearch}
                onChange={(e) => setKbSearch(e.target.value)}
                className="h-8"
              />
            </div>
            <ScrollArea className="h-48 mt-2">
              <div className="space-y-2">
                {filteredKBs.map((kb) => (
                  <div key={kb.id} className="flex items-center space-x-2">
                    <Checkbox
                      id={kb.id}
                      checked={selectedKBs.includes(kb.id)}
                      onCheckedChange={() => toggleKB(kb.id)}
                    />
                    <Label htmlFor={kb.id} className="text-sm font-normal flex-1 cursor-pointer">
                      <span className="block">{kb.name || kb.id}</span>
                      <span className="text-xs text-muted-foreground">
                        {kb.row_count || 0} docs
                      </span>
                    </Label>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col p-4">
        <div className="mb-4 flex gap-2">
          <Input
            placeholder="Enter search query..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          />
          <Button onClick={handleSearch} disabled={searchMutation.isPending || !query || selectedKBs.length === 0}>
            <SearchIcon className="mr-2 h-4 w-4" />
            {searchMutation.isPending ? 'Searching...' : 'Search'}
          </Button>
        </div>

        <ScrollArea className="flex-1">
          {hasSearched && results.length === 0 ? (
            <p className="text-muted-foreground">No results found</p>
          ) : (
            <div className="space-y-4">
              {results.map((result, index) => (
                <Card key={index} className="hover:shadow-md transition-shadow">
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 min-w-0">
                        <FileText className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                        <CardTitle className="text-sm truncate">
                          {result.metadata?.file_name as string || 'Document'}
                        </CardTitle>
                      </div>
                      <Badge variant={result.score > 0.8 ? 'default' : 'outline'} className="flex-shrink-0">
                        {(result.score * 100).toFixed(0)}%
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-muted-foreground line-clamp-3 break-words">
                      {result.text}
                    </p>
                    {result.kb_id && (
                      <p className="mt-2 text-xs text-muted-foreground flex items-center gap-1">
                        <span className="font-medium">KB:</span> {result.kb_id}
                      </p>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </ScrollArea>
      </div>
    </div>
  )
}

export function Search() {
  return <SearchPage />
}