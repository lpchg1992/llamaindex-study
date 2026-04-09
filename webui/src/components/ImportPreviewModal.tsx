import { useState, useMemo } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table'
import type { ZoteroPreviewItem } from '@/types/api'
import { FileText, Loader2, AlertCircle, CheckCircle2, Image, File, Copy, RefreshCw } from 'lucide-react'

interface ImportPreviewModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  previewData: ZoteroPreviewItem[]
  filteringRules: string[]
  totalItems: number
  eligibleItems: number
  ineligibleItems: number
  onConfirm: (selectedItems: ZoteroPreviewItem[], forceOcrIds: number[]) => void
  isLoading?: boolean
}

function StatusBadges({ item }: { item: ZoteroPreviewItem }) {
  if (item.is_duplicate) {
    return (
      <Badge variant="outline" className="text-xs bg-amber-50">
        <Copy className="h-3 w-3 mr-1" />
        已导入
      </Badge>
    )
  }

  if (!item.is_eligible) {
    return (
      <Badge variant="destructive" className="text-xs">
        <AlertCircle className="h-3 w-3 mr-1" />
        跳过
      </Badge>
    )
  }

  return (
    <div className="flex flex-wrap gap-1">
      <Badge variant="default" className="text-xs bg-green-600">
        <CheckCircle2 className="h-3 w-3 mr-1" />
        符合
      </Badge>
      {item.is_scanned_pdf && (
        <Badge variant="secondary" className="text-xs">
          <Image className="h-3 w-3 mr-1" />
          扫描
        </Badge>
      )}
      {item.has_md_cache && (
        <Badge variant="secondary" className="text-xs">
          <File className="h-3 w-3 mr-1" />
          MD缓存
        </Badge>
      )}
    </div>
  )
}

