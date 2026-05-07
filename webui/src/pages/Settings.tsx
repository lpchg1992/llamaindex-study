import { useState, useEffect } from 'react'
import { useSettings, useUpdateSettings, useRestartScheduler, useReloadConfig, useRestartApi, useKBs, useEvaluate, useObservabilityStats, useResetObservability, useTraces, useObservabilityDates } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
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
import { Settings2, Brain, Search, Layers, Loader2, AlertCircle, RotateCcw, Server, LineChart, Activity, Cpu, BarChart3, Clock, Trash2, ChevronDown, ChevronRight, CheckCircle, XCircle, RefreshCw } from 'lucide-react'
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
  const restartScheduler = useRestartScheduler()
  const reloadConfig = useReloadConfig()
  const restartApi = useRestartApi()

  // Evaluate hooks and state
  const { data: kbs } = useKBs()
  const evaluateMutation = useEvaluate()
  const [selectedKB, setSelectedKB] = useState<string>('')
  const [questions, setQuestions] = useState<string[]>([''])
  const [groundTruths, setGroundTruths] = useState<string[]>([''])
  const [results, setResults] = useState<any>(null)

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

  const handleRestartScheduler = async () => {
    try {
      await restartScheduler.mutateAsync()
      toast.success('Scheduler restarted')
    } catch (err) {
      toast.error('Failed to restart scheduler')
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

  const updateField = <K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) => {
    if (localSettings) {
      setLocalSettings({ ...localSettings, [key]: value })
    }
  }

  // Evaluate handlers
  const addQA = () => {
    setQuestions([...questions, ''])
    setGroundTruths([...groundTruths, ''])
  }

  const updateQuestion = (index: number, value: string) => {
    const newQuestions = [...questions]
    newQuestions[index] = value
    setQuestions(newQuestions)
  }

  const updateGroundTruth = (index: number, value: string) => {
    const newGroundTruths = [...groundTruths]
    newGroundTruths[index] = value
    setGroundTruths(newGroundTruths)
  }

  const handleEvaluate = async () => {
    if (!selectedKB) return
    const validQuestions = questions.filter((q) => q.trim())
    const validGroundTruths = groundTruths.filter((g) => g.trim())
    if (validQuestions.length === 0) return

    try {
      const result = await evaluateMutation.mutateAsync({
        kbId: selectedKB,
        req: {
          questions: validQuestions,
          ground_truths: validGroundTruths.length === validQuestions.length
            ? validGroundTruths
            : validQuestions.map(() => ''),
          top_k: 5,
        },
      })
      setResults(result)
    } catch (error) {
      console.error('Evaluation failed:', error)
    }
  }

  const metrics = [
    { key: 'faithfulness', label: 'Faithfulness', description: 'Answer accuracy vs context' },
    { key: 'answer_relevancy', label: 'Answer Relevancy', description: 'Answer relevance to question' },
    { key: 'context_precision', label: 'Context Precision', description: 'Retrieval quality' },
    { key: 'context_recall', label: 'Context Recall', description: 'Context coverage' },
  ]

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
          <TabsTrigger value="evaluate">
            <LineChart className="mr-2 h-4 w-4" />
            Evaluate
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
                    <p><Badge variant="outline">compact</Badge> Combine context into single response</p>
                    <p><Badge variant="outline">refine</Badge> Iteratively refine answer</p>
                    <p><Badge variant="outline">tree_summarize</Badge> Summarize from multiple sources</p>
                  </div>
                </div>
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
                    <SelectItem value="semantic">Semantic (Embedding-based)</SelectItem>
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
                          min={512}
                          max={8192}
                          value={localSettings.hierarchical_chunk_sizes?.[0] || 2048}
                          onChange={(e) => {
                            const sizes = [...(localSettings.hierarchical_chunk_sizes || [2048, 1024, 512])]
                            sizes[0] = parseInt(e.target.value) || 2048
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
                          min={256}
                          max={4096}
                          value={localSettings.hierarchical_chunk_sizes?.[1] || 1024}
                          onChange={(e) => {
                            const sizes = [...(localSettings.hierarchical_chunk_sizes || [2048, 1024, 512])]
                            sizes[1] = parseInt(e.target.value) || 1024
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
                          min={128}
                          max={2048}
                          value={localSettings.hierarchical_chunk_sizes?.[2] || 512}
                          onChange={(e) => {
                            const sizes = [...(localSettings.hierarchical_chunk_sizes || [2048, 1024, 512])]
                            sizes[2] = parseInt(e.target.value) || 512
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
                    <p className="text-xs text-muted-foreground">
                      Semantic chunking uses embeddings to find natural breaking points.
                      Chunk size is a target, not a hard limit.
                    </p>
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
                      Fully restart the API server. This will interrupt all ongoing requests. Use when the service is in an inconsistent state.
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
                      <Label className="text-base">Restart Scheduler</Label>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      Restart the task scheduler. This will cancel any running tasks.
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    onClick={handleRestartScheduler}
                    disabled={restartScheduler.isPending}
                  >
                    {restartScheduler.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Restart
                  </Button>
                </div>

                <div className="flex items-start justify-between gap-4 p-4 border rounded-lg">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <RotateCcw className="h-5 w-5" />
                      <Label className="text-base">Reload Configuration</Label>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      Reload model registry and settings. Use after changing LLM/Embedding models to apply changes.
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
              </div>

              <div className="border rounded-lg p-4">
                <h4 className="font-medium mb-4">Task Processing Settings</h4>
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
                      Update progress every N files
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
                      Maximum simultaneous tasks
                    </p>
                  </div>
                </div>
              </div>

              <div className="border rounded-lg p-4 mt-4">
                <h4 className="font-medium mb-4">Embedding Retry Settings</h4>
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
                      Retry embedding calls up to N times on failure
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
              </div>

              <div className="bg-muted/50 p-4 rounded-lg">
                <h4 className="font-medium mb-2">When to use these:</h4>
                <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
                  <li><strong>Restart API</strong> - Full service restart. Use when the service is unresponsive or in an inconsistent state.</li>
                  <li><strong>Restart Scheduler</strong> - After adding/removing models, or when tasks are stuck</li>
                  <li><strong>Reload Configuration</strong> - After changing LLM/Embedding settings that show "Requires restart"</li>
                </ul>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="evaluate">
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>Configuration</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label>Knowledge Base</Label>
                    <Select value={selectedKB} onValueChange={setSelectedKB}>
                      <SelectTrigger>
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
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle>Questions & Ground Truths</CardTitle>
                    <Button variant="outline" size="sm" onClick={addQA}>
                      Add Q&A
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  {questions.map((question, index) => (
                    <div key={index} className="space-y-2">
                      <Label>Question {index + 1}</Label>
                      <Textarea
                        placeholder="Enter question..."
                        value={question}
                        onChange={(e) => updateQuestion(index, e.target.value)}
                      />
                      <Label>Ground Truth {index + 1}</Label>
                      <Textarea
                        placeholder="Enter expected answer..."
                        value={groundTruths[index]}
                        onChange={(e) => updateGroundTruth(index, e.target.value)}
                      />
                    </div>
                  ))}
                  <Button
                    onClick={handleEvaluate}
                    disabled={!selectedKB || questions.every((q) => !q.trim()) || evaluateMutation.isPending}
                  >
                    {evaluateMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    {evaluateMutation.isPending ? 'Evaluating...' : 'Run Evaluation'}
                  </Button>
                </CardContent>
              </Card>
            </div>

            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <LineChart className="h-5 w-5" />
                    Results
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {results ? (
                    <div className="space-y-4">
                      {metrics.map((metric) => {
                        const value = results[metric.key]
                        const isGood = value >= 0.8
                        const isBad = value < 0.5
                        return (
                          <div key={metric.key} className="space-y-2">
                            <div className="flex items-center justify-between">
                              <div>
                                <span className="font-medium">{metric.label}</span>
                                <p className="text-xs text-muted-foreground">
                                  {metric.description}
                                </p>
                              </div>
                              <div className="flex items-center gap-2">
                                {isGood && <CheckCircle className="h-4 w-4 text-green-500" />}
                                {isBad && <XCircle className="h-4 w-4 text-red-500" />}
                                <Badge
                                  variant={isGood ? 'default' : isBad ? 'destructive' : 'secondary'}
                                >
                                  {typeof value === 'number' ? (value * 100).toFixed(1) : 'N/A'}%
                                </Badge>
                              </div>
                            </div>
                            <div className="h-2 w-full rounded-full bg-secondary">
                              <div
                                className={`h-2 rounded-full transition-all ${
                                  isGood ? 'bg-green-500' : isBad ? 'bg-red-500' : 'bg-yellow-500'
                                }`}
                                style={{ width: `${Math.min((value || 0) * 100, 100)}%` }}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="text-center text-muted-foreground py-8">
                      Run evaluation to see results
                    </p>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Metrics Guide</CardTitle>
                </CardHeader>
                <CardContent className="text-sm space-y-2 text-muted-foreground">
                  <p><strong>Faithfulness:</strong> Measures how accurately the answer reflects the retrieved context. Low scores indicate hallucinations.</p>
                  <p><strong>Answer Relevancy:</strong> Measures how relevant the answer is to the question. Low scores indicate irrelevant answers.</p>
                  <p><strong>Context Precision:</strong> Measures how precisely the retrieved context matches the question. Low scores indicate poor retrieval.</p>
                  <p><strong>Context Recall:</strong> Measures how much of the relevant context was retrieved. Low scores indicate missing information.</p>
                </CardContent>
              </Card>
            </div>
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
