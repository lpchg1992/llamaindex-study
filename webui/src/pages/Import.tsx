import { useState, useCallback, useMemo, useRef } from 'react'
import {
  useKBs,
  useIngestSelective,
  useIngestFiles,
  useAllZoteroCollectionsWithItems,
  useObsidianVaults,
  useObsidianVaultTree,
} from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
import { ImportProgressPanel } from '@/components/ImportProgressPanel'
import type { DocumentProgress } from '@/components/ImportProgressPanel'
import { Upload, FolderOpen, Book, FileText, Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import type { ObsidianVaultTree } from '@/types/api'

export function Import() {
  const { data: kbs } = useKBs()
  const ingestSelective = useIngestSelective()
  const ingestFiles = useIngestFiles()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [selectedKB, setSelectedKB] = useState<string>('')
  const [activeSource, setActiveSource] = useState<string>('zotero')
  const [asyncMode, setAsyncMode] = useState(true)
  const [isImporting, setIsImporting] = useState(false)

  const [zoteroSelectedIds, setZoteroSelectedIds] = useState<Set<string>>(new Set())
  const [zoteroSelectedItems, setZoteroSelectedItems] = useState<FileTreeItem[]>([])
  const [obsidianSelectedIds, setObsidianSelectedIds] = useState<Set<string>>(new Set())
  const [obsidianSelectedItems, setObsidianSelectedItems] = useState<FileTreeItem[]>([])
  const [fileSelectedItems, setFileSelectedItems] = useState<FileTreeItem[]>([])

  const [importProgress, setImportProgress] = useState<DocumentProgress[]>([])
  const [importCompleted, setImportCompleted] = useState(0)

  const { data: zoteroCollectionsData, isLoading: zoteroLoading, refetch: refetchZotero } =
    useAllZoteroCollectionsWithItems()
  const { data: obsidianVaults, isLoading: vaultsLoading, refetch: refetchVaults } =
    useObsidianVaults()
  const [selectedVault, setSelectedVault] = useState<string>('')
  const { data: obsidianTree, isLoading: treeLoading } = useObsidianVaultTree(selectedVault)

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

  const convertObsidianItem = (item: ObsidianVaultTree['items'][0]): FileTreeItem => {
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
  }

  const obsidianTreeItems = useMemo<FileTreeItem[]>(() => {
    if (!obsidianTree?.items) return []
    return obsidianTree.items.map((item) => convertObsidianItem(item))
  }, [obsidianTree, convertObsidianItem])

  const handleZoteroSelectionChange = useCallback(
    (ids: Set<string>, items: FileTreeItem[]) => {
      setZoteroSelectedIds(ids)
      setZoteroSelectedItems(items)
    },
    []
  )

  const handleObsidianSelectionChange = useCallback(
    (ids: Set<string>, items: FileTreeItem[]) => {
      setObsidianSelectedIds(ids)
      setObsidianSelectedItems(items)
    },
    []
  )

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
    if (!selectedKB) {
      toast.error('请先选择目标知识库')
      return
    }

    let itemsToImport: FileTreeItem[] = []
    let sourceType = ''

    if (activeSource === 'zotero') {
      itemsToImport = zoteroSelectedItems
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

    setIsImporting(true)

    const progressItems: DocumentProgress[] = itemsToImport.map((item) => ({
      id: item.id,
      name: item.name,
      status: 'pending' as const,
      chunksTotal: 0,
      chunksProcessed: 0,
    }))
    setImportProgress(progressItems)

    try {
      if (activeSource === 'files') {
        const paths = itemsToImport.map((item) => item.path || item.name)
        const result = await ingestFiles.mutateAsync({
          kbId: selectedKB,
          req: {
            paths,
            async_mode: asyncMode,
            refresh_topics: true,
          },
        })

        if (result.task_id) {
          toast.success(`导入任务已提交: ${result.task_id}`)
          setImportCompleted(itemsToImport.length)
          setImportProgress((prev) =>
            prev.map((p) => ({ ...p, status: 'success' as const }))
          )
        }
      } else {
        const importItems = itemsToImport.map((item) => ({
          type: item.type,
          id: item.item_id?.toString(),
          path: item.path,
        }))

        const result = await ingestSelective.mutateAsync({
          kbId: selectedKB,
          req: {
            source_type: sourceType,
            items: importItems,
            async_mode: asyncMode,
            refresh_topics: true,
          },
        })

        if (result.task_id) {
          toast.success(`导入任务已提交: ${result.task_id}`)
          setImportCompleted(itemsToImport.length)
          setImportProgress((prev) =>
            prev.map((p) => ({ ...p, status: 'success' as const }))
          )
        }
      }
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '导入失败')
      setImportProgress((prev) =>
        prev.map((p) => ({
          ...p,
          status: 'failed' as const,
          error: '导入失败',
        }))
      )
    } finally {
      setIsImporting(false)
    }
  }

  const allSelectedItems =
    activeSource === 'zotero'
      ? zoteroSelectedItems
      : activeSource === 'obsidian'
        ? obsidianSelectedItems
        : fileSelectedItems

  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-bold">导入文档</h1>

      <div className="mb-6">
        <Label>目标知识库</Label>
        <Select value={selectedKB} onValueChange={setSelectedKB}>
          <SelectTrigger className="w-64">
            <SelectValue placeholder="选择知识库..." />
          </SelectTrigger>
          <SelectContent>
            {kbs?.map((kb) => (
              <SelectItem key={kb.id} value={kb.id}>
                {kb.name || kb.id}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <FolderOpen className="h-5 w-5" />
              选择来源
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs value={activeSource} onValueChange={setActiveSource}>
              <TabsList className="grid w-full grid-cols-3">
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

              <TabsContent value="zotero" className="mt-4">
                <div className="flex gap-2 mb-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => refetchZotero()}
                    disabled={zoteroLoading}
                  >
                    <RefreshCw className="h-4 w-4" />
                  </Button>
                  <span className="text-sm text-muted-foreground">
                    {zoteroSelectedItems.length} 个文献已选择
                  </span>
                </div>
                <div className="border rounded-lg h-80">
                  <FileTree
                    items={zoteroTreeItems}
                    selectedIds={zoteroSelectedIds}
                    onSelectionChange={handleZoteroSelectionChange}
                    loading={zoteroLoading}
                    searchPlaceholder="搜索收藏夹或文献..."
                  />
                </div>
              </TabsContent>

              <TabsContent value="obsidian" className="mt-4">
                <div className="space-y-2 mb-2">
                  <Select value={selectedVault} onValueChange={setSelectedVault}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择 Vault..." />
                    </SelectTrigger>
                    <SelectContent>
                      {vaultsLoading ? (
                        <div className="p-2 text-center">
                          <Loader2 className="h-4 w-4 animate-spin mx-auto" />
                        </div>
                      ) : obsidianVaults?.vaults && obsidianVaults.vaults.length > 0 ? (
                        obsidianVaults.vaults.map((vault) => (
                          <SelectItem key={vault.name} value={vault.name}>
                            {vault.name} ({vault.note_count || 0} notes)
                          </SelectItem>
                        ))
                      ) : (
                        <div className="p-2 text-sm text-muted-foreground">
                          未找到 Vault
                        </div>
                      )}
                    </SelectContent>
                  </Select>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">
                      {obsidianSelectedItems.length} 个文件已选择
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => refetchVaults()}
                      disabled={vaultsLoading}
                    >
                      <RefreshCw className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                <div className="border rounded-lg h-80">
                  {selectedVault ? (
                    <FileTree
                      items={obsidianTreeItems}
                      selectedIds={obsidianSelectedIds}
                      onSelectionChange={handleObsidianSelectionChange}
                      loading={treeLoading}
                      searchPlaceholder="搜索文件夹或笔记..."
                    />
                  ) : (
                    <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                      请先选择 Vault
                    </div>
                  )}
                </div>
              </TabsContent>

              <TabsContent value="files" className="mt-4">
                <div className="space-y-2">
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={handleFileChange}
                  />
                  <Button onClick={handleFilePicker} variant="outline" className="w-full">
                    <Upload className="h-4 w-4 mr-2" />
                    选择文件
                  </Button>
                  <p className="text-xs text-muted-foreground">
                    支持 PDF, DOCX, XLSX, PPTX, MD, TXT 等格式
                  </p>
                </div>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <SelectedFilesPanel
            selectedItems={allSelectedItems}
            onRemove={
              activeSource === 'files'
                ? handleFileRemove
                : activeSource === 'zotero'
                  ? (id) => {
                      setZoteroSelectedItems((prev) => prev.filter((i) => i.id !== id))
                      setZoteroSelectedIds((prev) => {
                        const next = new Set(prev)
                        next.delete(id)
                        return next
                      })
                    }
                  : (id) => {
                      setObsidianSelectedItems((prev) => prev.filter((i) => i.id !== id))
                      setObsidianSelectedIds((prev) => {
                        const next = new Set(prev)
                        next.delete(id)
                        return next
                      })
                    }
            }
            onClearAll={
              activeSource === 'files' ? handleClearAllFiles : activeSource === 'zotero' ? () => { setZoteroSelectedItems([]); setZoteroSelectedIds(new Set()) } : () => { setObsidianSelectedItems([]); setObsidianSelectedIds(new Set()) }
            }
          />

          <ImportProgressPanel
            documents={importProgress}
            documentsTotal={allSelectedItems.length}
            documentsCompleted={importCompleted}
          />
        </div>
      </div>

      <div className="flex items-center gap-4">
        <Button
          onClick={handleImport}
          disabled={!selectedKB || allSelectedItems.length === 0 || isImporting}
          size="lg"
        >
          {isImporting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {isImporting ? '导入中...' : '开始导入'}
        </Button>

        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">导入模式：</span>
          <Button
            variant={asyncMode ? 'default' : 'outline'}
            size="sm"
            onClick={() => setAsyncMode(true)}
            title="立即返回，任务在后台执行，可在任务列表查看进度"
          >
            异步
          </Button>
          <Button
            variant={!asyncMode ? 'default' : 'outline'}
            size="sm"
            onClick={() => setAsyncMode(false)}
            title="等待所有文档处理完成后再返回"
          >
            同步
          </Button>
        </div>
      </div>
    </div>
  )
}
