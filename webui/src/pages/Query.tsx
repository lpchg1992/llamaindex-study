import { useState } from 'react'
import { useKBs, useModels, useQueryMutation } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { MessageSquare, FileText, Loader2, Sparkles, X, Rocket, Microscope, BookOpen, FileSearch } from 'lucide-react'
import { toast } from 'sonner'
import type { QueryResponse } from '@/types/api'
import { cn } from '@/lib/utils'

type PresetMode = 'smart' | 'deep' | 'full' | 'search'

const PRESETS: Record<PresetMode, { label: string; icon: React.ElementType; config: Partial<QueryConfig> }> = {
  smart: {
    label: 'Smart Q&A',
    icon: Rocket,
    config: { retrieval_mode: 'vector', useHyde: false, useMultiQuery: false, useAutoMerging: false, responseMode: 'compact' }
  },
  deep: {
    label: 'Deep Analysis',
    icon: Microscope,
    config: { retrieval_mode: 'vector', useHyde: true, useMultiQuery: false, useAutoMerging: true, responseMode: 'tree_summarize' }
  },
  full: {
    label: 'Full Retrieval',
    icon: BookOpen,
    config: { retrieval_mode: 'hybrid', useHyde: false, useMultiQuery: true, useAutoMerging: false, responseMode: 'compact' }
  },
  search: {
    label: 'Search Only',
    icon: FileSearch,
    config: { retrieval_mode: 'vector', useHyde: false, useMultiQuery: false, useAutoMerging: false, responseMode: 'no_text' }
  }
}

interface QueryConfig {
  route_mode: 'general' | 'auto'
  selectedKBs: string[]
  excludedKBs: string[]
  retrieval_mode: 'vector' | 'hybrid'
  llmModelId: string
  embedModelId: string
  useHyde: boolean
  useMultiQuery: boolean
  numMultiQueries: number
  useAutoMerging: boolean
  responseMode: string
}

