import { useState, useEffect } from 'react'
import { useSettings, useUpdateSettings, useModels, useRestartScheduler, useReloadConfig } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Settings2, Brain, Search, Layers, Shield, MessageSquare, Loader2, AlertCircle, RotateCcw, Server } from 'lucide-react'
import { toast } from 'sonner'
import type { SystemSettings } from '@/types/api'

export function SettingsPage() {
  const { data: settings, isLoading, error } = useSettings()
  const { data: llmModels } = useModels('llm')
  const { data: embeddingModels } = useModels('embedding')
  const updateSettings = useUpdateSettings()
  const restartScheduler = useRestartScheduler()
  const reloadConfig = useReloadConfig()

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

  const updateField = <K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) => {
    if (localSettings) {
      setLocalSettings({ ...localSettings, [key]: value })
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

      <Tabs defaultValue="retrieval" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="llm">
            <Brain className="mr-2 h-4 w-4" />
            LLM
          </TabsTrigger>
          <TabsTrigger value="embedding">
            <Layers className="mr-2 h-4 w-4" />
            Embedding
          </TabsTrigger>
          <TabsTrigger value="retrieval">
            <Search className="mr-2 h-4 w-4" />
            Retrieval
          </TabsTrigger>
          <TabsTrigger value="chunk">
            <Layers className="mr-2 h-4 w-4" />
            Chunk
          </TabsTrigger>
          <TabsTrigger value="reranker">
            <Shield className="mr-2 h-4 w-4" />
            Reranker
          </TabsTrigger>
          <TabsTrigger value="response">
            <MessageSquare className="mr-2 h-4 w-4" />
            Response
          </TabsTrigger>
          <TabsTrigger value="system">
            <Server className="mr-2 h-4 w-4" />
            System
          </TabsTrigger>
        </TabsList>

        <TabsContent value="llm">
          <Card>
            <CardHeader>
              <CardTitle>LLM Settings</CardTitle>
              <CardDescription>Configure language model settings</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="llm-mode">LLM Mode</Label>
                <Select
                  value={localSettings.llm_mode}
                  onValueChange={(v) => updateField('llm_mode', v)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ollama">Ollama (Local)</SelectItem>
                    <SelectItem value="siliconflow">SiliconFlow (Cloud)</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Requires restart to take effect
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="default-llm">Default LLM Model</Label>
                <Select
                  value={localSettings.default_llm_model || ''}
                  onValueChange={(v) => updateField('default_llm_model', v)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select default model..." />
                  </SelectTrigger>
                  <SelectContent>
                    {llmModels?.map((model) => (
                      <SelectItem key={model.id} value={model.id}>
                        {model.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Requires restart to take effect
                </p>
              </div>

              <Button onClick={() => handleSave('LLM')} disabled={updateSettings.isPending}>
                {updateSettings.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save LLM Settings
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="embedding">
          <Card>
            <CardHeader>
              <CardTitle>Embedding Settings</CardTitle>
              <CardDescription>Configure embedding model settings</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="embed-model">Embedding Model</Label>
                <Select
                  value={localSettings.ollama_embed_model}
                  onValueChange={(v) => updateField('ollama_embed_model', v)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {embeddingModels?.map((model) => (
                      <SelectItem key={model.id} value={model.id}>
                        {model.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Requires restart to take effect
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="ollama-url">Ollama Base URL</Label>
                <Input
                  id="ollama-url"
                  value={localSettings.ollama_base_url}
                  onChange={(e) => updateField('ollama_base_url', e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Requires restart to take effect
                </p>
              </div>

              <Button onClick={() => handleSave('Embedding')} disabled={updateSettings.isPending}>
                {updateSettings.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save Embedding Settings
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="retrieval">
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

              <Button onClick={() => handleSave('Retrieval')} disabled={updateSettings.isPending}>
                {updateSettings.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save Retrieval Settings
              </Button>
            </CardContent>
          </Card>
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
                    <SelectItem value="sentence">Sentence</SelectItem>
                    <SelectItem value="semantic">Semantic</SelectItem>
                  </SelectContent>
                </Select>
              </div>

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

              <Button onClick={() => handleSave('Chunk')} disabled={updateSettings.isPending}>
                {updateSettings.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save Chunk Settings
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="reranker">
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

              {localSettings.use_reranker && (
                <div className="space-y-2">
                  <Label htmlFor="rerank-model">Reranker Model</Label>
                  <Input
                    id="rerank-model"
                    value={localSettings.rerank_model}
                    onChange={(e) => updateField('rerank_model', e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Requires restart to take effect
                  </p>
                </div>
              )}

              <Button onClick={() => handleSave('Reranker')} disabled={updateSettings.isPending}>
                {updateSettings.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save Reranker Settings
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="response">
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
                    <SelectItem value="no_text">No Text</SelectItem>
                    <SelectItem value="accumulate">Accumulate</SelectItem>
                  </SelectContent>
                </Select>
                <div className="text-xs text-muted-foreground space-y-1 mt-2">
                  <p><Badge variant="outline">compact</Badge> Combine context into single response</p>
                  <p><Badge variant="outline">refine</Badge> Iteratively refine answer</p>
                  <p><Badge variant="outline">tree_summarize</Badge> Summarize from multiple sources</p>
                </div>
              </div>

              <Button onClick={() => handleSave('Response')} disabled={updateSettings.isPending}>
                {updateSettings.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save Response Settings
              </Button>
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

              <div className="bg-muted/50 p-4 rounded-lg">
                <h4 className="font-medium mb-2">When to use these:</h4>
                <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
                  <li><strong>Restart Scheduler</strong> - After adding/removing models, or when tasks are stuck</li>
                  <li><strong>Reload Configuration</strong> - After changing LLM/Embedding settings that show "Requires restart"</li>
                </ul>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

export function Settings() {
  return <SettingsPage />
}
