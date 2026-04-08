import { useState } from 'react'
import { useModels, useVendors, useCreateVendor, useDeleteVendor, useUpdateVendor, useCreateModel, useDeleteModel, useUpdateModel, useSetDefaultModel } from '@/api/hooks'
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
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Cpu, User, Plus, Trash2, Star, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import type { VendorInfo, ModelInfo, VendorCreateRequest, ModelCreateRequest } from '@/types/api'

function VendorDialog({
  open,
  onOpenChange,
  vendor,
  onSave,
  mode,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  vendor?: VendorInfo
  onSave: (data: VendorCreateRequest) => void
  mode: 'create' | 'edit'
}) {
  const [formData, setFormData] = useState<VendorCreateRequest>(
    vendor
      ? { id: vendor.id, name: vendor.name, api_base: vendor.api_base || '', api_key: vendor.api_key || '', is_active: vendor.is_active }
      : { id: '', name: '', api_base: '', api_key: '', is_active: true }
  )

  const handleSave = () => {
    if (!formData.id || !formData.name) return
    onSave(formData)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{mode === 'create' ? 'Add Vendor' : 'Edit Vendor'}</DialogTitle>
          <DialogDescription>
            {mode === 'create' ? 'Create a new vendor for LLM/embedding providers.' : 'Update vendor information.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="vendor-id">Vendor ID</Label>
            <Input
              id="vendor-id"
              placeholder="siliconflow"
              value={formData.id}
              onChange={(e) => setFormData({ ...formData, id: e.target.value.toLowerCase() })}
              disabled={mode === 'edit'}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="vendor-name">Display Name</Label>
            <Input
              id="vendor-name"
              placeholder="SiliconFlow"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="vendor-base">API Base URL</Label>
            <Input
              id="vendor-base"
              placeholder="https://api.siliconflow.cn/v1"
              value={formData.api_base || ''}
              onChange={(e) => setFormData({ ...formData, api_base: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="vendor-key">API Key</Label>
            <Input
              id="vendor-key"
              type="password"
              placeholder="sk-..."
              value={formData.api_key || ''}
              onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
            />
          </div>
          <div className="flex items-center space-x-2">
            <Switch
              id="vendor-active"
              checked={formData.is_active}
              onCheckedChange={(checked) => setFormData({ ...formData, is_active: checked })}
            />
            <Label htmlFor="vendor-active">Active</Label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={!formData.id || !formData.name}>
            {mode === 'create' ? 'Create' : 'Save Changes'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ModelDialog({
  open,
  onOpenChange,
  model,
  vendors,
  onSave,
  mode,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  model?: ModelInfo
  vendors?: VendorInfo[]
  onSave: (data: { modelId: string; data: ModelCreateRequest }) => void
  mode: 'create' | 'edit'
}) {
  const [formData, setFormData] = useState<ModelCreateRequest>(
    model
      ? { id: model.id, vendor_id: model.vendor_id, name: model.name, type: model.type, is_active: model.is_active, is_default: model.is_default }
      : { id: '', vendor_id: '', name: '', type: 'llm', is_active: true, is_default: false }
  )

  const handleSave = () => {
    if (!formData.id || !formData.vendor_id || !formData.type) return
    onSave({ modelId: model?.id || formData.id, data: formData })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{mode === 'create' ? 'Add Model' : 'Edit Model'}</DialogTitle>
          <DialogDescription>
            {mode === 'create' ? 'Add a new LLM, embedding, or reranker model.' : 'Update model information.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="model-id">Model ID</Label>
            <Input
              id="model-id"
              placeholder="siliconflow/DeepSeek-V3.2"
              value={formData.id}
              onChange={(e) => setFormData({ ...formData, id: e.target.value })}
              disabled={mode === 'edit'}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="model-vendor">Vendor</Label>
            <Select value={formData.vendor_id} onValueChange={(v) => setFormData({ ...formData, vendor_id: v })}>
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
              value={formData.name || ''}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="model-type">Type</Label>
            <Select value={formData.type} onValueChange={(v: 'llm' | 'embedding' | 'reranker') => setFormData({ ...formData, type: v })}>
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
              checked={formData.is_default}
              onCheckedChange={(checked) => setFormData({ ...formData, is_default: checked })}
            />
            <Label htmlFor="model-default">Set as default</Label>
          </div>
          <div className="flex items-center space-x-2">
            <Switch
              id="model-active"
              checked={formData.is_active}
              onCheckedChange={(checked) => setFormData({ ...formData, is_active: checked })}
            />
            <Label htmlFor="model-active">Active</Label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={!formData.id || !formData.vendor_id}>
            {mode === 'create' ? 'Create' : 'Save Changes'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function ModelsPage() {
  const { data: llmModels, isLoading: llmLoading } = useModels('llm')
  const { data: embeddingModels, isLoading: embeddingLoading } = useModels('embedding')
  const { data: rerankerModels, isLoading: rerankerLoading } = useModels('reranker')
  const { data: vendors, isLoading: vendorsLoading } = useVendors()
  const createVendor = useCreateVendor()
  const deleteVendor = useDeleteVendor()
  const updateVendor = useUpdateVendor()
  const createModel = useCreateModel()
  const deleteModel = useDeleteModel()
  const updateModel = useUpdateModel()
  const setDefaultModel = useSetDefaultModel()

  const [vendorDialog, setVendorDialog] = useState<{ open: boolean; mode: 'create' | 'edit'; vendor?: VendorInfo }>({ open: false, mode: 'create' })
  const [modelDialog, setModelDialog] = useState<{ open: boolean; mode: 'create' | 'edit'; model?: ModelInfo }>({ open: false, mode: 'create' })

  const handleCreateVendor = async (data: VendorCreateRequest) => {
    try {
      await createVendor.mutateAsync(data)
      toast.success('Vendor created')
    } catch (error) {
      toast.error('Failed to create vendor')
    }
  }

  const handleUpdateVendor = async (data: VendorCreateRequest) => {
    try {
      await updateVendor.mutateAsync(data)
      toast.success('Vendor updated')
    } catch (error) {
      toast.error('Failed to update vendor')
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

  const handleCreateModel = async ({ data }: { modelId: string; data: ModelCreateRequest }) => {
    try {
      await createModel.mutateAsync(data)
      toast.success('Model created')
    } catch (error) {
      toast.error('Failed to create model')
    }
  }

  const handleUpdateModel = async ({ modelId, data }: { modelId: string; data: ModelCreateRequest }) => {
    try {
      await updateModel.mutateAsync({ modelId, data })
      toast.success('Model updated')
    } catch (error) {
      toast.error('Failed to update model')
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

  const openEditVendor = (vendor: VendorInfo) => {
    setVendorDialog({ open: true, mode: 'edit', vendor })
  }

  const openEditModel = (model: ModelInfo) => {
    setModelDialog({ open: true, mode: 'edit', model })
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Models & Vendors</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setVendorDialog({ open: true, mode: 'create' })}>
            <Plus className="mr-2 h-4 w-4" />
            Add Vendor
          </Button>
          <Button onClick={() => setModelDialog({ open: true, mode: 'create' })}>
            <Plus className="mr-2 h-4 w-4" />
            Add Model
          </Button>
        </div>
      </div>

      <VendorDialog
        open={vendorDialog.open}
        onOpenChange={(open) => setVendorDialog({ ...vendorDialog, open })}
        vendor={vendorDialog.vendor}
        onSave={vendorDialog.mode === 'create' ? handleCreateVendor : handleUpdateVendor}
        mode={vendorDialog.mode}
      />

      <ModelDialog
        open={modelDialog.open}
        onOpenChange={(open) => setModelDialog({ ...modelDialog, open })}
        model={modelDialog.model}
        vendors={vendors}
        onSave={modelDialog.mode === 'create' ? handleCreateModel : handleUpdateModel}
        mode={modelDialog.mode}
      />

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
          <TabsTrigger value="reranker">
            <Cpu className="mr-2 h-4 w-4" />
            Rerankers
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
                        <Button variant="ghost" size="icon" onClick={() => openEditModel(model)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
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
                        <Button variant="ghost" size="icon" onClick={() => openEditModel(model)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
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

        <TabsContent value="reranker" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Reranker Models</CardTitle>
            </CardHeader>
            <CardContent>
              {rerankerLoading ? (
                <p className="text-muted-foreground">Loading...</p>
              ) : rerankerModels && rerankerModels.length > 0 ? (
                <div className="space-y-3">
                  {rerankerModels.map((model) => (
                    <div key={model.id} className="flex items-center justify-between p-3 border rounded-lg">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{model.name}</span>
                          {!model.is_active && <Badge variant="destructive">Inactive</Badge>}
                        </div>
                        <p className="text-sm text-muted-foreground font-mono">{model.id}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{model.vendor_id}</Badge>
                        <Button variant="ghost" size="icon" onClick={() => openEditModel(model)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => handleDeleteModel(model.id)}>
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground">No reranker models configured</p>
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
                      <div className="flex items-center gap-2">
                        <Button variant="ghost" size="icon" onClick={() => openEditVendor(vendor)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => handleDeleteVendor(vendor.id)}>
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
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