export function QueryPage() {
  const { data: kbs } = useKBs()
  const { data: llmModels } = useModels('llm')
  const { data: embeddingModels } = useModels('embedding')
  const queryMutation = useQueryMutation()

  const [config, setConfig] = useState<QueryConfig>({
    route_mode: 'general',
    selectedKBs: [],
    excludedKBs: [],
    retrieval_mode: 'vector',
    llmModelId: '',
    embedModelId: '',
    useHyde: false,
    useMultiQuery: false,
    numMultiQueries: 3,
    useAutoMerging: false,
    responseMode: 'compact',
  })
  const [query, setQuery] = useState('')
  const [response, setResponse] = useState<QueryResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [activePreset, setActivePreset] = useState<PresetMode | null>(null)
  const [kbSearch, setKbSearch] = useState('')

  const filteredKBs = kbs?.filter(kb =>
    (kb.name || kb.id).toLowerCase().includes(kbSearch.toLowerCase())
  ) || []

  const filteredExcludableKBs = kbs?.filter(kb =>
    !config.selectedKBs.includes(kb.id) && (kb.name || kb.id).toLowerCase().includes(kbSearch.toLowerCase())
  ) || []

  const updateConfig = <K extends keyof QueryConfig>(key: K, value: QueryConfig[K]) => {
    setConfig(prev => ({ ...prev, [key]: value }))
    setActivePreset(null)
  }

  const applyPreset = (preset: PresetMode) => {
    const presetConfig = PRESETS[preset].config
    setConfig(prev => ({
      ...prev,
      retrieval_mode: presetConfig.retrieval_mode as 'vector' | 'hybrid',
      useHyde: presetConfig.useHyde ?? false,
      useMultiQuery: presetConfig.useMultiQuery ?? false,
      useAutoMerging: presetConfig.useAutoMerging ?? false,
      responseMode: presetConfig.responseMode ?? 'compact',
    }))
    setActivePreset(preset)
  }

  const toggleKB = (kbId: string) => {
    updateConfig('selectedKBs',
      config.selectedKBs.includes(kbId)
        ? config.selectedKBs.filter(id => id !== kbId)
        : [...config.selectedKBs, kbId]
    )
  }

  const toggleExcludeKB = (kbId: string) => {
    updateConfig('excludedKBs',
      config.excludedKBs.includes(kbId)
        ? config.excludedKBs.filter(id => id !== kbId)
        : [...config.excludedKBs, kbId]
    )
  }

  const handleQuery = async () => {
    if (!query) return
    if (config.route_mode === 'general' && config.selectedKBs.length === 0) {
      toast.error('Please select at least one knowledge base')
      return
    }

    setIsLoading(true)
    try {
      const result = await queryMutation.mutateAsync({
        query,
        route_mode: config.route_mode,
        kb_ids: config.route_mode === 'general' ? config.selectedKBs.join(',') : undefined,
        exclude: config.route_mode === 'auto' && config.excludedKBs.length > 0 ? config.excludedKBs : undefined,
        retrieval_mode: config.retrieval_mode,
        model_id: config.llmModelId || undefined,
        embed_model_id: config.embedModelId || undefined,
        use_hyde: config.useHyde || undefined,
        use_multi_query: config.useMultiQuery || undefined,
        num_multi_queries: config.useMultiQuery ? config.numMultiQueries : undefined,
        use_auto_merging: config.useAutoMerging || undefined,
        response_mode: config.responseMode,
        top_k: 5,
      })
      setResponse(result)
    } catch (error) {
      console.error('Query failed:', error)
      toast.error('Query failed')
    } finally {
      setIsLoading(false)
    }
  }

  const isQueryDisabled = isLoading || !query || (config.route_mode === 'general' && config.selectedKBs.length === 0)

  return (
    <div className="flex h-full">
      <div className="w-96 border-r p-4 flex flex-col overflow-hidden">
        <h2 className="mb-4 text-lg font-semibold">Query Settings</h2>

        <div className="space-y-4 flex-1 overflow-y-auto">
          <div className="space-y-2">
            <Label>Presets</Label>
            <div className="grid grid-cols-2 gap-2">
              {(Object.keys(PRESETS) as PresetMode[]).map((mode) => {
                const preset = PRESETS[mode]
                const Icon = preset.icon
                return (
                  <Button
                    key={mode}
                    variant={activePreset === mode ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => applyPreset(mode)}
                    className={cn('justify-start', activePreset === mode && 'bg-primary')}
                  >
                    <Icon className="mr-2 h-4 w-4" />
                    {preset.label}
                  </Button>
                )
              })}
            </div>
          </div>

          <div className="border-t pt-4">
            <div className="space-y-2">
              <Label>Route Mode</Label>
              <Select value={config.route_mode} onValueChange={(v) => updateConfig('route_mode', v as 'general' | 'auto')}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="general">User selects KBs</SelectItem>
                  <SelectItem value="auto">Auto routing</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {config.route_mode === 'general' ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Knowledge Bases</Label>
                <div className="flex gap-1">
                  <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => updateConfig('selectedKBs', filteredKBs.map(kb => kb.id))}>
                    All
                  </Button>
                  <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => updateConfig('selectedKBs', [])}>
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
              <ScrollArea className="h-40">
                <div className="space-y-2">
                  {filteredKBs.map((kb) => (
                    <div key={kb.id} className="flex items-center space-x-2">
                      <Checkbox
                        id={kb.id}
                        checked={config.selectedKBs.includes(kb.id)}
                        onCheckedChange={() => toggleKB(kb.id)}
                      />
                      <Label htmlFor={kb.id} className="text-sm font-normal flex-1 cursor-pointer">
                        <span className="block">{kb.name || kb.id}</span>
                        <span className="text-xs text-muted-foreground">{kb.row_count || 0} docs</span>
                      </Label>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Exclude KBs</Label>
              </div>
              <Input
                placeholder="Search KBs to exclude..."
                value={kbSearch}
                onChange={(e) => setKbSearch(e.target.value)}
                className="h-8"
              />
              <ScrollArea className="h-32">
                <div className="flex flex-wrap gap-2">
                  {filteredExcludableKBs.map((kb) => (
                    <Badge
                      key={kb.id}
                      variant={config.excludedKBs.includes(kb.id) ? 'default' : 'outline'}
                      className="cursor-pointer"
                      onClick={() => toggleExcludeKB(kb.id)}
                    >
                      {kb.name || kb.id}
                      {config.excludedKBs.includes(kb.id) && <X className="ml-1 h-3 w-3" />}
                    </Badge>
                  ))}
                </div>
              </ScrollArea>
            </div>
          )}

          <div className="border-t pt-4 space-y-3">
            <div className="space-y-2">
              <Label>Retrieval Mode</Label>
              <Select value={config.retrieval_mode} onValueChange={(v) => updateConfig('retrieval_mode', v as 'vector' | 'hybrid')}>
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
              <Label>LLM Model</Label>
              <Select value={config.llmModelId} onValueChange={(v) => updateConfig('llmModelId', v)}>
                <SelectTrigger>
                  <SelectValue placeholder="Default model" />
                </SelectTrigger>
                <SelectContent>
                  {llmModels?.map((model) => (
                    <SelectItem key={model.id} value={model.id}>
                      {model.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Embedding Model</Label>
              <Select value={config.embedModelId} onValueChange={(v) => updateConfig('embedModelId', v)}>
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

            <div className="space-y-2">
              <Label>Response Mode</Label>
              <Select value={config.responseMode} onValueChange={(v) => updateConfig('responseMode', v)}>
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
                  <SelectItem value="compact_accumulate">Compact Accumulate</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-3">
              <Label>Enhancements</Label>
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="hyde" className="text-sm">HyDE Query</Label>
                  <p className="text-xs text-muted-foreground">Hypothetical document embedding</p>
                </div>
                <Switch id="hyde" checked={config.useHyde} onCheckedChange={(v) => updateConfig('useHyde', v)} />
              </div>
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="multi" className="text-sm">Multi Query</Label>
                  <p className="text-xs text-muted-foreground">Generate query variations</p>
                </div>
                <Switch id="multi" checked={config.useMultiQuery} onCheckedChange={(v) => updateConfig('useMultiQuery', v)} />
              </div>
              {config.useMultiQuery && (
                <div className="pl-6 border-l-2">
                  <Label htmlFor="num-queries" className="text-sm">Number of variations</Label>
                  <Input
                    id="num-queries"
                    type="number"
                    min={1}
                    max={10}
                    value={config.numMultiQueries}
                    onChange={(e) => updateConfig('numMultiQueries', parseInt(e.target.value) || 3)}
                    className="w-20 h-8"
                  />
                </div>
              )}
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="merging" className="text-sm">Auto Merging</Label>
                  <p className="text-xs text-muted-foreground">Merge child nodes (hierarchical)</p>
                </div>
                <Switch id="merging" checked={config.useAutoMerging} onCheckedChange={(v) => updateConfig('useAutoMerging', v)} />
              </div>
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
            disabled={isQueryDisabled}
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
              <Card className="border-l-4 border-l-primary">
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <MessageSquare className="h-5 w-5 text-primary" />
                    Response
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="prose prose-sm max-w-none dark:prose-invert">
                    <p className="whitespace-pre-wrap break-words leading-relaxed">{response.response}</p>
                  </div>
                </CardContent>
              </Card>

              {response.sources && response.sources.length > 0 && (
                <Card className="hover:shadow-md transition-shadow">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <FileText className="h-5 w-5" />
                      Sources ({response.sources.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {response.sources.map((source, index) => (
                      <div key={index} className="p-4 border rounded-lg hover:bg-muted/50 transition-colors">
                        <div className="flex items-center justify-between mb-2">
                          <Badge variant={source.score > 0.8 ? 'default' : 'outline'} className="font-mono">
                            {(source.score * 100).toFixed(0)}%
                          </Badge>
                        </div>
                        <p className="text-sm text-muted-foreground line-clamp-3 break-words leading-relaxed">
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