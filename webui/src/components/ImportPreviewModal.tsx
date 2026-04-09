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
import { FileText, Loader2, AlertCircle, CheckCircle2, Image, File } from 'lucide-react'

interface ImportPreviewModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  previewData: ZoteroPreviewItem[]
  filteringRules: string[]
  totalItems: number
  eligibleItems: number
  ineligibleItems: number
  onConfirm: (selectedItems: ZoteroPreviewItem[]) => void
  isLoading?: boolean
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
    return new Set(previewData.filter((item) => item.is_eligible).map((item) => item.item_id))
  })

  useMemo(() => {
    setSelectedIds(new Set(previewData.filter((item) => item.is_eligible).map((item) => item.item_id)))
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

  const toggleAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds(new Set(previewData.filter((item) => item.is_eligible).map((item) => item.item_id)))
    } else {
      setSelectedIds(new Set())
    }
  }

  const selectedItems = useMemo(() => {
    return previewData.filter((item) => selectedIds.has(item.item_id))
  }, [previewData, selectedIds])

  const allEligibleSelected = useMemo(() => {
    const eligibleIds = new Set(previewData.filter((item) => item.is_eligible).map((item) => item.item_id))
    return eligibleIds.size > 0 && [...eligibleIds].every((id) => selectedIds.has(id))
  }, [previewData, selectedIds])

  const handleConfirm = () => {
    onConfirm(selectedItems)
    onOpenChange(false)
  }

  const scannedCount = previewData.filter((item) => item.is_scanned_pdf && item.is_eligible).length
  const hasMdCacheCount = previewData.filter((item) => item.has_md_cache && item.is_eligible).length

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[95vw] w-[95vw] h-[85vh] flex flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            导入预览
          </DialogTitle>
          <DialogDescription>
            应用筛选规则后，共 {totalItems} 篇文献，其中 {eligibleItems} 篇符合条件，{ineligibleItems} 篇将被跳过
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 min-h-0 flex flex-col gap-4 overflow-hidden">
          <div className="flex flex-wrap gap-3 text-sm">
            {filteringRules.map((rule, i) => (
              <Badge key={i} variant="outline" className="text-xs">
                {rule}
              </Badge>
            ))}
          </div>

          <div className="grid grid-cols-3 gap-4 text-sm">
            <div className="flex items-center gap-2 p-3 border rounded-lg bg-muted/30">
              <CheckCircle2 className="h-4 w-4 text-green-600" />
              <span>符合条件: <strong>{eligibleItems}</strong> 篇</span>
            </div>
            <div className="flex items-center gap-2 p-3 border rounded-lg bg-muted/30">
              <AlertCircle className="h-4 w-4 text-amber-600" />
              <span>将跳过: <strong>{ineligibleItems}</strong> 篇</span>
            </div>
            <div className="flex items-center gap-2 p-3 border rounded-lg bg-muted/30">
              <Image className="h-4 w-4 text-blue-600" />
              <span>扫描件PDF: <strong>{scannedCount}</strong> 篇</span>
            </div>
          </div>

          <div className="flex-1 min-h-0 border rounded-lg overflow-hidden flex flex-col">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">
                    <Checkbox
                      checked={allEligibleSelected}
                      onCheckedChange={toggleAll}
                      aria-label="全选"
                    />
                  </TableHead>
                  <TableHead className="w-20">Doc ID</TableHead>
                  <TableHead>文档名称</TableHead>
                  <TableHead className="w-24">类型</TableHead>
                  <TableHead className="w-28">状态</TableHead>
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
                      className={!item.is_eligible ? 'opacity-60' : ''}
                    >
                      <TableCell className="w-12">
                        <Checkbox
                          checked={selectedIds.has(item.item_id)}
                          onCheckedChange={(checked) => toggleItem(item.item_id, !!checked)}
                          disabled={!item.is_eligible}
                          aria-label={`选择 ${item.title}`}
                        />
                      </TableCell>
                      <TableCell className="w-20 font-mono text-xs text-muted-foreground">
                        {item.item_id}
                      </TableCell>
                      <TableCell className="max-w-[300px]">
                        <div className="truncate" title={item.title}>
                          {item.title}
                        </div>
                        {item.creators.length > 0 && (
                          <div className="text-xs text-muted-foreground truncate">
                            {item.creators.join(', ')}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="w-24">
                        <Badge
                          variant="outline"
                          className="text-xs"
                        >
                          {item.attachment_type?.toUpperCase() || 'N/A'}
                        </Badge>
                        {item.is_scanned_pdf && (
                          <Badge variant="secondary" className="ml-1 text-xs">
                            <Image className="h-3 w-3 mr-1" />
                            扫描
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="w-28">
                        {item.is_eligible ? (
                          <Badge variant="default" className="text-xs bg-green-600">
                            <CheckCircle2 className="h-3 w-3 mr-1" />
                            符合
                          </Badge>
                        ) : (
                          <Badge variant="destructive" className="text-xs">
                            <AlertCircle className="h-3 w-3 mr-1" />
                            跳过
                          </Badge>
                        )}
                        {item.has_md_cache && item.is_eligible && (
                          <Badge variant="secondary" className="ml-1 text-xs">
                            <File className="h-3 w-3 mr-1" />
                            MD缓存
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <span className="text-xs text-muted-foreground">
                          {item.ineligible_reason || (item.is_eligible ? '将通过 [kb] 过滤' : '无')}
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
          <div className="flex items-center gap-4 flex-1">
            <span className="text-sm text-muted-foreground">
              已选择 <strong>{selectedIds.size}</strong> 篇文献
            </span>
          </div>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleConfirm} disabled={selectedIds.size === 0 || isLoading}>
            {isLoading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            确认导入 ({selectedIds.size})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
