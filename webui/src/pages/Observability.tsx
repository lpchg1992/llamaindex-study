import { useObservabilityStats, useResetObservability, useTraces } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Loader2, RefreshCw, Activity, Cpu, BarChart3, Clock, Trash2, ChevronDown, ChevronRight, Server } from 'lucide-react'
import { toast } from 'sonner'
import { useState } from 'react'
import type { VendorStats } from '@/types/api'

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

function VendorPanel({ vendor }: { vendor: VendorStats }) {
  const [expanded, setExpanded] = useState(true)

  const llmModels = vendor.models.filter((m: any) => m.model_type === 'llm')
  const embedModels = vendor.models.filter((m: any) => m.model_type === 'embedding')
  const rerankerModels = vendor.models.filter((m: any) => m.model_type === 'reranker')

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
              {vendor.models.length} model{vendor.models.length !== 1 ? 's' : ''}
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
          {vendor.models.length === 0 ? (
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

export function Observability() {
  const { data: stats, isLoading: statsLoading, refetch: refetchStats } = useObservabilityStats()
  const resetStats = useResetObservability()
  const { data: traces, isLoading: tracesLoading, refetch: refetchTraces } = useTraces(100)

  const handleReset = async () => {
    if (!confirm('Reset all observability data?')) return
    try {
      await resetStats.mutateAsync()
      toast.success('Observability data reset')
      refetchStats()
    } catch (error) {
      toast.error('Failed to reset')
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Observability</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => { refetchStats(); refetchTraces() }}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          <Button variant="destructive" onClick={handleReset} disabled={resetStats.isPending}>
            {resetStats.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
            Reset
          </Button>
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
                        <Badge variant="secondary">{vendor.models.length} models</Badge>
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
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Badge variant="outline">{trace.event_type}</Badge>
                            <span className="text-sm text-muted-foreground">
                              {new Date(trace.timestamp).toLocaleString()}
                            </span>
                          </div>
                          <span className="text-sm font-medium">
                            {trace.duration_ms.toFixed(2)} ms
                          </span>
                        </div>
                        {trace.metadata && Object.keys(trace.metadata).length > 0 && (
                          <pre className="text-xs text-muted-foreground mt-2 overflow-x-auto">
                            {JSON.stringify(trace.metadata, null, 2)}
                          </pre>
                        )}
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
    </div>
  )
}

export function ObservabilityPage() {
  return <Observability />
}
