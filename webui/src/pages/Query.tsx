import { useState } from 'react'
import { useKBs, useModels, useQueryMutation } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { MessageSquare, FileText, Loader2, Sparkles } from 'lucide-react'
import type { QueryResponse } from '@/types/api'

export function QueryPage() {
  const { data: kbs } = useKBs()
  const { data: models } = useModels('llm')
  const queryMutation = useQueryMutation()

  const [query, setQuery] = useState('')
  const [routeMode, setRouteMode] = useState<'general' | 'auto'>('general')
  const [selectedKBs, setSelectedKBs] = useState<string[]>([])
  const [retrievalMode, setRetrievalMode] = useState<'vector' | 'hybrid'>('vector')
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [useHyde, setUseHyde] = useState(false)
  const [useMultiQuery, setUseMultiQuery] = useState(false)
  const [useAutoMerging, setUseAutoMerging] = useState(false)
  const [responseMode, setResponseMode] = useState<string>('compact')
  const [response, setResponse] = useState<QueryResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const toggleKB = (kbId: string) => {
    setSelectedKBs((prev) =>
      prev.includes(kbId) ? prev.filter((id) => id !== kbId) : [...prev, kbId]
    )
  }

  const handleQuery = async () => {
    if (!query) return
    if (routeMode === 'general' && selectedKBs.length === 0) return

    setIsLoading(true)
    try {
      const result = await queryMutation.mutateAsync({
        query,
        route_mode: routeMode,
        kb_ids: routeMode === 'general' ? selectedKBs.join(',') : undefined,
        retrieval_mode: retrievalMode,
        model_id: selectedModel || undefined,
        use_hyde: useHyde || undefined,
        use_multi_query: useMultiQuery || undefined,
        use_auto_merging: useAutoMerging || undefined,
        response_mode: responseMode,
        top_k: 5,
      })
      setResponse(result)
    } catch (error) {
      console.error('Query failed:', error)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex h-full">
      <div className="w-80 border-r p-4">
        <h2 className="mb-4 text-lg font-semibold">Query Settings</h2>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Route Mode</Label>
            <Select value={routeMode} onValueChange={(v) => setRouteMode(v as 'general' | 'auto')}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="general">User selects KBs</SelectItem>
                <SelectItem value="auto">Auto routing</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {routeMode === 'general' && (
            <div className="space-y-2">
              <Label>Knowledge Bases</Label>
              <ScrollArea className="h-48">
                <div className="space-y-2">
                  {kbs?.map((kb) => (
                    <div key={kb.id} className="flex items-center space-x-2">
                      <Checkbox
                        id={kb.id}
                        checked={selectedKBs.includes(kb.id)}
                        onCheckedChange={() => toggleKB(kb.id)}
                      />
                      <Label htmlFor={kb.id} className="text-sm font-normal">
                        {kb.name || kb.id}
                      </Label>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </div>
          )}

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
            <Label>Model</Label>
            <Select value={selectedModel} onValueChange={setSelectedModel}>
              <SelectTrigger>
                <SelectValue placeholder="Default model" />
              </SelectTrigger>
              <SelectContent>
                {models?.map((model) => (
                  <SelectItem key={model.id} value={model.id}>
                    {model.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Response Mode</Label>
            <Select value={responseMode} onValueChange={setResponseMode}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="compact">Compact</SelectItem>
                <SelectItem value="refine">Refine</SelectItem>
                <SelectItem value="tree_summarize">Tree Summarize</SelectItem>
                <SelectItem value="simple">Simple</SelectItem>
                <SelectItem value="no_text">No Text</SelectItem>
                <SelectItem value="accumulate">Accumulate</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-3">
            <Label>Enhancements</Label>
            <div className="flex items-center justify-between">
              <Label htmlFor="hyde" className="text-sm">HyDE Query</Label>
              <Switch id="hyde" checked={useHyde} onCheckedChange={setUseHyde} />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="multi" className="text-sm">Multi Query</Label>
              <Switch id="multi" checked={useMultiQuery} onCheckedChange={setUseMultiQuery} />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="merging" className="text-sm">Auto Merging</Label>
              <Switch id="merging" checked={useAutoMerging} onCheckedChange={setUseAutoMerging} />
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col p-4">
        <div className="mb-4 flex gap-2">
          <Textarea
            placeholder="Enter your question..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="min-h-[80px]"
          />
          <Button
            onClick={handleQuery}
            disabled={isLoading || !query || (routeMode === 'general' && selectedKBs.length === 0)}
            className="shrink-0"
          >
            {isLoading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="mr-2 h-4 w-4" />
            )}
            {isLoading ? 'Thinking...' : 'Query'}
          </Button>
        </div>

        <ScrollArea className="flex-1">
          {response ? (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <MessageSquare className="h-5 w-5" />
                    Response
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="prose prose-sm max-w-none">
                    <p className="whitespace-pre-wrap">{response.response}</p>
                  </div>
                </CardContent>
              </Card>

              {response.sources && response.sources.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <FileText className="h-5 w-5" />
                      Sources ({response.sources.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {response.sources.map((source, index) => (
                      <div key={index} className="p-3 border rounded-lg">
                        <div className="flex items-center justify-between mb-2">
                          <Badge variant="outline">
                            Score: {(source.score * 100).toFixed(1)}%
                          </Badge>
                        </div>
                        <p className="text-sm text-muted-foreground line-clamp-3">
                          {source.text}
                        </p>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-muted-foreground">
              Enter a question and click Query to get started
            </div>
          )}
        </ScrollArea>
      </div>
    </div>
  )
}

export function Query() {
  return <QueryPage />
}