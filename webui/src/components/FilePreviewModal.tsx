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
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import type { FilePreviewItem } from '@/types/api'
import { FileText, Loader2, FolderOpen, AlertCircle } from 'lucide-react'

interface FilePreviewModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  previewData: FilePreviewItem[]
  filteringRules: string[]
  totalItems: number
  eligibleItems: number
  warnings?: string[]
  onConfirm: (selectedPaths: string[]) => void
  title?: string
  description?: string
  isLoading?: boolean
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function FilePreviewModal({
  open,
  onOpenChange,
  previewData,
  filteringRules,
  totalItems,
  eligibleItems,
  warnings = [],
  onConfirm,
  title = '导入预览',
  description,
  isLoading,
}: FilePreviewModalProps) {
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(() => {
    return new Set(previewData.map((item) => item.path))
  })

  useMemo(() => {
    setSelectedPaths(new Set(previewData.map((item) => item.path)))
  }, [previewData])

  const toggleItem = (path: string, checked: boolean) => {
    setSelectedPaths((prev) => {
      const next = new Set(prev)
      if (checked) {
        next.add(path)
      } else {
        next.delete(path)
      }
      return next
    })
  }

  const toggleAll = (checked: boolean) => {
    if (checked) {
      setSelectedPaths(new Set(previewData.map((item) => item.path)))
    } else {
      setSelectedPaths(new Set())
    }
  }

  const selectedItems = useMemo(() => {
    return previewData.filter((item) => selectedPaths.has(item.path))
  }, [previewData, selectedPaths])

  const allSelected = useMemo(() => {
    return previewData.length > 0 && previewData.every((item) => selectedPaths.has(item.path))
  }, [previewData, selectedPaths])

  const handleConfirm = () => {
    onConfirm(selectedItems.map((item) => item.path))
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[95vw] w-[95vw] h-[85vh] flex flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FolderOpen className="h-5 w-5" />
            {title}
          </DialogTitle>
          <DialogDescription>
            {description || `共 ${totalItems} 个文件，其中 ${eligibleItems} 个将被导入`}
          </DialogDescription>
        </DialogHeader>
        
        <div className="flex items-center justify-between px-1">
          <div className="flex flex-wrap gap-2 text-sm">
            {filteringRules.map((rule, i) => (
              <Badge key={i} variant="outline" className="text-xs">
                {rule}
              </Badge>
            ))}
            {warnings.map((warning, i) => (
              <Badge key={`warn-${i}`} variant="destructive" className="text-xs">
                <AlertCircle className="h-3 w-3 mr-1" />
                {warning}
              </Badge>
            ))}
          </div>
        </div>

        <div className="flex-1 min-h-0 flex flex-col gap-4 overflow-hidden px-1">
          <div className="flex items-center gap-3 p-3 border rounded-lg bg-green-50/50">
            <FileText className="h-5 w-5 text-green-600 shrink-0" />
            <div className="text-sm">
              <div className="text-xs text-muted-foreground">确认导入</div>
              <div><strong>{selectedPaths.size}</strong> / {totalItems} 个文件</div>
            </div>
          </div>

          <div className="flex-1 min-h-0 border rounded-lg overflow-hidden flex flex-col">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <Checkbox
                      checked={allSelected}
                      onCheckedChange={toggleAll}
                      aria-label="全选"
                    />
                  </TableHead>
                  <TableHead>文件路径</TableHead>
                  <TableHead className="w-24">大小</TableHead>
                </TableRow>
              </TableHeader>
            </Table>
            <ScrollArea className="flex-1">
              <Table>
                <TableBody>
                  {previewData.map((item) => (
                    <TableRow key={item.path}>
                      <TableCell className="w-10">
                        <Checkbox
                          checked={selectedPaths.has(item.path)}
                          onCheckedChange={(checked) => toggleItem(item.path, !!checked)}
                          aria-label={`选择 ${item.path}`}
                        />
                      </TableCell>
                      <TableCell>
                        <div className="truncate text-sm" title={item.path}>
                          {item.path.split('/').pop()}
                        </div>
                        <div className="text-xs text-muted-foreground truncate" title={item.path}>
                          {item.path}
                        </div>
                      </TableCell>
                      <TableCell className="w-24 text-sm text-muted-foreground">
                        {formatSize(item.size)}
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
              已选择 <strong>{selectedPaths.size}</strong> 个文件
            </span>
          </div>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleConfirm} disabled={selectedPaths.size === 0 || isLoading}>
            {isLoading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            确认选择 ({selectedPaths.size})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}