import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Database, Server, Key } from 'lucide-react'

export function SettingsPage() {
  const settings = [
    {
      category: 'API Configuration',
      icon: Server,
      items: [
        { label: 'API Base URL', value: 'http://localhost:37241' },
        { label: 'API Port', value: '37241' },
      ],
    },
    {
      category: 'Storage',
      icon: Database,
      items: [
        { label: 'Persist Directory', value: '/Volumes/online/llamaindex' },
        { label: 'Zotero Directory', value: '/Volumes/online/llamaindex/zotero' },
      ],
    },
    {
      category: 'Embedding',
      icon: Key,
      items: [
        { label: 'Embedding Model', value: 'bge-m3' },
        { label: 'Embedding Dimension', value: '1024' },
      ],
    },
  ]

  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-bold">Settings</h1>

      <div className="grid gap-6 lg:grid-cols-2">
        {settings.map((section) => (
          <Card key={section.category}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <section.icon className="h-5 w-5" />
                {section.category}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {section.items.map((item) => (
                <div key={item.label} className="flex justify-between">
                  <span className="text-muted-foreground">{item.label}</span>
                  <span className="font-mono text-sm">{item.value}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Environment Variables</CardTitle>
          <CardDescription>
            These settings are configured via environment variables in your .env file
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 text-sm">
            <p><code className="bg-muted px-1">SILICONFLOW_API_KEY</code> - SiliconFlow API Key</p>
            <p><code className="bg-muted px-1">OLLAMA_EMBED_MODEL</code> - Ollama embedding model (default: bge-m3)</p>
            <p><code className="bg-muted px-1">OLLAMA_BASE_URL</code> - Ollama server URL</p>
            <p><code className="bg-muted px-1">USE_HYBRID_SEARCH</code> - Enable hybrid search (true/false)</p>
            <p><code className="bg-muted px-1">USE_AUTO_MERGING</code> - Enable auto-merging retrieval</p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export function Settings() {
  return <SettingsPage />
}