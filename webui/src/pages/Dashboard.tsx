import { useKBs, useKBTasks } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Database, ListTodo, Upload } from 'lucide-react'

export function Dashboard() {
  const { data: kbs, isLoading: kbsLoading } = useKBs()
  const { data: runningTasks } = useKBTasks(undefined, 'running')

  const totalDocs = kbs?.reduce((acc, kb) => acc + (kb.row_count || 0), 0) || 0

  const stats = [
    {
      title: 'Knowledge Bases',
      value: kbsLoading ? '...' : kbs?.length || 0,
      icon: Database,
      description: 'Total knowledge bases',
    },
    {
      title: 'Total Documents',
      value: totalDocs.toLocaleString(),
      icon: ListTodo,
      description: 'Across all knowledge bases',
    },
    {
      title: 'Running Tasks',
      value: runningTasks?.length || 0,
      icon: Upload,
      description: 'Currently processing',
    },
  ]

  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-bold">Dashboard</h1>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {stats.map((stat) => (
          <Card key={stat.title}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {stat.title}
              </CardTitle>
              <stat.icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
              <p className="text-xs text-muted-foreground">
                {stat.description}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="mt-8">
        <h2 className="mb-4 text-lg font-semibold">Knowledge Bases</h2>
        {kbsLoading ? (
          <p className="text-muted-foreground">Loading...</p>
        ) : kbs && kbs.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {kbs.map((kb) => (
              <Card key={kb.id}>
                <CardHeader>
                  <CardTitle className="text-base">{kb.name || kb.id}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">ID:</span>
                      <span className="font-mono">{kb.id}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Documents:</span>
                      <span>{kb.row_count?.toLocaleString() || 0}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Status:</span>
                      <span className="capitalize">{kb.status}</span>
                    </div>
                    {kb.chunk_strategy && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Chunk:</span>
                        <span>{kb.chunk_strategy}</span>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground">No knowledge bases found</p>
        )}
      </div>
    </div>
  )
}