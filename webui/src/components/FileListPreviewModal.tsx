import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
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
import { FileText, FolderOpen, RefreshCw } from 'lucide-react'

interface FileListPreviewItem {
  path: string
  name?: string
  size: number
  relative_path?: string
}

interface FileListPreviewModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  items: FileListPreviewItem[]
  filteringRules: string[]
  totalItems: number
  warnings?: string[]
  onRefresh?: () => void
  isLoading?: boolean
  emptyMessage?: string
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function FileListPreviewModal({
  open,
  onOpenChange,
  title,
  items,
  filteringRules,
  totalItems,
  warnings = [],
  onRefresh,
  isLoading,
  emptyMessage = '没有文件',
}: FileListPreviewModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[95vw] w-[95vw] h-[85vh] flex flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FolderOpen className="h-5 w-5" />
            {title}
          </DialogTitle>
          <DialogDescription>
            共找到 {totalItems} 个文件
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center justify-between px-1">
          <div className="flex flex-wrap gap-2 text-sm">
            {filteringRules.map((rule, i) => (
              <Badge key={i} variant="outline" className="text-xs">
                {rule}
              </Badge>
            ))}
          </div>
          {onRefresh && (
            <Button
              variant="outline"
              size="sm"
              onClick={onRefresh}
              disabled={isLoading}
              title="刷新预览"
            >
              <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
              刷新
            </Button>
          )}
        </div>

        {warnings.length > 0 && (
          <div className="flex flex-col gap-1 p-2 border rounded-lg bg-amber-50/50">
            {warnings.map((warning, i) => (
              <div key={i} className="text-xs text-amber-600">{warning}</div>
            ))}
          </div>
        )}

        <div className="flex-1 min-h-0 border rounded-lg overflow-hidden flex flex-col">
          {items.length === 0 ? (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              {emptyMessage}
            </div>
          ) : (
            <ScrollArea className="flex-1">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>文件名</TableHead>
                    <TableHead className="w-24">大小</TableHead>
                    <TableHead>路径</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item, idx) => (
                    <TableRow key={`${item.path}-${idx}`}>
                      <TableCell className="max-w-[200px]">
                        <div className="truncate text-sm flex items-center gap-2">
                          <FileText className="h-4 w-4 shrink-0" />
                          <span className="truncate" title={item.name || item.path}>
                            {item.name || item.path.split('/').pop()}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="w-24 text-xs text-muted-foreground">
                        {formatSize(item.size)}
                      </TableCell>
                      <TableCell>
                        <div className="truncate text-xs text-muted-foreground max-w-[300px]" title={item.relative_path || item.path}>
                          {item.relative_path || item.path}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
          )}
        </div>

        <DialogFooter className="shrink-0">
          <span className="text-sm text-muted-foreground">
            共 <strong>{items.length}</strong> 个文件显示
          </span>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