export function ImportPreviewModal({
  open,
  onOpenChange,
  previewData,
  filteringRules,
  totalItems,
  eligibleItems,
  ineligibleItems,
  onConfirm,
  isLoading,
}: ImportPreviewModalProps) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => {
    return new Set(previewData.filter((item) => item.is_eligible && !item.is_duplicate).map((item) => item.item_id))
  })
  const [forceOcrIds, setForceOcrIds] = useState<Set<number>>(new Set())

  useMemo(() => {
    setSelectedIds(new Set(previewData.filter((item) => item.is_eligible && !item.is_duplicate).map((item) => item.item_id)))
  }, [previewData])

  const toggleItem = (itemId: number, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (checked) {
        next.add(itemId)
      } else {
        next.delete(itemId)
      }
      return next
    })
  }

  const toggleForceOcr = (itemId: number, checked: boolean) => {
    setForceOcrIds((prev) => {
      const next = new Set(prev)
      if (checked) {
        next.add(itemId)
      } else {
        next.delete(itemId)
      }
      return next
    })
  }

  const toggleAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds(new Set(previewData.filter((item) => item.is_eligible && !item.is_duplicate).map((item) => item.item_id)))
    } else {
      setSelectedIds(new Set())
    }
  }

  const selectedItems = useMemo(() => {
    return previewData.filter((item) => selectedIds.has(item.item_id))
  }, [previewData, selectedIds])

  const allEligibleSelected = useMemo(() => {
    const eligibleIds = new Set(previewData.filter((item) => item.is_eligible && !item.is_duplicate).map((item) => item.item_id))
    return eligibleIds.size > 0 && [...eligibleIds].every((id) => selectedIds.has(id))
  }, [previewData, selectedIds])

  const handleConfirm = () => {
    onConfirm(selectedItems, Array.from(forceOcrIds))
    onOpenChange(false)
  }

  const scannedCount = previewData.filter((item) => item.is_scanned_pdf && item.is_eligible).length
  const duplicateCount = previewData.filter((item) => item.is_duplicate).length
  const mdCacheCount = previewData.filter((item) => item.has_md_cache && item.is_eligible).length

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[95vw] w-[95vw] h-[85vh] flex flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            导入预览
          </DialogTitle>
          <DialogDescription>
            应用筛选规则后，共 {totalItems} 篇文献，其中 {eligibleItems} 篇符合条件，{ineligibleItems} 篇将跳过，{duplicateCount} 篇已导入
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 min-h-0 flex flex-col gap-4 overflow-hidden px-1">
          <div className="flex flex-wrap gap-2 text-sm">
            {filteringRules.map((rule, i) => (
              <Badge key={i} variant="outline" className="text-xs">
                {rule}
              </Badge>
            ))}
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div className="flex items-center gap-3 p-3 border rounded-lg bg-green-50/50">
              <CheckCircle2 className="h-5 w-5 text-green-600 shrink-0" />
              <div className="text-sm">
                <div className="text-xs text-muted-foreground">符合条件</div>
                <div><strong>{eligibleItems}</strong> 篇</div>
              </div>
            </div>
            <div className="flex items-center gap-3 p-3 border rounded-lg bg-amber-50/50">
              <AlertCircle className="h-5 w-5 text-amber-600 shrink-0" />
              <div className="text-sm">
                <div className="text-xs text-muted-foreground">将跳过</div>
                <div><strong>{ineligibleItems}</strong> 篇</div>
              </div>
            </div>
            <div className="flex items-center gap-3 p-3 border rounded-lg bg-blue-50/50">
              <Copy className="h-5 w-5 text-blue-600 shrink-0" />
              <div className="text-sm">
                <div className="text-xs text-muted-foreground">已导入</div>
                <div><strong>{duplicateCount}</strong> 篇</div>
              </div>
            </div>
            <div className="flex items-center gap-3 p-3 border rounded-lg bg-purple-50/50">
              <Image className="h-5 w-5 text-purple-600 shrink-0" />
              <div className="text-sm">
                <div className="text-xs text-muted-foreground">扫描件 / MD缓存</div>
                <div><strong>{scannedCount}</strong> / <strong>{mdCacheCount}</strong></div>
              </div>
            </div>
          </div>

          <div className="flex-1 min-h-0 border rounded-lg overflow-hidden flex flex-col">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <Checkbox
                      checked={allEligibleSelected}
                      onCheckedChange={toggleAll}
                      aria-label="全选"
                    />
                  </TableHead>
                  <TableHead className="w-16">ID</TableHead>
                  <TableHead>文档名称</TableHead>
                  <TableHead className="w-20">类型</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="w-24">
                    <div className="flex items-center gap-1">
                      <RefreshCw className="h-3 w-3" />
                      强制OCR
                    </div>
                  </TableHead>
                  <TableHead>原因</TableHead>
                </TableRow>
              </TableHeader>
            </Table>
            <ScrollArea className="flex-1">
              <Table>
                <TableBody>
                  {previewData.map((item) => (
                    <TableRow
                      key={item.item_id}
                      className={!item.is_eligible && !item.is_duplicate ? 'opacity-50' : ''}
                    >
                      <TableCell className="w-10">
                        <Checkbox
                          checked={selectedIds.has(item.item_id)}
                          onCheckedChange={(checked) => toggleItem(item.item_id, !!checked)}
                          disabled={!item.is_eligible || item.is_duplicate}
                          aria-label={`选择 ${item.title}`}
                        />
                      </TableCell>
                      <TableCell className="w-16 font-mono text-xs text-muted-foreground">
                        {item.item_id}
                      </TableCell>
                      <TableCell className="max-w-[280px]">
                        <div className="truncate text-sm" title={item.title}>
                          {item.title}
                        </div>
                        {item.creators.length > 0 && (
                          <div className="text-xs text-muted-foreground truncate">
                            {item.creators.join(', ')}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="w-20">
                        <Badge variant="outline" className="text-xs">
                          {item.attachment_type?.toUpperCase() || 'N/A'}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <StatusBadges item={item} />
                      </TableCell>
                      <TableCell className="w-24">
                        {item.is_eligible && !item.is_duplicate && item.is_scanned_pdf ? (
                          <Checkbox
                            checked={forceOcrIds.has(item.item_id)}
                            onCheckedChange={(checked) => toggleForceOcr(item.item_id, !!checked)}
                            aria-label={`强制 OCR ${item.title}`}
                          />
                        ) : item.is_eligible && !item.is_duplicate ? (
                          <span className="text-xs text-muted-foreground">-</span>
                        ) : (
                          <span className="text-xs text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <span className="text-xs text-muted-foreground truncate block max-w-[150px]" title={item.ineligible_reason || ''}>
                          {item.ineligible_reason || (item.is_eligible ? '' : '-')}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
          </div>
        </div>

        <DialogFooter className="shrink-0">
          <div className="flex items-center gap-6 flex-1">
            <span className="text-sm text-muted-foreground">
              已选择 <strong>{selectedIds.size}</strong> 篇文献
            </span>
            {forceOcrIds.size > 0 && (
              <span className="text-sm text-purple-600">
                <RefreshCw className="h-3 w-3 inline mr-1" />
                强制OCR <strong>{forceOcrIds.size}</strong> 篇
              </span>
            )}
          </div>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleConfirm} disabled={selectedIds.size === 0 || isLoading}>
            {isLoading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            确认选择 ({selectedIds.size})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
