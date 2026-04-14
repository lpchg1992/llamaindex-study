import { useState, useEffect } from 'react'
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
import { Cpu, User, Plus, Trash2, Star, Pencil, Settings2 } from 'lucide-react'
import { toast } from 'sonner'
import type { VendorInfo, ModelInfo, VendorCreateRequest, ModelCreateRequest } from '@/types/api'

type VendorType = 'cloud' | 'local'

function getDefaultModelConfig(type: string): Record<string, unknown> {
  switch (type) {
    case 'llm':
      return { temperature: 0.7, max_tokens: 2048, top_p: 0.9 }
    case 'embedding':
      return { dimensions: 1024, batch_size: 32, pooling: 'mean' }
    case 'reranker':
      return { top_k: 10, normalize: true }
    default:
      return {}
  }
}

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
  const [vendorType, setVendorType] = useState<VendorType>(
    vendor?.api_key ? 'cloud' : 'local'
  )
  
  const [formData, setFormData] = useState<VendorCreateRequest>(
    vendor
      ? { id: vendor.id, name: vendor.name, api_base: vendor.api_base || '', api_key: vendor.api_key || '', is_active: vendor.is_active }
      : { id: '', name: '', api_base: '', api_key: '', is_active: true }
  )

  useEffect(() => {
    if (vendor) {
      setFormData({
        id: vendor.id,
        name: vendor.name,
        api_base: vendor.api_base || '',
        api_key: vendor.api_key || '',
        is_active: vendor.is_active,
      })
      setVendorType(vendor.api_key ? 'cloud' : 'local')
    } else {
      setFormData({ id: '', name: '', api_base: '', api_key: '', is_active: true })
      setVendorType('cloud')
    }
  }, [vendor])

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
            <Label htmlFor="vendor-type">Vendor Type</Label>
            <Select value={vendorType} onValueChange={(v: VendorType) => setVendorType(v)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="cloud">
                  <div className="flex flex-col items-start">
                    <span>Cloud Provider</span>
                    <span className="text-xs text-muted-foreground">Requires API key (e.g., SiliconFlow, OpenAI)</span>
                  </div>
                </SelectItem>
                <SelectItem value="local">
                  <div className="flex flex-col items-start">
                    <span>Local Provider</span>
                    <span className="text-xs text-muted-foreground">No API key needed (e.g., Ollama)</span>
                  </div>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
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
              placeholder={vendorType === 'cloud' ? 'https://api.siliconflow.cn/v1' : 'http://localhost:11434'}
              value={formData.api_base || ''}
              onChange={(e) => setFormData({ ...formData, api_base: e.target.value })}
            />
            {vendorType === 'local' && (
              <p className="text-xs text-muted-foreground">
                Local providers typically use http://localhost:11434
              </p>
            )}
          </div>
          {vendorType === 'cloud' && (
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
          )}
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
  const [showAdvanced, setShowAdvanced] = useState(false)
  
  const [formData, setFormData] = useState<ModelCreateRequest>(
    model
      ? { 
          id: model.id, 
          vendor_id: model.vendor_id, 
          name: model.name, 
          type: model.type, 
          is_active: model.is_active, 
          is_default: model.is_default,
          config: model.config || getDefaultModelConfig(model.type)
        }
      : { id: '', vendor_id: '', name: '', type: 'llm', is_active: true, is_default: false, config: getDefaultModelConfig('llm') }
  )

  const autoGenerateModelId = (vendorId: string, name: string): string => {
    if (!vendorId || !name) return ''
    const safeName = name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
    return `${vendorId}/${safeName}`
  }

  const handleVendorChange = (vendorId: string) => {
    if (mode === 'create') {
      setFormData(prev => ({ ...prev, vendor_id: vendorId, id: autoGenerateModelId(vendorId, prev.name) }))
    } else {
      setFormData(prev => ({ ...prev, vendor_id: vendorId }))
    }
  }

  const handleNameChange = (name: string) => {
    if (mode === 'create') {
      setFormData(prev => ({ ...prev, name, id: autoGenerateModelId(prev.vendor_id, name) }))
    } else {
      setFormData(prev => ({ ...prev, name }))
    }
  }

  useEffect(() => {
    if (model) {
      setFormData({
        id: model.id,
        vendor_id: model.vendor_id,
        name: model.name,
        type: model.type,
        is_active: model.is_active,
        is_default: model.is_default,
        config: model.config || getDefaultModelConfig(model.type),
      })
    } else {
      setFormData({ id: '', vendor_id: '', name: '', type: 'llm', is_active: true, is_default: false, config: getDefaultModelConfig('llm') })
    }
  }, [model])

  const updateConfig = (key: string, value: unknown) => {
    setFormData(prev => ({
      ...prev,
      config: { ...prev.config, [key]: value }
    }))
  }

  const handleSave = () => {
    if (!formData.name || !formData.vendor_id || !formData.type) return
    const finalId = mode === 'create' ? formData.id : (model?.id || formData.id)
    if (!finalId) return
    onSave({ modelId: finalId, data: formData })
    onOpenChange(false)
  }

  const getConfigValue = <T,>(key: string, defaultValue: T): T => {
    const val = formData.config?.[key]
    return (val as T) ?? defaultValue
  }

  const renderModelConfig = () => {
    switch (formData.type) {
      case 'llm':
        return (
          <div className="space-y-3 border-t pt-3">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <Settings2 className="h-4 w-4" />
              LLM Configuration
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="config-temperature" className="text-xs">Temperature</Label>
                <Input
                  id="config-temperature"
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={getConfigValue('temperature', 0.7)}
                  onChange={(e) => updateConfig('temperature', parseFloat(e.target.value))}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="config-max-tokens" className="text-xs">Max Tokens</Label>
                <Input
                  id="config-max-tokens"
                  type="number"
                  min={1}
                  max={128000}
                  value={getConfigValue('max_tokens', 2048)}
                  onChange={(e) => updateConfig('max_tokens', parseInt(e.target.value))}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="config-top-p" className="text-xs">Top P</Label>
                <Input
                  id="config-top-p"
                  type="number"
                  min={0}
                  max={1}
                  step={0.1}
                  value={getConfigValue('top_p', 0.9)}
                  onChange={(e) => updateConfig('top_p', parseFloat(e.target.value))}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="config-freq-penalty" className="text-xs">Frequency Penalty</Label>
                <Input
                  id="config-freq-penalty"
                  type="number"
                  min={-2}
                  max={2}
                  step={0.1}
                  value={getConfigValue('frequency_penalty', 0)}
                  onChange={(e) => updateConfig('frequency_penalty', parseFloat(e.target.value))}
                />
              </div>
            </div>
          </div>
        )
      case 'embedding':
        return (
          <div className="space-y-3 border-t pt-3">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <Settings2 className="h-4 w-4" />
              Embedding Configuration
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="config-dimensions" className="text-xs">Dimensions</Label>
                <Input
                  id="config-dimensions"
                  type="number"
                  min={128}
                  max={4096}
                  value={getConfigValue('dimensions', 1024)}
                  onChange={(e) => updateConfig('dimensions', parseInt(e.target.value))}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="config-batch-size" className="text-xs">Batch Size</Label>
                <Input
                  id="config-batch-size"
                  type="number"
                  min={1}
                  max={256}
                  value={getConfigValue('batch_size', 32)}
                  onChange={(e) => updateConfig('batch_size', parseInt(e.target.value))}
                />
              </div>
              <div className="space-y-1 col-span-2">
                <Label htmlFor="config-pooling" className="text-xs">Pooling Mode</Label>
                <Select 
                  value={getConfigValue('pooling', 'mean')} 
                  onValueChange={(v) => updateConfig('pooling', v)}
                >
                  <SelectTrigger id="config-pooling">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="mean">Mean Pooling</SelectItem>
                    <SelectItem value="cls">CLS Pooling</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        )
      case 'reranker':
        return (
          <div className="space-y-3 border-t pt-3">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <Settings2 className="h-4 w-4" />
              Reranker Configuration
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="config-top-k" className="text-xs">Top K</Label>
                <Input
                  id="config-top-k"
                  type="number"
                  min={1}
                  max={100}
                  value={getConfigValue('top_k', 10)}
                  onChange={(e) => updateConfig('top_k', parseInt(e.target.value))}
                />
              </div>
              <div className="flex items-center space-x-2 pt-5">
                <Switch
                  id="config-normalize"
                  checked={getConfigValue('normalize', true)}
                  onCheckedChange={(checked) => updateConfig('normalize', checked)}
                />
                <Label htmlFor="config-normalize" className="text-xs">Normalize Scores</Label>
              </div>
            </div>
          </div>
        )
      default:
        return null
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{mode === 'create' ? 'Add Model' : 'Edit Model'}</DialogTitle>
          <DialogDescription>
            {mode === 'create' ? 'Add a new LLM, embedding, or reranker model.' : 'Update model information.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4 max-h-[60vh] overflow-y-auto">
          <div className="space-y-2">
            <Label htmlFor="model-id">Model ID</Label>
            <Input
              id="model-id"
              value={formData.id}
              readOnly
              disabled={mode === 'create'}
              placeholder={mode === 'create' ? 'Auto-generated from vendor and name...' : formData.id}
              className={mode === 'create' ? 'bg-muted' : ''}
            />
            {mode === 'create' && formData.id && (
              <p className="text-xs text-muted-foreground">ID: {formData.id}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="model-vendor">Vendor</Label>
            <Select value={formData.vendor_id} onValueChange={handleVendorChange}>
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
              onChange={(e) => handleNameChange(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="model-type">Type</Label>
            <Select value={formData.type} onValueChange={(v: 'llm' | 'embedding' | 'reranker') => {
              setFormData(prev => ({
                ...prev,
                type: v,
                config: getDefaultModelConfig(v)
              }))
            }}>
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
          
          {renderModelConfig()}
          
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <Settings2 className="h-4 w-4" />
            {showAdvanced ? 'Hide' : 'Show'} Advanced Configuration
          </button>
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
