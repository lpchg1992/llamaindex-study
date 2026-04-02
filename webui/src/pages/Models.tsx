import { useModels, useVendors } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Cpu, User } from 'lucide-react'

export function ModelsPage() {
  const { data: llmModels, isLoading: llmLoading } = useModels('llm')
  const { data: embeddingModels, isLoading: embeddingLoading } = useModels('embedding')
  const { data: vendors, isLoading: vendorsLoading } = useVendors()

  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-bold">Models & Vendors</h1>

      <Tabs defaultValue="llm" className="w-full">
        <TabsList>
          <TabsTrigger value="llm">
            <Cpu className="mr-2 h-4 w-4" />
            LLMs
          </TabsTrigger>
          <TabsTrigger value="embedding">
            <Cpu className="mr-2 h-4 w-4" />
            Embeddings
          </TabsTrigger>
          <TabsTrigger value="vendors">
            <User className="mr-2 h-4 w-4" />
            Vendors
          </TabsTrigger>
        </TabsList>

        <TabsContent value="llm" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Language Models</CardTitle>
            </CardHeader>
            <CardContent>
              {llmLoading ? (
                <p className="text-muted-foreground">Loading...</p>
              ) : llmModels && llmModels.length > 0 ? (
                <div className="space-y-3">
                  {llmModels.map((model) => (
                    <div key={model.id} className="flex items-center justify-between p-3 border rounded-lg">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{model.name}</span>
                          {model.is_default && <Badge>Default</Badge>}
                          {!model.is_active && <Badge variant="destructive">Inactive</Badge>}
                        </div>
                        <p className="text-sm text-muted-foreground font-mono">{model.id}</p>
                      </div>
                      <Badge variant="outline">{model.vendor_id}</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground">No LLM models configured</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="embedding" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Embedding Models</CardTitle>
            </CardHeader>
            <CardContent>
              {embeddingLoading ? (
                <p className="text-muted-foreground">Loading...</p>
              ) : embeddingModels && embeddingModels.length > 0 ? (
                <div className="space-y-3">
                  {embeddingModels.map((model) => (
                    <div key={model.id} className="flex items-center justify-between p-3 border rounded-lg">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{model.name}</span>
                          {model.is_default && <Badge>Default</Badge>}
                          {!model.is_active && <Badge variant="destructive">Inactive</Badge>}
                        </div>
                        <p className="text-sm text-muted-foreground font-mono">{model.id}</p>
                      </div>
                      <Badge variant="outline">{model.vendor_id}</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground">No embedding models configured</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="vendors" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Vendors</CardTitle>
            </CardHeader>
            <CardContent>
              {vendorsLoading ? (
                <p className="text-muted-foreground">Loading...</p>
              ) : vendors && vendors.length > 0 ? (
                <div className="space-y-3">
                  {vendors.map((vendor) => (
                    <div key={vendor.id} className="flex items-center justify-between p-3 border rounded-lg">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{vendor.name}</span>
                          {!vendor.is_active && <Badge variant="destructive">Inactive</Badge>}
                        </div>
                        <p className="text-sm text-muted-foreground font-mono">{vendor.id}</p>
                        {vendor.api_base && (
                          <p className="text-xs text-muted-foreground">{vendor.api_base}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground">No vendors configured</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

export function Models() {
  return <ModelsPage />
}