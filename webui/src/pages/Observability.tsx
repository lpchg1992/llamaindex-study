import { useObservabilityStats, useResetObservability, useTraces } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Loader2, RefreshCw, Activity, Cpu, BarChart3, Clock, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

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
          <TabsTrigger value="tokens">
            <Cpu className="mr-2 h-4 w-4" />
            Tokens
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
                  Total Queries
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {stats?.rag_stats?.total_queries || 0}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Total Retrievals
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {stats?.rag_stats?.total_retrievals || 0}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Avg Latency
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {stats?.rag_stats?.avg_latency_ms?.toFixed(2) || '0.00'} ms
                </div>
              </CardContent>
            </Card>
          </div>

          {stats?.rag_stats_formatted && (
            <Card className="mt-4">
              <CardHeader>
                <CardTitle>Formatted Stats</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="text-sm whitespace-pre-wrap bg-muted p-4 rounded-lg overflow-x-auto">
                  {stats.rag_stats_formatted}
                </pre>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="tokens" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Cpu className="h-5 w-5" />
                Token Usage
              </CardTitle>
            </CardHeader>
            <CardContent>
              {statsLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : stats?.token_stats ? (
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                  <div className="p-4 border rounded-lg">
                    <p className="text-sm text-muted-foreground">Prompt Tokens</p>
                    <p className="text-2xl font-bold">{stats.token_stats.prompt_tokens.toLocaleString()}</p>
                  </div>
                  <div className="p-4 border rounded-lg">
                    <p className="text-sm text-muted-foreground">Completion Tokens</p>
                    <p className="text-2xl font-bold">{stats.token_stats.completion_tokens.toLocaleString()}</p>
                  </div>
                  <div className="p-4 border rounded-lg">
                    <p className="text-sm text-muted-foreground">Total Tokens</p>
                    <p className="text-2xl font-bold">{stats.token_stats.total_tokens.toLocaleString()}</p>
                  </div>
                  <div className="p-4 border rounded-lg">
                    <p className="text-sm text-muted-foreground">Embedding Tokens</p>
                    <p className="text-2xl font-bold">{stats.token_stats.embedding_tokens.toLocaleString()}</p>
                  </div>
                </div>
              ) : (
                <p className="text-muted-foreground text-center py-4">No token data available</p>
              )}
              {stats?.token_stats_formatted && (
                <div className="mt-4">
                  <pre className="text-sm whitespace-pre-wrap bg-muted p-4 rounded-lg overflow-x-auto">
                    {stats.token_stats_formatted}
                  </pre>
                </div>
              )}
            </CardContent>
          </Card>
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