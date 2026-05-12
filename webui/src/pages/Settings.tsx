import { useState, useEffect } from 'react'
import { useSettings, useUpdateSettings, useRestartApi, useReloadConfig, useObservabilityStats, useResetObservability, useTraces, useObservabilityDates, useResetSettings } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Settings2, Brain, Search, Layers, Loader2, AlertCircle, RotateCcw, Server, Activity, Cpu, BarChart3, Clock, Trash2, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import type { SystemSettings, VendorStats } from '@/types/api'

function VendorPanel({ vendor }: { vendor: VendorStats }) {
  const [expanded, setExpanded] = useState(true)

  const models = vendor.models || []
  const llmModels = models.filter((m: any) => m.model_type === 'llm')
  const embedModels = models.filter((m: any) => m.model_type === 'embedding')
  const rerankerModels = models.filter((m: any) => m.model_type === 'reranker')

  return (
    <div className="border rounded-lg mb-4 overflow-hidden">
      <div
        className="flex items-center justify-between p-4 bg-muted/50 cursor-pointer hover:bg-muted transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <Server className="h-5 w-5 text-muted-foreground" />
          <div>
            <h3 className="font-semibold text-lg">{vendor.vendor_id}</h3>
            <p className="text-sm text-muted-foreground">
              {models.length} model{models.length !== 1 ? 's' : ''}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-6">
          <div className="text-right">
            <p className="text-2xl font-bold">{vendor.total_calls.toLocaleString()}</p>
            <p className="text-xs text-muted-foreground">calls</p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold">{vendor.total_tokens.toLocaleString()}</p>
            <p className="text-xs text-muted-foreground">tokens</p>
          </div>
          {vendor.total_errors > 0 && (
            <div className="text-right">
              <p className="text-2xl font-bold text-red-500">{vendor.total_errors}</p>
              <p className="text-xs text-muted-foreground">errors</p>
            </div>
          )}
          {expanded ? (
            <ChevronDown className="h-5 w-5 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-5 w-5 text-muted-foreground" />
          )}
        </div>
      </div>

      {expanded && (
        <div className="p-4">
          {models.length === 0 ? (
            <p className="text-muted-foreground text-center py-4">No model data</p>
          ) : (
            <div className="space-y-6">
              {llmModels.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-muted-foreground mb-2 flex items-center gap-2">
                    <Cpu className="h-4 w-4" /> LLM Models
                  </h4>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-muted-foreground border-b">
                        <th className="py-2 px-3 font-medium">Type</th>
                        <th className="py-2 px-3 font-medium">Model ID</th>
                        <th className="py-2 px-3 font-medium text-right">Calls</th>
                        <th className="py-2 px-3 font-medium text-right">Prompt</th>
                        <th className="py-2 px-3 font-medium text-right">Completion</th>
                        <th className="py-2 px-3 font-medium text-right">Total</th>
                        <th className="py-2 px-3 font-medium text-right">Errors</th>
                      </tr>
                    </thead>
                    <tbody>
                      {llmModels.map((model: any, idx: number) => (
                        <ModelRow key={`llm-${idx}`} model={model} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {embedModels.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-muted-foreground mb-2 flex items-center gap-2">
                    <BarChart3 className="h-4 w-4" /> Embedding Models
                  </h4>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-muted-foreground border-b">
                        <th className="py-2 px-3 font-medium">Type</th>
                        <th className="py-2 px-3 font-medium">Model ID</th>
                        <th className="py-2 px-3 font-medium text-right">Calls</th>
                        <th className="py-2 px-3 font-medium text-right">Tokens</th>
                        <th className="py-2 px-3 font-medium text-right">Total</th>
                        <th className="py-2 px-3 font-medium text-right">Errors</th>
                      </tr>
                    </thead>
                    <tbody>
                      {embedModels.map((model: any, idx: number) => (
                        <tr key={`embed-${idx}`} className="border-b">
                          <td className="py-2 px-3">
                            <Badge variant="outline">{model.model_type}</Badge>
                          </td>
                          <td className="py-2 px-3 font-mono text-sm">{model.model_id}</td>
                          <td className="py-2 px-3 text-right">{model.call_count.toLocaleString()}</td>
                          <td className="py-2 px-3 text-right">{model.prompt_tokens.toLocaleString()}</td>
                          <td className="py-2 px-3 text-right font-medium">{model.total_tokens.toLocaleString()}</td>
                          <td className="py-2 px-3 text-right">
                            {model.error_count > 0 ? (
                              <span className="text-red-500">{model.error_count}</span>
                            ) : (
                              <span className="text-green-500">0</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {rerankerModels.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-muted-foreground mb-2 flex items-center gap-2">
                    <Activity className="h-4 w-4" /> Reranker Models
                  </h4>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-muted-foreground border-b">
                        <th className="py-2 px-3 font-medium">Type</th>
                        <th className="py-2 px-3 font-medium">Model ID</th>
                        <th className="py-2 px-3 font-medium text-right">Calls</th>
                        <th className="py-2 px-3 font-medium text-right">Tokens</th>
                        <th className="py-2 px-3 font-medium text-right">Total</th>
                        <th className="py-2 px-3 font-medium text-right">Errors</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rerankerModels.map((model: any, idx: number) => (
                        <tr key={`rerank-${idx}`} className="border-b">
                          <td className="py-2 px-3">
                            <Badge variant="outline">{model.model_type}</Badge>
                          </td>
                          <td className="py-2 px-3 font-mono text-sm">{model.model_id}</td>
                          <td className="py-2 px-3 text-right">{model.call_count.toLocaleString()}</td>
                          <td className="py-2 px-3 text-right">{model.prompt_tokens.toLocaleString()}</td>
                          <td className="py-2 px-3 text-right font-medium">{model.total_tokens.toLocaleString()}</td>
                          <td className="py-2 px-3 text-right">
                            {model.error_count > 0 ? (
                              <span className="text-red-500">{model.error_count}</span>
                            ) : (
                              <span className="text-green-500">0</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ModelRow({ model }: { model: any }) {
  return (
    <tr className="border-b">
      <td className="py-2 px-3">
        <Badge variant="secondary">{model.model_type}</Badge>
      </td>
      <td className="py-2 px-3 font-mono text-sm">{model.model_id}</td>
      <td className="py-2 px-3 text-right">{model.call_count.toLocaleString()}</td>
      <td className="py-2 px-3 text-right">{model.prompt_tokens.toLocaleString()}</td>
      <td className="py-2 px-3 text-right">{model.completion_tokens.toLocaleString()}</td>
      <td className="py-2 px-3 text-right font-medium">{model.total_tokens.toLocaleString()}</td>
      <td className="py-2 px-3 text-right">
        {model.error_count > 0 ? (
          <span className="text-red-500">{model.error_count}</span>
        ) : (
          <span className="text-green-500">0</span>
        )}
      </td>
    </tr>
  )
}

export function SettingsPage() {
  const { data: settings, isLoading, error } = useSettings()
  const updateSettings = useUpdateSettings()
  const restartApi = useRestartApi()
  const reloadConfig = useReloadConfig()
  const resetSettings = useResetSettings()

  // Observability hooks and state
  const [startDate, setStartDate] = useState<string>('')
  const [endDate, setEndDate] = useState<string>('')
  const { data: stats, isLoading: statsLoading, refetch: refetchStats } = useObservabilityStats(startDate || undefined, endDate || undefined)
  const resetStats = useResetObservability()
  const { data: traces, isLoading: tracesLoading, refetch: refetchTraces } = useTraces(100, startDate || undefined, endDate || undefined)
  const { data: availableDates } = useObservabilityDates()

  const handleQuickDateFilter = (days: number | null) => {
    if (days === null) {
      setStartDate('')
      setEndDate('')
      return
    }
    const today = new Date()
    const past = new Date()
    past.setDate(today.getDate() - days)
    setStartDate(past.toISOString().split('T')[0])
    setEndDate(today.toISOString().split('T')[0])
  }

  const [localSettings, setLocalSettings] = useState<SystemSettings | null>(null)

  useEffect(() => {
    if (settings) {
      setLocalSettings(settings)
    }
  }, [settings])

  const handleSave = async (category: string) => {
    if (!localSettings) return
    try {
      await updateSettings.mutateAsync(localSettings)
      toast.success(`${category} settings saved`)
    } catch (err) {
      toast.error(`Failed to save ${category} settings`)
    }
  }

  const handleReloadConfig = async () => {
    try {
      await reloadConfig.mutateAsync()
      toast.success('Configuration reloaded')
    } catch (err) {
      toast.error('Failed to reload configuration')
    }
  }

  const handleRestartApi = async () => {
    try {
      await restartApi.mutateAsync()
      toast.success('API restart initiated - page will reload')
      setTimeout(() => {
        window.location.reload()
      }, 2000)
    } catch (err) {
      toast.error('Failed to restart API')
    }
  }

  const handleResetDefaults = async () => {
    if (!confirm('Reset all settings to their default values? This cannot be undone.')) return
    try {
      await resetSettings.mutateAsync()
      toast.success('Settings restored to defaults')
    } catch (err) {
      toast.error('Failed to reset settings')
    }
  }

  const updateField = <K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) => {
    if (localSettings) {
      setLocalSettings({ ...localSettings, [key]: value })
    }
  }

  // Observability handlers
  const handleResetObservability = async () => {
    if (!confirm('Reset all observability data?')) return
    try {
      await resetStats.mutateAsync()
      toast.success('Observability data reset')
      refetchStats()
    } catch (error) {
      toast.error('Failed to reset')
    }
  }

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !localSettings) {
    return (
      <div className="p-6">
        <div className="flex items-center gap-2 text-destructive">
          <AlertCircle className="h-5 w-5" />
          <span>Failed to load settings</span>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Settings2 className="h-6 w-6" />
          Settings
        </h1>
        <p className="text-muted-foreground mt-1">
          Configure system behavior. Some changes require restart to take effect.
        </p>
      </div>

      <Tabs defaultValue="model" className="w-full">
        <TabsList className="mb-4 flex flex-wrap h-auto">
          <TabsTrigger value="model">
            <Brain className="mr-2 h-4 w-4" />
            Model
          </TabsTrigger>
          <TabsTrigger value="search">
            <Search className="mr-2 h-4 w-4" />
            Search
          </TabsTrigger>
          <TabsTrigger value="chunk">
            <Layers className="mr-2 h-4 w-4" />
            Chunk
          </TabsTrigger>
          <TabsTrigger value="observability">
            <Activity className="mr-2 h-4 w-4" />
            Observability
          </TabsTrigger>
          <TabsTrigger value="system">
            <Server className="mr-2 h-4 w-4" />
            System
          </TabsTrigger>
        </TabsList>

        <TabsContent value="model">
          <div className="space-y-6">
            {/* Reranker Section */}
            <Card>
              <CardHeader>
                <CardTitle>Reranker Settings</CardTitle>
                <CardDescription>Configure document reranking after initial retrieval</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="use-reranker">Enable Reranker</Label>
                    <p className="text-sm text-muted-foreground">
                      Re-rank retrieved documents for better relevance
                    </p>
                  </div>
                  <Switch
                    id="use-reranker"
                    checked={localSettings.use_reranker}
                    onCheckedChange={(checked) => updateField('use_reranker', checked)}
                  />
                </div>
              </CardContent>
            </Card>

            <Button onClick={() => handleSave('Model')} disabled={updateSettings.isPending}>
              {updateSettings.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save Model Settings
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="search">
          <div className="space-y-6">
            {/* Retrieval Section */}
            <Card>
              <CardHeader>
                <CardTitle>Retrieval Settings</CardTitle>
                <CardDescription>Configure how documents are retrieved</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="top-k">Top K (Number of results)</Label>
                  <Input
                    id="top-k"
                    type="number"
                    min={1}
                    max={100}
                    value={localSettings.top_k}
                    onChange={(e) => updateField('top_k', parseInt(e.target.value) || 5)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="oversampling">Retrieval Oversampling Factor</Label>
                  <Input
                    id="oversampling"
                    type="number"
                    min={1}
                    max={20}
                    value={localSettings.retrieval_oversampling_factor}
                    onChange={(e) => updateField('retrieval_oversampling_factor', parseInt(e.target.value) || 5)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Retrieve top_k × N candidates before reranking. Higher = more recall, slower.
                  </p>
                </div>

                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="hybrid-search">Hybrid Search</Label>
                    <p className="text-sm text-muted-foreground">
                      Combine vector and keyword search
                    </p>
                  </div>
                  <Switch
                    id="hybrid-search"
                    checked={localSettings.use_hybrid_search}
                    onCheckedChange={(checked) => updateField('use_hybrid_search', checked)}
                  />
                </div>

                {localSettings.use_hybrid_search && (
                  <div className="space-y-2 pl-6 border-l-2">
                    <Label htmlFor="hybrid-alpha">Vector Weight (Alpha)</Label>
                    <div className="flex items-center gap-4">
                      <Input
                        id="hybrid-alpha"
                        type="number"
                        min={0}
                        max={1}
                        step={0.1}
                        value={localSettings.hybrid_search_alpha}
                        onChange={(e) => updateField('hybrid_search_alpha', parseFloat(e.target.value) || 0.5)}
                        className="w-24"
                      />
                      <span className="text-sm text-muted-foreground">
                        {localSettings.hybrid_search_alpha < 0.5 ? 'More keyword' : localSettings.hybrid_search_alpha > 0.5 ? 'More vector' : 'Balanced'}
                      </span>
                    </div>
                    <div className="space-y-2 mt-4">
                      <Label htmlFor="hybrid-mode">Fusion Mode</Label>
                      <Select
                        value={localSettings.hybrid_search_mode}
                        onValueChange={(v) => updateField('hybrid_search_mode', v)}
                      >
                        <SelectTrigger id="hybrid-mode">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="relative_score">Relative Score</SelectItem>
                          <SelectItem value="dynamic">Dynamic</SelectItem>
                          <SelectItem value="converage">Converage</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                )}

                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="auto-merging">Auto-Merging</Label>
                    <p className="text-sm text-muted-foreground">
                      Automatically merge child nodes into parent nodes
                    </p>
                  </div>
                  <Switch
                    id="auto-merging"
                    checked={localSettings.use_auto_merging}
                    onCheckedChange={(checked) => updateField('use_auto_merging', checked)}
                  />
                </div>

                {localSettings.use_auto_merging && (
                  <div className="space-y-2 pl-6 border-l-2">
                    <Label htmlFor="merge-thresh">Merge Threshold</Label>
                    <div className="flex items-center gap-4">
                      <Input
                        id="merge-thresh"
                        type="number"
                        min={0.1}
                        max={1.0}
                        step={0.05}
                        value={localSettings.auto_merging_simple_ratio_thresh}
                        onChange={(e) => updateField('auto_merging_simple_ratio_thresh', parseFloat(e.target.value) || 0.5)}
                        className="w-24"
                      />
                      <span className="text-sm text-muted-foreground">
                        {localSettings.auto_merging_simple_ratio_thresh >= 0.6
                          ? 'Conservative'
                          : localSettings.auto_merging_simple_ratio_thresh <= 0.35
                            ? 'Aggressive'
                            : 'Balanced'}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Only merge if {Math.round(localSettings.auto_merging_simple_ratio_thresh * 100)}% of child nodes match. Higher = less noise.
                    </p>
                  </div>
                )}

                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="hyde">HyDE Query</Label>
                    <p className="text-sm text-muted-foreground">
                      Hypothetical Document Embedding for better retrieval
                    </p>
                  </div>
                  <Switch
                    id="hyde"
                    checked={localSettings.use_hyde}
                    onCheckedChange={(checked) => updateField('use_hyde', checked)}
                  />
                </div>

                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="multi-query">Multi-Query</Label>
                    <p className="text-sm text-muted-foreground">
                      Generate multiple query variations
                    </p>
                  </div>
                  <Switch
                    id="multi-query"
                    checked={localSettings.use_multi_query}
                    onCheckedChange={(checked) => updateField('use_multi_query', checked)}
                  />
                </div>

                {localSettings.use_multi_query && (
                  <div className="space-y-2 pl-6 border-l-2">
                    <Label htmlFor="num-queries">Number of Query Variations</Label>
                    <Input
                      id="num-queries"
                      type="number"
                      min={1}
                      max={10}
                      value={localSettings.num_multi_queries}
                      onChange={(e) => updateField('num_multi_queries', parseInt(e.target.value) || 3)}
                      className="w-24"
                    />
                  </div>
                )}

                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="similarity-filter">Similarity Filter</Label>
                    <p className="text-sm text-muted-foreground">
                      Filter low-score nodes before reranking
                    </p>
                  </div>
                  <Switch
                    id="similarity-filter"
                    checked={localSettings.enable_similarity_filter}
                    onCheckedChange={(checked) => updateField('enable_similarity_filter', checked)}
                  />
                </div>

                {localSettings.enable_similarity_filter && (
                  <div className="space-y-2 pl-6 border-l-2">
                    <Label htmlFor="similarity-cutoff">Cutoff Threshold</Label>
                    <div className="flex items-center gap-4">
                      <Input
                        id="similarity-cutoff"
                        type="number" min={0} max={1} step={0.05}
                        value={localSettings.similarity_filter_cutoff}
                        onChange={(e) => updateField('similarity_filter_cutoff', parseFloat(e.target.value) || 0.3)}
                        className="w-24"
                      />
                      <span className="text-sm text-muted-foreground">
                        Score &lt; {localSettings.similarity_filter_cutoff} → dropped
                      </span>
                    </div>
                  </div>
                )}

                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="long-context-reorder">Long Context Reorder</Label>
                    <p className="text-sm text-muted-foreground">
                      Reorder nodes for better attention distribution
                    </p>
                  </div>
                  <Switch
                    id="long-context-reorder"
                    checked={localSettings.enable_long_context_reorder}
                    onCheckedChange={(checked) => updateField('enable_long_context_reorder', checked)}
                  />
                </div>

                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="semantic-chunking">Semantic Chunking</Label>
                    <p className="text-sm text-muted-foreground">
                      Split documents by semantic similarity
                    </p>
                  </div>
                  <Switch
                    id="semantic-chunking"
                    checked={localSettings.use_semantic_chunking}
                    onCheckedChange={(checked) => updateField('use_semantic_chunking', checked)}
                  />
                </div>
              </CardContent>
            </Card>

            {/* Response Section */}
            <Card>
              <CardHeader>
                <CardTitle>Response Settings</CardTitle>
                <CardDescription>Configure how responses are generated</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="response-mode">Response Mode</Label>
                  <Select
                    value={localSettings.response_mode}
                    onValueChange={(v) => updateField('response_mode', v)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="compact">Compact</SelectItem>
                      <SelectItem value="refine">Refine</SelectItem>
                      <SelectItem value="tree_summarize">Tree Summarize</SelectItem>
                      <SelectItem value="simple">Simple</SelectItem>
                      <SelectItem value="accumulate">Accumulate</SelectItem>
                    </SelectContent>
                  </Select>
                  <div className="text-xs text-muted-foreground space-y-1 mt-2">
                    <div><Badge variant="outline">compact</Badge> Combine context into single response</div>
                    <div><Badge variant="outline">refine</Badge> Iteratively refine answer</div>
                    <div><Badge variant="outline">tree_summarize</Badge> Summarize from multiple sources</div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Ingestion Pipeline</CardTitle>
                <CardDescription>Reference detection, text normalization &amp; caching during document embedding</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="ingestion-pipeline">Enable IngestionPipeline</Label>
                    <p className="text-sm text-muted-foreground">
                      Apply reference detection, text cleaning, and caching during import
                    </p>
                  </div>
                  <Switch
                    id="ingestion-pipeline"
                    checked={localSettings.use_ingestion_pipeline}
                    onCheckedChange={(checked) => updateField('use_ingestion_pipeline', checked)}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="context-enrich">Context Enrichment</Label>
                    <p className="text-sm text-muted-foreground">
                      Prepend doc name, source, and category to chunk text before embedding
                    </p>
                  </div>
                  <Switch
                    id="context-enrich"
                    checked={localSettings.enable_context_enrichment}
                    onCheckedChange={(checked) => updateField('enable_context_enrichment', checked)}
                  />
                </div>
              </CardContent>
            </Card>

            {/* Reference Filtering */}
            <Card>
              <CardHeader>
                <CardTitle>Reference Filtering</CardTitle>
                <CardDescription>How to handle bibliography and citation sections during import and retrieval</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="ref-strategy">Reference Strategy</Label>
                  <Select
                    value={localSettings.reference_strategy}
                    onValueChange={(v) => updateField('reference_strategy', v)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="flag">Flag (mark & downrank)</SelectItem>
                      <SelectItem value="skip">Skip (exclude at import)</SelectItem>
                      <SelectItem value="none">None (no filtering)</SelectItem>
                    </SelectContent>
                  </Select>
                  <div className="text-xs text-muted-foreground space-y-1 mt-2">
                    <div><Badge variant="outline">flag</Badge> Mark references, downrank 70% at retrieval time</div>
                    <div><Badge variant="outline">skip</Badge> Completely exclude reference chunks during import</div>
                    <div><Badge variant="outline">none</Badge> No reference detection or filtering</div>
                  </div>
                </div>

                {localSettings.reference_strategy !== 'none' && (
                  <div className="bg-muted/50 rounded-lg p-4 space-y-4">
                    <p className="text-sm font-medium">Reference Detection Thresholds</p>
                    <div className="grid grid-cols-3 gap-4">
                      <div className="space-y-2">
                        <Label htmlFor="ref-strong">Strong Signal Ratio</Label>
                        <Input
                          id="ref-strong"
                          type="number"
                          min={0.1}
                          max={1.0}
                          step={0.05}
                          value={localSettings.reference_strong_ratio}
                          onChange={(e) => updateField('reference_strong_ratio', parseFloat(e.target.value) || 0.5)}
                        />
                        <p className="text-xs text-muted-foreground">Direct判定阈值</p>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="ref-moderate">Moderate Ratio</Label>
                        <Input
                          id="ref-moderate"
                          type="number"
                          min={0.1}
                          max={1.0}
                          step={0.05}
                          value={localSettings.reference_moderate_ratio}
                          onChange={(e) => updateField('reference_moderate_ratio', parseFloat(e.target.value) || 0.3)}
                        />
                        <p className="text-xs text-muted-foreground">中等信号比例阈值</p>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="ref-weak">Weak Ratio</Label>
                        <Input
                          id="ref-weak"
                          type="number"
                          min={0.1}
                          max={1.0}
                          step={0.05}
                          value={localSettings.reference_weak_ratio}
                          onChange={(e) => updateField('reference_weak_ratio', parseFloat(e.target.value) || 0.4)}
                        />
                        <p className="text-xs text-muted-foreground">弱信号比例阈值</p>
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-4">
                      <div className="space-y-2">
                        <Label htmlFor="ref-mod-matches">Moderate Min Matches</Label>
                        <Input
                          id="ref-mod-matches"
                          type="number"
                          min={1}
                          max={20}
                          value={localSettings.reference_moderate_min_matches}
                          onChange={(e) => updateField('reference_moderate_min_matches', parseInt(e.target.value) || 5)}
                        />
                        <p className="text-xs text-muted-foreground">中等信号最小匹配数</p>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="ref-weak-matches">Weak Min Matches</Label>
                        <Input
                          id="ref-weak-matches"
                          type="number"
                          min={1}
                          max={20}
                          value={localSettings.reference_weak_min_matches}
                          onChange={(e) => updateField('reference_weak_min_matches', parseInt(e.target.value) || 3)}
                        />
                        <p className="text-xs text-muted-foreground">弱信号最小匹配数</p>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="ref-weak-strong">Weak Min Strong</Label>
                        <Input
                          id="ref-weak-strong"
                          type="number"
                          min={1}
                          max={10}
                          value={localSettings.reference_weak_min_strong}
                          onChange={(e) => updateField('reference_weak_min_strong', parseInt(e.target.value) || 2)}
                        />
                        <p className="text-xs text-muted-foreground">弱信号最小强匹配数</p>
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            <Button onClick={() => handleSave('Search')} disabled={updateSettings.isPending}>
              {updateSettings.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save Search Settings
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="chunk">
          <Card>
            <CardHeader>
              <CardTitle>Chunking Settings</CardTitle>
              <CardDescription>Configure how documents are split into chunks</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="chunk-strategy">Chunk Strategy</Label>
                <Select
                  value={localSettings.chunk_strategy}
                  onValueChange={(v) => updateField('chunk_strategy', v)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="hierarchical">Hierarchical (Parent-Child)</SelectItem>
                    <SelectItem value="sentence">Sentence (Fixed Size)</SelectItem>
                    <SelectItem value="window">Window (Context-Aware)</SelectItem>
                    <SelectItem value="semantic">Semantic (Embedding-based)</SelectItem>
                    <SelectItem value="markdown">Markdown (Heading-based)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {localSettings.chunk_strategy === 'hierarchical' ? (
                <>
                  <div className="bg-muted/50 rounded-lg p-4 space-y-3">
                    <p className="text-sm font-medium">Hierarchical Chunk Sizes</p>
                    <p className="text-xs text-muted-foreground">
                      Creates 3 levels of chunks for Auto-Merging Retriever.
                      Parent chunks are the largest, leaf chunks are the smallest.
                    </p>
                    <div className="grid grid-cols-3 gap-4">
                      <div className="space-y-2">
                        <Label htmlFor="parent-size" className="text-xs">Parent (Largest)</Label>
                        <Input
                          id="parent-size"
                          type="number"
                          min={256}
                          max={4096}
                          value={localSettings.hierarchical_chunk_sizes?.[0] || 1024}
                          onChange={(e) => {
                            const sizes = [...(localSettings.hierarchical_chunk_sizes || [1024, 512, 256])]
                            sizes[0] = parseInt(e.target.value) || 1024
                            updateField('hierarchical_chunk_sizes', sizes)
                          }}
                        />
                        <p className="text-xs text-muted-foreground">Coarse retrieval</p>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="child-size" className="text-xs">Child</Label>
                        <Input
                          id="child-size"
                          type="number"
                          min={128}
                          max={2048}
                          value={localSettings.hierarchical_chunk_sizes?.[1] || 512}
                          onChange={(e) => {
                            const sizes = [...(localSettings.hierarchical_chunk_sizes || [1024, 512, 256])]
                            sizes[1] = parseInt(e.target.value) || 512
                            updateField('hierarchical_chunk_sizes', sizes)
                          }}
                        />
                        <p className="text-xs text-muted-foreground">Medium chunks</p>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="leaf-size" className="text-xs">Leaf (Smallest)</Label>
                        <Input
                          id="leaf-size"
                          type="number"
                          min={64}
                          max={1024}
                          value={localSettings.hierarchical_chunk_sizes?.[2] || 256}
                          onChange={(e) => {
                            const sizes = [...(localSettings.hierarchical_chunk_sizes || [1024, 512, 256])]
                            sizes[2] = parseInt(e.target.value) || 256
                            updateField('hierarchical_chunk_sizes', sizes)
                          }}
                        />
                        <p className="text-xs text-muted-foreground">Fine-grained</p>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="chunk-overlap">Chunk Overlap</Label>
                    <Input
                      id="chunk-overlap"
                      type="number"
                      min={0}
                      max={500}
                      value={localSettings.chunk_overlap}
                      onChange={(e) => updateField('chunk_overlap', parseInt(e.target.value) || 100)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Overlap between chunks at each level
                    </p>
                  </div>
                </>
              ) : localSettings.chunk_strategy === 'window' ? (
                <div className="space-y-2 p-4 bg-muted/50 rounded-lg">
                  <Label htmlFor="window-size">Window Size (sentences)</Label>
                  <Input
                    id="window-size"
                    type="number" min={1} max={10}
                    value={localSettings.window_size}
                    onChange={(e) => updateField('window_size', parseInt(e.target.value) || 3)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Surrounding sentences per chunk for context-aware retrieval
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="chunk-size">Chunk Size</Label>
                      <Input
                        id="chunk-size"
                        type="number"
                        min={100}
                        max={4096}
                        value={localSettings.chunk_size}
                        onChange={(e) => updateField('chunk_size', parseInt(e.target.value) || 1024)}
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="chunk-overlap">Chunk Overlap</Label>
                      <Input
                        id="chunk-overlap"
                        type="number"
                        min={0}
                        max={500}
                        value={localSettings.chunk_overlap}
                        onChange={(e) => updateField('chunk_overlap', parseInt(e.target.value) || 100)}
                      />
                    </div>
                  </div>
                  {localSettings.chunk_strategy === 'semantic' && (
                    <div className="space-y-4 bg-muted/50 rounded-lg p-4">
                      <p className="text-sm font-medium">Semantic Chunking Thresholds</p>
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                          <Label htmlFor="sem-similarity-thresh">Similarity Threshold</Label>
                          <Input
                            id="sem-similarity-thresh"
                            type="number"
                            min={0.1}
                            max={1.0}
                            step={0.05}
                            value={localSettings.semantic_chunking_similarity_threshold}
                            onChange={(e) => updateField('semantic_chunking_similarity_threshold', parseFloat(e.target.value) || 0.5)}
                          />
                          <p className="text-xs text-muted-foreground">
                            Split when similarity drops below this (higher = finer chunks)
                          </p>
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="sem-percentile-thresh">Percentile Threshold</Label>
                          <Input
                            id="sem-percentile-thresh"
                            type="number"
                            min={0.1}
                            max={1.0}
                            step={0.05}
                            value={localSettings.semantic_chunking_percentile_threshold ?? ''}
                            onChange={(e) => {
                              const val = e.target.value
                              updateField('semantic_chunking_percentile_threshold', val ? parseFloat(val) : null)
                            }}
                            placeholder="Optional"
                          />
                          <p className="text-xs text-muted-foreground">
                            Alternative: split at percentile (leave empty to use similarity)
                          </p>
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="space-y-2">
                    <Label htmlFor="embed-batch-size">Embedding Batch Size</Label>
                    <Input
                      id="embed-batch-size"
                      type="number"
                      min={1}
                      max={256}
                      value={localSettings.embed_batch_size}
                      onChange={(e) => updateField('embed_batch_size', parseInt(e.target.value) || 32)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Number of texts to embed in a single batch
                    </p>
                  </div>
                </div>
              )}

              <Button onClick={() => handleSave('Chunk')} disabled={updateSettings.isPending}>
                {updateSettings.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save Chunk Settings
              </Button>

              <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-3 mt-4">
                <p className="text-sm text-amber-600 dark:text-amber-400">
                  <strong>Note:</strong> These settings only affect new document imports.
                  Existing knowledge bases will continue using their original chunking configuration.
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="system">
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>System Administration</CardTitle>
                <CardDescription>Restart services and reload configuration</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="space-y-4">
                  <div className="flex items-start justify-between gap-4 p-4 border rounded-lg border-destructive/50">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <RotateCcw className="h-5 w-5 text-destructive" />
                        <Label className="text-base">Restart API</Label>
                      </div>
                      <p className="text-sm text-muted-foreground">
                        Fully restart the API server and embedded task scheduler.
                        This will interrupt all ongoing requests.
                        Use when the service is in an inconsistent state or after major config changes.
                      </p>
                    </div>
                    <Button
                      variant="destructive"
                      onClick={handleRestartApi}
                      disabled={restartApi.isPending}
                    >
                      {restartApi.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                      Restart API
                    </Button>
                  </div>

                  <div className="flex items-start justify-between gap-4 p-4 border rounded-lg">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <RotateCcw className="h-5 w-5" />
                        <Label className="text-base">Reload Configuration</Label>
                      </div>
                      <p className="text-sm text-muted-foreground">
                        Hot-reload model registry, runtime settings, and embedding endpoints without restarting.
                        Use after changing LLM/Embedding model settings or system parameters.
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      onClick={handleReloadConfig}
                      disabled={reloadConfig.isPending}
                    >
                      {reloadConfig.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                      Reload
                    </Button>
                  </div>

                  <div className="flex items-start justify-between gap-4 p-4 border rounded-lg border-amber-500/30">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <RotateCcw className="h-5 w-5 text-amber-500" />
                        <Label className="text-base">Reset to Defaults</Label>
                      </div>
                      <p className="text-sm text-muted-foreground">
                        Clear all persisted settings and restore factory defaults.
                        Use when settings are stale or misconfigured.
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      onClick={handleResetDefaults}
                      disabled={resetSettings.isPending}
                    >
                      {resetSettings.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                      Reset
                    </Button>
                  </div>
                </div>

                <div className="bg-muted/50 p-4 rounded-lg">
                  <h4 className="font-medium mb-2">When to use these:</h4>
                  <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
                    <li><strong>Restart API</strong> — Full restart of API + embedded scheduler. Use when the service is unresponsive, after model/vendor changes, or when tasks are stuck.</li>
                    <li><strong>Reload Configuration</strong> — Hot-reload without downtime. Use for runtime settings changes (top_k, chunk sizes, etc.) that don't require a full restart.</li>
                    <li><strong>Reset to Defaults</strong> — Clear all persisted overrides. Use after upgrading when old cached settings conflict with new defaults.</li>
                  </ul>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Task Processing</CardTitle>
                <CardDescription>Configure task execution behavior</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="progress-interval">Progress Update Interval</Label>
                    <Input
                      id="progress-interval"
                      type="number"
                      min={1}
                      max={100}
                      value={localSettings.progress_update_interval}
                      onChange={(e) => updateField('progress_update_interval', parseInt(e.target.value) || 10)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Update task progress every N files processed
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="max-concurrent">Max Concurrent Tasks</Label>
                    <Input
                      id="max-concurrent"
                      type="number"
                      min={1}
                      max={50}
                      value={localSettings.max_concurrent_tasks}
                      onChange={(e) => updateField('max_concurrent_tasks', parseInt(e.target.value) || 10)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Maximum simultaneous import/processing tasks
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Embedding Retry</CardTitle>
                <CardDescription>Configure resilience for embedding API calls</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="max-retries">Max Retries</Label>
                    <Input
                      id="max-retries"
                      type="number"
                      min={1}
                      max={20}
                      value={localSettings.max_retries}
                      onChange={(e) => updateField('max_retries', parseInt(e.target.value) || 5)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Retry failed embedding calls up to N times
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="retry-delay">Retry Delay (seconds)</Label>
                    <Input
                      id="retry-delay"
                      type="number"
                      min={0.5}
                      max={30}
                      step={0.5}
                      value={localSettings.retry_delay}
                      onChange={(e) => updateField('retry_delay', parseFloat(e.target.value) || 2.0)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Wait time between retry attempts
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Embedding Concurrency</CardTitle>
                <CardDescription>Control parallel embedding throughput</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="embed-pool">Thread Pool Size</Label>
                    <Input
                      id="embed-pool"
                      type="number"
                      min={4}
                      max={64}
                      value={localSettings.embed_concurrent_pool_size}
                      onChange={(e) => updateField('embed_concurrent_pool_size', parseInt(e.target.value) || 16)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Total embedding worker threads across all endpoints
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="embed-endpoint">Per-Endpoint Max</Label>
                    <Input
                      id="embed-endpoint"
                      type="number"
                      min={1}
                      max={32}
                      value={localSettings.embed_endpoint_max_concurrent}
                      onChange={(e) => updateField('embed_endpoint_max_concurrent', parseInt(e.target.value) || 8)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Max concurrent requests per single endpoint
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Embedding Thresholds</CardTitle>
                <CardDescription>Control embedding parallelism based on text length</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="short-thresh">Short Text Threshold</Label>
                    <Input
                      id="short-thresh"
                      type="number"
                      min={100}
                      max={5000}
                      value={localSettings.ollama_short_text_threshold}
                      onChange={(e) => updateField('ollama_short_text_threshold', parseInt(e.target.value) || 600)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Texts shorter than this use single endpoint
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="fanout-thresh">Fanout Threshold</Label>
                    <Input
                      id="fanout-thresh"
                      type="number"
                      min={500}
                      max={10000}
                      value={localSettings.ollama_fanout_text_threshold}
                      onChange={(e) => updateField('ollama_fanout_text_threshold', parseInt(e.target.value) || 1800)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Texts longer than this use fanout to all endpoints
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Task Heartbeat</CardTitle>
                <CardDescription>Configure task liveliness monitoring</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="heartbeat">Heartbeat Interval (s)</Label>
                    <Input
                      id="heartbeat"
                      type="number"
                      min={10}
                      max={600}
                      value={localSettings.heartbeat_interval}
                      onChange={(e) => updateField('heartbeat_interval', parseInt(e.target.value) || 30)}
                    />
                    <p className="text-xs text-muted-foreground">
                      How often tasks report liveness
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="stale-timeout">Stale Task Timeout (s)</Label>
                    <Input
                      id="stale-timeout"
                      type="number"
                      min={60}
                      max={3600}
                      value={localSettings.stale_task_timeout}
                      onChange={(e) => updateField('stale_task_timeout', parseInt(e.target.value) || 300)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Tasks without heartbeat for this long are marked stale
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>OCR & API</CardTitle>
                <CardDescription>OCR pipeline and network configuration</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="mineru-key">MinerU API Key</Label>
                    <Input
                      id="mineru-key"
                      type="password"
                      value={localSettings.mineru_api_key}
                      onChange={(e) => updateField('mineru_api_key', e.target.value)}
                      placeholder="Stored in .env"
                    />
                    <p className="text-xs text-muted-foreground">
                      Primary source: MINERU_API_KEY in .env
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="doc2x-key">doc2x API Key</Label>
                    <Input
                      id="doc2x-key"
                      type="password"
                      value={localSettings.doc2x_api_key}
                      onChange={(e) => updateField('doc2x_api_key', e.target.value)}
                      placeholder="Stored in .env"
                    />
                    <p className="text-xs text-muted-foreground">
                      Primary source: DOC2X_API_KEY in .env
                    </p>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="mineru-pipeline">MinerU Pipeline ID</Label>
                  <Input
                    id="mineru-pipeline"
                    value={localSettings.mineru_pipeline_id}
                    onChange={(e) => updateField('mineru_pipeline_id', e.target.value)}
                    placeholder="e.g. vlm"
                  />
                  <p className="text-xs text-muted-foreground">
                    OCR pipeline for MinerU scanned PDF processing
                  </p>
                </div>

                <div className="bg-muted/50 rounded-lg p-4 space-y-4">
                  <p className="text-sm font-medium">PDF Scanned Detection</p>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="pdf-scan-thresh">Scan Density Threshold</Label>
                      <Input
                        id="pdf-scan-thresh"
                        type="number"
                        min={0}
                        max={100}
                        step={0.5}
                        value={localSettings.pdf_scan_threshold}
                        onChange={(e) => updateField('pdf_scan_threshold', parseFloat(e.target.value) || 10)}
                      />
                      <p className="text-xs text-muted-foreground">
                        Text density (chars/sq inch). Below this = scanned PDF
                      </p>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="pdf-image-ratio">Image Ratio Threshold</Label>
                      <Input
                        id="pdf-image-ratio"
                        type="number"
                        min={0}
                        max={1}
                        step={0.05}
                        value={localSettings.pdf_image_ratio_threshold}
                        onChange={(e) => updateField('pdf_image_ratio_threshold', parseFloat(e.target.value) || 0.8)}
                      />
                      <p className="text-xs text-muted-foreground">
                        Image coverage ratio. Above this = scanned PDF
                      </p>
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="api-port">API Port</Label>
                    <Input
                      id="api-port"
                      type="number"
                      min={1024}
                      max={65535}
                      value={localSettings.api_port}
                      onChange={(e) => updateField('api_port', parseInt(e.target.value) || 37241)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Requires restart to take effect
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="cors-origins">CORS Extra Origins</Label>
                    <Input
                      id="cors-origins"
                      value={localSettings.cors_extra_origins}
                      onChange={(e) => updateField('cors_extra_origins', e.target.value)}
                      placeholder="http://192.168.1.100:5173"
                    />
                    <p className="text-xs text-muted-foreground">
                      Comma-separated. Requires restart.
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Button onClick={() => handleSave('System')} disabled={updateSettings.isPending}>
              {updateSettings.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save System Settings
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="observability">
          <div className="mb-4 space-y-4">
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">Date Range:</span>
                <div className="flex gap-1">
                  <Button size="sm" variant={!startDate && !endDate ? "default" : "outline"} onClick={() => handleQuickDateFilter(null)}>
                    All
                  </Button>
                  <Button size="sm" variant={startDate === new Date().toISOString().split('T')[0] ? "default" : "outline"} onClick={() => handleQuickDateFilter(0)}>
                    Today
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => handleQuickDateFilter(7)}>
                    7 Days
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => handleQuickDateFilter(30)}>
                    30 Days
                  </Button>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-36"
                  placeholder="Start date"
                />
                <span className="text-muted-foreground">to</span>
                <Input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-36"
                  placeholder="End date"
                />
                {(startDate || endDate) && (
                  <Button size="sm" variant="ghost" onClick={() => { setStartDate(''); setEndDate('') }}>
                    Clear
                  </Button>
                )}
              </div>
            </div>
            <div className="flex items-center justify-between">
              <div className="text-sm text-muted-foreground">
                {availableDates?.dates && availableDates.dates.length > 0 && (
                  <span>Available dates: {availableDates.dates.length} days</span>
                )}
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => { refetchStats(); refetchTraces() }}>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Refresh
                </Button>
                <Button variant="destructive" onClick={handleResetObservability} disabled={resetStats.isPending}>
                  {resetStats.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                  Reset
                </Button>
              </div>
            </div>
          </div>

          <Tabs defaultValue="overview" className="w-full">
            <TabsList>
              <TabsTrigger value="overview">
                <BarChart3 className="mr-2 h-4 w-4" />
                Overview
              </TabsTrigger>
              <TabsTrigger value="vendors">
                <Server className="mr-2 h-4 w-4" />
                Vendors
              </TabsTrigger>
              <TabsTrigger value="traces">
                <Activity className="mr-2 h-4 w-4" />
                Traces
              </TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="mt-4">
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium text-muted-foreground">
                      Total Calls
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-bold">
                      {stats?.total_calls?.toLocaleString() || 0}
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium text-muted-foreground">
                      Total Tokens
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-bold">
                      {stats?.total_tokens?.toLocaleString() || 0}
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium text-muted-foreground">
                      Vendors
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-bold">
                      {stats?.vendor_stats?.length || 0}
                    </div>
                  </CardContent>
                </Card>
              </div>

              {stats?.vendor_stats && stats.vendor_stats.length > 0 && (
                <Card className="mt-4">
                  <CardHeader>
                    <CardTitle>Vendors Summary</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {stats.vendor_stats.map((vendor: VendorStats) => (
                        <div key={vendor.vendor_id} className="flex items-center justify-between p-3 border rounded-lg">
                          <div className="flex items-center gap-3">
                            <Server className="h-4 w-4 text-muted-foreground" />
                            <span className="font-medium">{vendor.vendor_id}</span>
                            <Badge variant="secondary">{vendor.models?.length || 0} models</Badge>
                          </div>
                          <div className="flex items-center gap-4 text-sm">
                            <span>
                              <span className="text-muted-foreground">calls: </span>
                              <span className="font-medium">{vendor.total_calls.toLocaleString()}</span>
                            </span>
                            <span>
                              <span className="text-muted-foreground">tokens: </span>
                              <span className="font-medium">{vendor.total_tokens.toLocaleString()}</span>
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </TabsContent>

            <TabsContent value="vendors" className="mt-4">
              {statsLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : stats?.vendor_stats && stats.vendor_stats.length > 0 ? (
                <div>
                  {stats.vendor_stats.map((vendor: VendorStats) => (
                    <VendorPanel key={vendor.vendor_id} vendor={vendor} />
                  ))}
                </div>
              ) : (
                <Card>
                  <CardContent className="flex items-center justify-center py-12">
                    <div className="text-center">
                      <Server className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                      <p className="text-lg font-medium">No vendor data</p>
                      <p className="text-sm text-muted-foreground mt-1">
                        Model call statistics will appear here after making API calls
                      </p>
                    </div>
                  </CardContent>
                </Card>
              )}
            </TabsContent>

            <TabsContent value="traces" className="mt-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Clock className="h-5 w-5" />
                    Recent Traces
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {tracesLoading ? (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                    </div>
                  ) : traces && traces.traces && traces.traces.length > 0 ? (
                    <ScrollArea className="h-96">
                      <div className="space-y-2">
                        {traces.traces.map((trace, index) => (
                          <div key={index} className="p-3 border rounded-lg">
                            <div className="flex items-center justify-between mb-2">
                              <div className="flex items-center gap-2">
                                <Badge variant="outline">{trace.retrieval_count} ret</Badge>
                                <span className="text-sm text-muted-foreground">
                                  {new Date(trace.timestamp).toLocaleString()}
                                </span>
                              </div>
                              <span className="text-sm font-medium">
                                {trace.duration_ms.toFixed(0)} ms
                              </span>
                            </div>
                            <p className="text-sm mb-2 line-clamp-2">{trace.query}</p>
                            <div className="flex gap-4 text-xs text-muted-foreground">
                              <span>LLM: {trace.llm_input_tokens} → {trace.llm_output_tokens} tokens</span>
                              <span>Embed: {trace.embedding_tokens} tokens</span>
                              <span>Total: {trace.total_tokens} tokens</span>
                              {trace.error && <span className="text-red-500">Error: {trace.error}</span>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </ScrollArea>
                  ) : (
                    <p className="text-muted-foreground text-center py-4">No traces available</p>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </TabsContent>
      </Tabs>
    </div>
  )
}

export function Settings() {
  return <SettingsPage />
}
