import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useIngestSelective,
  useIngestFiles,
  useAllZoteroCollectionsWithItems,
  useObsidianVaults,
  useObsidianVaultTree,
  useZoteroPreview,
  useObsidianPreview,
  useFilePreview,
} from '@/api/hooks'

import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { FileTree } from '@/components/FileTree'
import type { FileTreeItem } from '@/components/FileTree'
import { SelectedFilesPanel } from '@/components/SelectedFilesPanel'
import { ImportPreviewModal } from '@/components/ImportPreviewModal'
import { FileListPreviewModal } from '@/components/FileListPreviewModal'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Upload, FolderOpen, Book, FileText, RefreshCw, Eye, Loader2, Settings2, ChevronDown, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import type {
  ObsidianVaultTree,
  ZoteroPreviewItem,
  ObsidianPreviewItem,
  FilePreviewItem,
} from '@/types/api'

interface ImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  kbId: string
  kbName: string
}

export function ImportDialog({ open, onOpenChange, kbId, kbName }: ImportDialogProps) {
  const ingestSelective = useIngestSelective()
  const ingestFiles = useIngestFiles()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [activeSource, setActiveSource] = useState<string>('zotero')

  const [zoteroSelectedIds, setZoteroSelectedIds] = useState<Set<string>>(new Set())
  const [zoteroSelectedItems, setZoteroSelectedItems] = useState<FileTreeItem[]>([])
  // 预览确认后的项目（只有确认后才会显示在已选择框）
  const [zoteroConfirmedItems, setZoteroConfirmedItems] = useState<FileTreeItem[]>([])
  // 是否已预览并确认（Zotero特有）
  const [zoteroPreviewConfirmed, setZoteroPreviewConfirmed] = useState(false)
  const [obsidianSelectedIds, setObsidianSelectedIds] = useState<Set<string>>(new Set())
  const [obsidianSelectedItems, setObsidianSelectedItems] = useState<FileTreeItem[]>([])
  const [fileSelectedItems, setFileSelectedItems] = useState<FileTreeItem[]>([])

  const navigate = useNavigate()

  const { data: zoteroCollectionsData, isLoading: zoteroLoading, refetch: refetchZotero } =
    useAllZoteroCollectionsWithItems()
  const { data: obsidianVaults, isLoading: vaultsLoading, refetch: refetchVaults } =
    useObsidianVaults()
  const [selectedVault, setSelectedVault] = useState<string>('')
  const { data: obsidianTree, isLoading: treeLoading } = useObsidianVaultTree(selectedVault)

  const zoteroPreview = useZoteroPreview()
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewData, setPreviewData] = useState<ZoteroPreviewItem[]>([])
  const [previewMeta, setPreviewMeta] = useState({
    totalItems: 0,
    eligibleItems: 0,
    ineligibleItems: 0,
    filteringRules: [] as string[],
  })
  const [zoteroPrefix, setZoteroPrefix] = useState("[kb]")
  const [zoteroIncludeExts, setZoteroIncludeExts] = useState("")
  const [zoteroDetectedScannedIds, setZoteroDetectedScannedIds] = useState<Set<number>>(new Set())
  const [zoteroForceOcrIds, setZoteroForceOcrIds] = useState<Set<number>>(new Set())
  const [zoteroManualScannedIds, setZoteroManualScannedIds] = useState<Set<number>>(new Set())
  const [zoteroMdCacheIds, setZoteroMdCacheIds] = useState<Set<number>>(new Set())

  // 预览缓存
  const [previewCache, setPreviewCache] = useState<{
    data: ZoteroPreviewItem[]
    meta: typeof previewMeta
    itemIds: number[]
  } | null>(null)

  useEffect(() => {
    setPreviewCache(null)
  }, [zoteroIncludeExts])

  const obsidianPreview = useObsidianPreview()
  const [obsidianPreviewOpen, setObsidianPreviewOpen] = useState(false)
  const [obsidianPreviewData, setObsidianPreviewData] = useState<ObsidianPreviewItem[]>([])
  const [obsidianPreviewMeta, setObsidianPreviewMeta] = useState({
    totalItems: 0,
    eligibleItems: 0,
    filteringRules: [] as string[],
    warnings: [] as string[],
  })
  const [obsidianPrefix, setObsidianPrefix] = useState("")

  const filePreview = useFilePreview()
  const [filePreviewOpen, setFilePreviewOpen] = useState(false)
  const [filePreviewData, setFilePreviewData] = useState<FilePreviewItem[]>([])
  const [filePreviewMeta, setFilePreviewMeta] = useState({
    totalItems: 0,
    eligibleItems: 0,
    filteringRules: [] as string[],
    warnings: [] as string[],
  })
  const [fileIncludeExts, setFileIncludeExts] = useState("")

  const [showAdvanced, setShowAdvanced] = useState(false)
  const [chunkStrategy, setChunkStrategy] = useState<string>("hierarchical")
  const [chunkSize, setChunkSize] = useState<number>(1024)
  const [hierarchicalChunkSizes, setHierarchicalChunkSizes] = useState<string>("2048,1024,512")

  const zoteroTreeItems = useMemo<FileTreeItem[]>(() => {
    if (!zoteroCollectionsData?.collections) return []

    const buildTree = (parentId: number | null): FileTreeItem[] => {
      return zoteroCollectionsData.collections
        .filter((c) => c.parent_id === parentId)
        .map((c) => ({
          id: `collection-${c.collection_id}`,
          name: c.collection_name,
          type: 'collection' as const,
          children: [
            ...c.items.map((item) => ({
              id: `item-${item.item_id}`,
              name: item.title,
              type: 'item' as const,
              item_id: item.item_id,
              has_file: item.has_file,
            })),
            ...buildTree(Number(c.collection_id)),
          ],
        }))
    }

    return buildTree(null)
  }, [zoteroCollectionsData])

  const convertObsidianItem = useCallback((item: ObsidianVaultTree['items'][0]): FileTreeItem => {
    return {
      id: item.path || item.name,
      name: item.name,
      type: item.type === 'folder' ? 'folder' : 'file',
      path: item.path,
      md_count: item.md_count,
      size: item.size,
      has_children: item.has_children,
      children: item.children?.map(convertObsidianItem),
    }
  }, [])

  const obsidianTreeItems = useMemo<FileTreeItem[]>(() => {
    if (!obsidianTree?.items) return []
    return obsidianTree.items.map((item) => convertObsidianItem(item))
  }, [obsidianTree, convertObsidianItem])

  const handleZoteroSelectionChange = useCallback(
    (ids: Set<string>, items: FileTreeItem[]) => {
      setZoteroSelectedIds(ids)
      setZoteroSelectedItems(items)
      // 选择改变时清除预览缓存
      setPreviewCache(null)
      setZoteroPreviewConfirmed(false)
    },
    []
  )

  const handlePreviewZotero = async () => {
    // 重置确认状态
    setZoteroPreviewConfirmed(false)
    
    const itemIds = zoteroSelectedItems
      .filter((item) => item.type === 'item')
      .map((item) => item.item_id)
      .filter((id): id is number => id !== undefined)

    if (itemIds.length === 0) {
      toast.error('请先选择要预览的文献')
      return
    }

    // 检查缓存：长度相同且顺序一致才命中缓存
    if (previewCache && 
        previewCache.itemIds.length === itemIds.length &&
        previewCache.itemIds.every((id, idx) => id === itemIds[idx])) {
      setPreviewData(previewCache.data)
      setPreviewMeta(previewCache.meta)
      setPreviewOpen(true)
      return
    }

    try {
      const includeExts = zoteroIncludeExts
        .split(',')
        .map(ext => ext.trim().toLowerCase())
        .filter(ext => ext.length > 0)
      const result = await zoteroPreview.mutateAsync({
        kb_id: kbId,
        item_ids: itemIds,
        prefix: zoteroPrefix,
        include_exts: includeExts.length > 0 ? includeExts : undefined,
      })
      const newMeta = {
        totalItems: result.total_items,
        eligibleItems: result.eligible_items,
        ineligibleItems: result.ineligible_items,
        filteringRules: result.filtering_rules,
      }
      setPreviewData(result.items)
      setPreviewMeta(newMeta)
      // 更新缓存
      setPreviewCache({
        data: result.items,
        meta: newMeta,
        itemIds,
      })
      setPreviewOpen(true)
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '预览失败')
    }
  }

  const handlePreviewConfirm = (selectedPreviewItems: ZoteroPreviewItem[], forceOcrIds: number[], manualScannedIds: number[]) => {
    const selectedItemIds = new Set(selectedPreviewItems.map((item) => item.item_id))

    const confirmedItems = zoteroSelectedItems
      .filter(
        (item) =>
          item.type === 'item' &&
          item.item_id !== undefined &&
          selectedItemIds.has(item.item_id)
      )
    setZoteroConfirmedItems(confirmedItems)
    setZoteroPreviewConfirmed(true)

    setZoteroForceOcrIds(new Set(forceOcrIds))

    setZoteroManualScannedIds(new Set(manualScannedIds))

    const detectedScanned = selectedPreviewItems.filter(item => item.is_scanned_pdf).map(item => item.item_id)
    setZoteroDetectedScannedIds(new Set(detectedScanned))

    const mdCacheIds = selectedPreviewItems.filter(item => item.has_md_cache).map(item => item.item_id)
    setZoteroMdCacheIds(new Set(mdCacheIds))

    if (forceOcrIds.length > 0) {
      toast.success(`已确认 ${selectedPreviewItems.length} 篇文献（${forceOcrIds.length} 篇强制OCR）`)
    } else {
      toast.success(`已确认 ${selectedPreviewItems.length} 篇文献`)
    }
  }

  const handleObsidianSelectionChange = useCallback(
    (ids: Set<string>, items: FileTreeItem[]) => {
      setObsidianSelectedIds(ids)
      setObsidianSelectedItems(items)
    },
    []
  )

  // 刷新预览（强制从后端获取最新数据）
  const handleRefreshPreview = async () => {
    const itemIds = zoteroSelectedItems
      .filter((item) => item.type === 'item')
      .map((item) => item.item_id)
      .filter((id): id is number => id !== undefined)

    if (itemIds.length === 0) {
      toast.error('请先选择要预览的文献')
      return
    }

    try {
      const includeExts = zoteroIncludeExts
        .split(',')
        .map(ext => ext.trim().toLowerCase())
        .filter(ext => ext.length > 0)
      const result = await zoteroPreview.mutateAsync({
        kb_id: kbId,
        item_ids: itemIds,
        prefix: zoteroPrefix,
        include_exts: includeExts.length > 0 ? includeExts : undefined,
      })
      const newMeta = {
        totalItems: result.total_items,
        eligibleItems: result.eligible_items,
        ineligibleItems: result.ineligible_items,
        filteringRules: result.filtering_rules,
      }
      setPreviewData(result.items)
      setPreviewMeta(newMeta)
      setPreviewCache({
        data: result.items,
        meta: newMeta,
        itemIds,
      })
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '刷新预览失败')
    }
  }

  const handlePreviewObsidian = async () => {
    if (!selectedVault) {
      toast.error('请先选择 Vault')
      return
    }

    const vault = obsidianVaults?.vaults.find(v => v.name === selectedVault)
    if (!vault) {
      toast.error('未找到 Vault 信息')
      return
    }

    try {
      const result = await obsidianPreview.mutateAsync({
        vault_path: vault.path,
        prefix: obsidianPrefix || undefined,
      })
      setObsidianPreviewData(result.items)
      setObsidianPreviewMeta({
        totalItems: result.total_items,
        eligibleItems: result.eligible_items,
        filteringRules: result.filtering_rules,
        warnings: result.warnings,
      })
      setObsidianPreviewOpen(true)
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '预览失败')
    }
  }

  const handlePreviewFiles = async () => {
    if (fileSelectedItems.length === 0) {
      toast.error('请先选择文件')
      return
    }

    const paths = fileSelectedItems.map(item => item.path || item.name)

    try {
      const includeExts = fileIncludeExts
        .split(',')
        .map(ext => ext.trim().toLowerCase())
        .filter(ext => ext.length > 0)
      const result = await filePreview.mutateAsync({
        paths,
        include_exts: includeExts.length > 0 ? includeExts : undefined,
      })
      setFilePreviewData(result.items)
      setFilePreviewMeta({
        totalItems: result.total_items,
        eligibleItems: result.eligible_items,
        filteringRules: result.filtering_rules,
        warnings: result.warnings,
      })
      setFilePreviewOpen(true)
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '预览失败')
    }
  }

  const handleFileRemove = (id: string) => {
    setFileSelectedItems((prev) => prev.filter((item) => item.id !== id))
  }

  const handleClearAllFiles = () => {
    setFileSelectedItems([])
  }

  const handleFilePicker = () => {
    fileInputRef.current?.click()
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return

    const newFiles: FileTreeItem[] = Array.from(files).map((file) => ({
      id: file.name,
      name: file.name,
      type: 'file' as const,
      path: (file as any).path || file.name,
      size: file.size,
    }))

    setFileSelectedItems((prev) => [...prev, ...newFiles])
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleImport = async () => {
    let itemsToImport: FileTreeItem[] = []
    let sourceType = ''

    if (activeSource === 'zotero') {
      itemsToImport = allSelectedItems
      sourceType = 'zotero'
    } else if (activeSource === 'obsidian') {
      itemsToImport = obsidianSelectedItems
      sourceType = 'obsidian'
    } else {
      itemsToImport = fileSelectedItems
      sourceType = 'files'
    }

    if (itemsToImport.length === 0) {
      toast.error('请先选择要导入的文件')
      return
    }

    const chunkParams = {
      chunk_strategy: chunkStrategy,
      chunk_size: chunkSize,
      ...(chunkStrategy === 'hierarchical' && {
        hierarchical_chunk_sizes: hierarchicalChunkSizes.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n))
      }),
    }

    try {
      if (activeSource === 'files') {
        const paths = itemsToImport.map((item) => item.path || item.name)
        const result = await ingestFiles.mutateAsync({
          kbId,
          req: {
            paths,
            async_mode: true,
            refresh_topics: true,
            ...chunkParams,
          },
        })

        if (result.task_id) {
          toast.success(`导入任务已提交: ${result.task_id}`)
          onOpenChange(false)
          navigate('/tasks')
        }
      } else {
        const importItems = itemsToImport.map((item) => {
          const base = {
            type: item.type,
            id: item.item_id?.toString(),
            path: item.path,
          }
          if (activeSource === 'zotero' && item.type === 'item' && item.item_id !== undefined) {
            const options: Record<string, boolean> = {}
            // 如果有 MD 缓存，传递给后端
            if (zoteroMdCacheIds.has(item.item_id)) {
              options.has_md_cache = true
            }
            // 强制 OCR：删除旧缓存，重新 OCR 替换
            if (zoteroForceOcrIds.has(item.item_id)) {
              options.force_ocr = true
              options.is_scanned = true
            }
            // 扫描开关打开时（系统检测 或 用户手动开启），标记为扫描件
            // 后端根据 is_scanned + has_md_cache 决定使用 MD 缓存还是运行 OCR
            if (zoteroManualScannedIds.has(item.item_id) || zoteroDetectedScannedIds.has(item.item_id)) {
              options.is_scanned = true
            }
            if (Object.keys(options).length > 0) {
              return { ...base, options }
            }
          }
          return base
        })

        const result = await ingestSelective.mutateAsync({
          kbId,
          req: {
            source_type: sourceType,
            items: importItems,
            async_mode: true,
            refresh_topics: false,
            ...(activeSource === 'zotero' && { prefix: zoteroPrefix }),
            ...chunkParams,
          },
        })

        if (result.task_id) {
          toast.success(`导入任务已提交: ${result.task_id}`)
          onOpenChange(false)
          navigate('/tasks')
        }
      }
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '导入失败')
    }
  }

  // Zotero使用确认后的项目列表，其他来源直接使用选择的项目
  const allSelectedItems =
    activeSource === 'zotero'
      ? zoteroConfirmedItems
      : activeSource === 'obsidian'
        ? obsidianSelectedItems
        : fileSelectedItems

  // Zotero需要先预览并确认才能导入
  const canImportZotero = activeSource !== 'zotero' || zoteroPreviewConfirmed

  const resetState = () => {
    setActiveSource('zotero')
    setZoteroSelectedIds(new Set())
    setZoteroSelectedItems([])
    setZoteroConfirmedItems([])
    setZoteroPreviewConfirmed(false)
    setObsidianSelectedIds(new Set())
    setObsidianSelectedItems([])
    setFileSelectedItems([])
    setPreviewCache(null)
    setZoteroForceOcrIds(new Set())
    setZoteroManualScannedIds(new Set())
    setZoteroDetectedScannedIds(new Set())
    setZoteroMdCacheIds(new Set())
  }

  const handleClose = (open: boolean) => {
    if (!open) {
      resetState()
    }
    onOpenChange(open)
  }

  return (
    <>
      <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-[95vw] w-[98vw] h-[92vh] flex flex-col overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5" />
            导入文档到 &quot;{kbName}&quot;
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 min-h-0 flex flex-col gap-4 overflow-hidden">
          <div className="flex gap-4 flex-1 min-h-0 overflow-hidden">
            <div className="flex flex-col border rounded-lg p-4 w-[500px] shrink-0 min-h-0 overflow-hidden">
              <div className="flex items-center gap-2 mb-4 shrink-0">
                <FolderOpen className="h-5 w-5" />
                <span className="font-medium">选择来源</span>
              </div>
              
              <Tabs value={activeSource} onValueChange={setActiveSource} className="flex flex-col flex-1 min-h-0 overflow-hidden">
                <TabsList className="grid w-full grid-cols-3 shrink-0">
                  <TabsTrigger value="zotero" className="flex items-center gap-1">
                    <Book className="h-4 w-4" />
                    Zotero
                  </TabsTrigger>
                  <TabsTrigger value="obsidian" className="flex items-center gap-1">
                    <Book className="h-4 w-4" />
                    Obsidian
                  </TabsTrigger>
                  <TabsTrigger value="files" className="flex items-center gap-1">
                    <FileText className="h-4 w-4" />
                    文件
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="zotero" className="flex flex-col flex-1 min-h-0 overflow-hidden">
                  <div className="flex items-center gap-3 mb-3">
                    <Button variant="outline" size="sm" onClick={() => refetchZotero()} disabled={zoteroLoading}>
                      <RefreshCw className={`h-4 w-4 ${zoteroLoading ? 'animate-spin' : ''}`} />
                    </Button>
                    <div className="flex items-center gap-2">
                      <Label htmlFor="prefix" className="text-xs text-muted-foreground">前缀</Label>
                      <Input id="prefix" value={zoteroPrefix} onChange={(e) => setZoteroPrefix(e.target.value)} className="h-7 w-20 text-xs" />
                    </div>
                    <div className="flex items-center gap-2">
                      <Label htmlFor="exts" className="text-xs text-muted-foreground">文件类型</Label>
                      <Input 
                        id="exts" 
                        value={zoteroIncludeExts} 
                        onChange={(e) => setZoteroIncludeExts(e.target.value)} 
                        className="h-7 w-24 text-xs" 
                        placeholder="如: pdf,docx"
                      />
                    </div>
                    <Button variant="default" size="sm" onClick={handlePreviewZotero} disabled={zoteroSelectedItems.filter(i => i.type === 'item').length === 0 || zoteroPreview.isPending}>
                      <Eye className={`h-4 w-4 ${zoteroPreview.isPending ? 'animate-spin' : ''} mr-1`} />
                      预览
                    </Button>
                  </div>
                  <div className="text-sm text-muted-foreground mb-3">
                    已选 {zoteroSelectedItems.length} 篇文献
                    {zoteroPreviewConfirmed && `（已确认 ${zoteroConfirmedItems.length} 篇）`}
                    {!zoteroPreviewConfirmed && zoteroSelectedItems.length > 0 && ' → 请预览确认'}
                  </div>
                  <div className="border rounded-lg flex-1 min-h-0 overflow-hidden">
                    <FileTree
                      items={zoteroTreeItems}
                      selectedIds={zoteroSelectedIds}
                      onSelectionChange={handleZoteroSelectionChange}
                      loading={zoteroLoading}
                      searchPlaceholder="搜索收藏夹或文献..."
                    />
                  </div>
                </TabsContent>

                <TabsContent value="obsidian" className="flex flex-col flex-1 min-h-0 overflow-hidden">
                  <div className="flex items-center gap-3 mb-3">
                    <Select value={selectedVault} onValueChange={setSelectedVault}>
                      <SelectTrigger className="flex-1"><SelectValue placeholder="选择 Vault..." /></SelectTrigger>
                      <SelectContent>
                        {vaultsLoading ? (
                          <div className="p-2 text-center"><Loader2 className="h-4 w-4 animate-spin mx-auto" /></div>
                        ) : obsidianVaults?.vaults && obsidianVaults.vaults.length > 0 ? (
                          obsidianVaults.vaults.map((vault) => (
                            <SelectItem key={vault.name} value={vault.name}>{vault.name} ({vault.note_count || 0} notes)</SelectItem>
                          ))
                        ) : (
                          <div className="p-2 text-sm text-muted-foreground">未找到 Vault</div>
                        )}
                      </SelectContent>
                    </Select>
                    <Button variant="outline" size="sm" onClick={() => refetchVaults()} disabled={vaultsLoading}>
                      <RefreshCw className={`h-4 w-4 ${vaultsLoading ? 'animate-spin' : ''}`} />
                    </Button>
                    <div className="flex items-center gap-2">
                      <Label htmlFor="obsidian-prefix" className="text-xs text-muted-foreground">前缀</Label>
                      <Input 
                        id="obsidian-prefix" 
                        value={obsidianPrefix} 
                        onChange={(e) => setObsidianPrefix(e.target.value)} 
                        className="h-7 w-20 text-xs" 
                        placeholder="可选"
                      />
                    </div>
                    <Button 
                      variant="default" 
                      size="sm" 
                      onClick={handlePreviewObsidian} 
                      disabled={!selectedVault || obsidianPreview.isPending}
                    >
                      <Eye className={`h-4 w-4 ${obsidianPreview.isPending ? 'animate-spin' : ''} mr-1`} />
                      预览
                    </Button>
                  </div>
                  <div className="text-sm text-muted-foreground mb-3">
                    {obsidianSelectedItems.length} 个文件已选择
                  </div>
                  <div className="border rounded-lg flex-1 min-h-0 overflow-hidden">
                    {selectedVault ? (
                      <FileTree
                        items={obsidianTreeItems}
                        selectedIds={obsidianSelectedIds}
                        onSelectionChange={handleObsidianSelectionChange}
                        loading={treeLoading}
                        searchPlaceholder="搜索文件夹或笔记..."
                      />
                    ) : (
                      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">请先选择 Vault</div>
                    )}
                  </div>
                </TabsContent>

                <TabsContent value="files" className="flex flex-col flex-1 min-h-0 overflow-hidden">
                  <div className="flex flex-col items-center justify-center flex-1 gap-4">
                    <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileChange} />
                    <Button onClick={handleFilePicker} variant="outline" className="w-full max-w-xs">
                      <Upload className="h-4 w-4 mr-2" />选择文件
                    </Button>
                    <div className="flex items-center gap-2">
                      <Label htmlFor="file-exts" className="text-xs text-muted-foreground">文件类型</Label>
                      <Input 
                        id="file-exts" 
                        value={fileIncludeExts} 
                        onChange={(e) => setFileIncludeExts(e.target.value)} 
                        className="h-7 w-32 text-xs" 
                        placeholder="如: pdf,docx"
                      />
                    </div>
                    <Button 
                      variant="default" 
                      size="sm" 
                      onClick={handlePreviewFiles} 
                      disabled={fileSelectedItems.length === 0 || filePreview.isPending}
                    >
                      <Eye className={`h-4 w-4 ${filePreview.isPending ? 'animate-spin' : ''} mr-1`} />
                      预览
                    </Button>
                    <p className="text-xs text-muted-foreground text-center">支持 PDF, DOCX, XLSX, PPTX, MD, TXT 等格式</p>
                  </div>
                </TabsContent>
              </Tabs>

              <div className="mt-4 pt-4 border-t">
                <button
                  type="button"
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  {showAdvanced ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  <Settings2 className="h-4 w-4" />
                  高级选项
                </button>
                {showAdvanced && (
                  <div className="mt-3 space-y-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <Label htmlFor="chunk-strategy" className="text-xs">分块策略</Label>
                        <Select value={chunkStrategy} onValueChange={setChunkStrategy}>
                          <SelectTrigger id="chunk-strategy" className="h-8 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="hierarchical">层级 (Hierarchical)</SelectItem>
                            <SelectItem value="sentence">句子 (Sentence)</SelectItem>
                            <SelectItem value="semantic">语义 (Semantic)</SelectItem>
                            <SelectItem value="markdown">Markdown</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="chunk-size" className="text-xs">分块大小</Label>
                        <Input
                          id="chunk-size"
                          type="number"
                          value={chunkSize}
                          onChange={(e) => setChunkSize(parseInt(e.target.value) || 1024)}
                          className="h-8 text-xs"
                        />
                      </div>
                    </div>
                    {chunkStrategy === 'hierarchical' && (
                      <div className="space-y-1">
                        <Label htmlFor="hierarchical-sizes" className="text-xs">层级大小 (逗号分隔)</Label>
                        <Input
                          id="hierarchical-sizes"
                          value={hierarchicalChunkSizes}
                          onChange={(e) => setHierarchicalChunkSizes(e.target.value)}
                          placeholder="2048,1024,512"
                          className="h-8 text-xs"
                        />
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className="flex flex-col gap-4 flex-1 min-h-0 overflow-hidden">
              <SelectedFilesPanel
                selectedItems={allSelectedItems}
                onRemove={
                  activeSource === 'files'
                    ? handleFileRemove
                    : activeSource === 'zotero'
                      ? (id) => {
                          setZoteroSelectedItems((prev) => prev.filter((i) => i.id !== id))
                          setZoteroSelectedIds((prev) => { const next = new Set(prev); next.delete(id); return next })
                        }
                      : (id) => {
                          setObsidianSelectedItems((prev) => prev.filter((i) => i.id !== id))
                          setObsidianSelectedIds((prev) => { const next = new Set(prev); next.delete(id); return next })
                        }
                }
                onClearAll={
                  activeSource === 'files'
                    ? handleClearAllFiles
                    : activeSource === 'zotero'
                      ? () => { setZoteroSelectedItems([]); setZoteroSelectedIds(new Set()) }
                      : () => { setObsidianSelectedItems([]); setObsidianSelectedIds(new Set()) }
                }
              />
            </div>
          </div>

          <div className="flex items-center justify-end shrink-0 border-t pt-4">
            <Button
              onClick={handleImport}
              disabled={allSelectedItems.length === 0 || !canImportZotero}
              size="lg"
              title={!canImportZotero ? '请先预览并确认要导入的文献' : ''}
            >
              开始导入 ({allSelectedItems.length})
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>

    <ImportPreviewModal
      open={previewOpen}
      onOpenChange={setPreviewOpen}
      previewData={previewData}
      filteringRules={previewMeta.filteringRules}
      totalItems={previewMeta.totalItems}
      eligibleItems={previewMeta.eligibleItems}
      ineligibleItems={previewMeta.ineligibleItems}
      onConfirm={handlePreviewConfirm}
      onRefresh={handleRefreshPreview}
      isLoading={zoteroPreview.isPending}
    />

    <FileListPreviewModal
      open={obsidianPreviewOpen}
      onOpenChange={setObsidianPreviewOpen}
      title="Obsidian 预览"
      items={obsidianPreviewData}
      filteringRules={obsidianPreviewMeta.filteringRules}
      totalItems={obsidianPreviewMeta.totalItems}
      warnings={obsidianPreviewMeta.warnings}
      onRefresh={handlePreviewObsidian}
      isLoading={obsidianPreview.isPending}
      emptyMessage="没有找到 .md 文件"
    />

    <FileListPreviewModal
      open={filePreviewOpen}
      onOpenChange={setFilePreviewOpen}
      title="文件预览"
      items={filePreviewData}
      filteringRules={filePreviewMeta.filteringRules}
      totalItems={filePreviewMeta.totalItems}
      warnings={filePreviewMeta.warnings}
      onRefresh={handlePreviewFiles}
      isLoading={filePreview.isPending}
      emptyMessage="没有文件"
    />
    </>
  )
}