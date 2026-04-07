import { useState } from 'react'
import { useModels, useVendors, useCreateVendor, useDeleteVendor, useCreateModel, useDeleteModel, useSetDefaultModel } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Cpu, User, Plus, Trash2, Loader2, Star } from 'lucide-react'
import { toast } from 'sonner'
import type { VendorCreateRequest, ModelCreateRequest } from '@/types/api'

export function ModelsPage() {
  const { data: llmModels, isLoading: llmLoading } = useModels('llm')
  const { data: embeddingModels, isLoading: embeddingLoading } = useModels('embedding')
  const { data: vendors, isLoading: vendorsLoading } = useVendors()
  const createVendor = useCreateVendor()
  const deleteVendor = useDeleteVendor()
  const createModel = useCreateModel()
  const deleteModel = useDeleteModel()
  const setDefaultModel = useSetDefaultModel()

  const [isVendorDialogOpen, setIsVendorDialogOpen] = useState(false)
  const [isModelDialogOpen, setIsModelDialogOpen] = useState(false)
  const [newVendor, setNewVendor] = useState<VendorCreateRequest>({
    id: '',
    name: '',
    api_base: '',
    api_key: '',
    is_active: true,
  })
  const [newModel, setNewModel] = useState<ModelCreateRequest>({
    id: '',
    vendor_id: '',
    name: '',
    type: 'llm',
    is_active: true,
    is_default: false,
  })

  const handleCreateVendor = async () => {
    if (!newVendor.id || !newVendor.name) return
    try {
      await createVendor.mutateAsync(newVendor)
      setIsVendorDialogOpen(false)
      setNewVendor({ id: '', name: '', api_base: '', api_key: '', is_active: true })
      toast.success('Vendor created')
    } catch (error) {
      toast.error('Failed to create vendor')
    }
  }

  const handleDeleteVendor = async (vendorId: string) => {
    if (!confirm(`Delete vendor "${vendorId}"?`)) return
    try {
      await deleteVendor.mutateAsync(vendorId)
      toast.success('Vendor deleted')
    } catch (error) {
      toast.error('Failed to delete vendor')
    }
  }

  const handleCreateModel = async () => {
    if (!newModel.id || !newModel.vendor_id || !newModel.type) return
    try {
      await createModel.mutateAsync(newModel)
      setIsModelDialogOpen(false)
      setNewModel({ id: '', vendor_id: '', name: '', type: 'llm', is_active: true, is_default: false })
      toast.success('Model created')
    } catch (error) {
      toast.error('Failed to create model')
    }
  }

  const handleDeleteModel = async (modelId: string) => {
    if (!confirm(`Delete model "${modelId}"?`)) return
    try {
      await deleteModel.mutateAsync(modelId)
      toast.success('Model deleted')
    } catch (error) {
      toast.error('Failed to delete model')
    }
  }

  const handleSetDefault = async (modelId: string) => {
    try {
      await setDefaultModel.mutateAsync(modelId)
      toast.success('Default model set')
    } catch (error) {
      toast.error('Failed to set default model')
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Models & Vendors</h1>
        <div className="flex gap-2">
          <Dialog open={isVendorDialogOpen} onOpenChange={setIsVendorDialogOpen}>
            <DialogTrigger asChild>
              <Button variant="outline">
                <Plus className="mr-2 h-4 w-4" />
                Add Vendor
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add Vendor</DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="vendor-id">Vendor ID</Label>
                  <Input
                    id="vendor-id"
                    placeholder="siliconflow"
                    value={newVendor.id}
                    onChange={(e) => setNewVendor({ ...newVendor, id: e.target.value.toLowerCase() })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="vendor-name">Display Name</Label>
                  <Input
                    id="vendor-name"
                    placeholder="SiliconFlow"
                    value={newVendor.name}
                    onChange={(e) => setNewVendor({ ...newVendor, name: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="vendor-base">API Base URL</Label>
                  <Input
                    id="vendor-base"
                    placeholder="https://api.siliconflow.cn/v1"
                    value={newVendor.api_base || ''}
                    onChange={(e) => setNewVendor({ ...newVendor, api_base: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="vendor-key">API Key</Label>
                  <Input
                    id="vendor-key"
                    type="password"
                    placeholder="sk-..."
                    value={newVendor.api_key || ''}
                    onChange={(e) => setNewVendor({ ...newVendor, api_key: e.target.value })}
                  />
                </div>
                <div className="flex items-center space-x-2">
                  <Switch
                    id="vendor-active"
                    checked={newVendor.is_active}
                    onCheckedChange={(checked) => setNewVendor({ ...newVendor, is_active: checked })}
                  />
                  <Label htmlFor="vendor-active">Active</Label>
                </div>
                <Button onClick={handleCreateVendor} disabled={!newVendor.id || !newVendor.name || createVendor.isPending}>
                  {createVendor.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Create Vendor
                </Button>
              </div>
            </DialogContent>
          </Dialog>

          <Dialog open={isModelDialogOpen} onOpenChange={setIsModelDialogOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                Add Model
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add Model</DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="model-id">Model ID</Label>
                  <Input
                    id="model-id"
                    placeholder="siliconflow/DeepSeek-V3.2"
                    value={newModel.id}
                    onChange={(e) => setNewModel({ ...newModel, id: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="model-vendor">Vendor</Label>
                  <Select value={newModel.vendor_id} onValueChange={(v) => setNewModel({ ...newModel, vendor_id: v })}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select vendor..." />
                    </SelectTrigger>
                    <SelectContent>
                      {vendors?.map((v) => (
                        <SelectItem key={v.id} value={v.id}>{v.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="model-name">Display Name</Label>
                  <Input
                    id="model-name"
                    placeholder="DeepSeek V3.2"
                    value={newModel.name || ''}
                    onChange={(e) => setNewModel({ ...newModel, name: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="model-type">Type</Label>
                  <Select value={newModel.type} onValueChange={(v: 'llm' | 'embedding' | 'reranker') => setNewModel({ ...newModel, type: v })}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="llm">LLM</SelectItem>
                      <SelectItem value="embedding">Embedding</SelectItem>
                      <SelectItem value="reranker">Reranker</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-center space-x-2">
                  <Switch
                    id="model-default"
                    checked={newModel.is_default}
                    onCheckedChange={(checked) => setNewModel({ ...newModel, is_default: checked })}
                  />
                  <Label htmlFor="model-default">Set as default</Label>
                </div>
                <Button onClick={handleCreateModel} disabled={!newModel.id || !newModel.vendor_id || createModel.isPending}>
                  {createModel.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Create Model
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>

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
                          {model.is_default && <Badge><Star className="h-3 w-3 mr-1" />Default</Badge>}
                          {!model.is_active && <Badge variant="destructive">Inactive</Badge>}
                        </div>
                        <p className="text-sm text-muted-foreground font-mono">{model.id}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{model.vendor_id}</Badge>
                        {!model.is_default && (
                          <Button variant="ghost" size="sm" onClick={() => handleSetDefault(model.id)}>
                            Set Default
                          </Button>
                        )}
                        <Button variant="ghost" size="icon" onClick={() => handleDeleteModel(model.id)}>
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
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
                          {model.is_default && <Badge><Star className="h-3 w-3 mr-1" />Default</Badge>}
                          {!model.is_active && <Badge variant="destructive">Inactive</Badge>}
                        </div>
                        <p className="text-sm text-muted-foreground font-mono">{model.id}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{model.vendor_id}</Badge>
                        {!model.is_default && (
                          <Button variant="ghost" size="sm" onClick={() => handleSetDefault(model.id)}>
                            Set Default
                          </Button>
                        )}
                        <Button variant="ghost" size="icon" onClick={() => handleDeleteModel(model.id)}>
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
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
                      <Button variant="ghost" size="icon" onClick={() => handleDeleteVendor(vendor.id)}>
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
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