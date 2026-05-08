import { File, X, Book, FileText, Scan, Zap, Database } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import type { FileTreeItem } from './FileTree'
import { cn } from '@/lib/utils'

interface SelectedFilesPanelProps {
  selectedItems: FileTreeItem[]
  onRemove: (id: string) => void
  onClearAll: () => void
}

export function SelectedFilesPanel({
  selectedItems,
  onRemove,
  onClearAll,
}: SelectedFilesPanelProps) {
  const getIcon = (item: FileTreeItem) => {
    switch (item.type) {
      case 'folder':
      case 'collection':
        return <Book className="h-4 w-4 shrink-0 text-muted-foreground" />
      case 'file':
        return <File className="h-4 w-4 shrink-0 text-muted-foreground" />
      case 'item':
        return <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
      default:
        return <File className="h-4 w-4 shrink-0 text-muted-foreground" />
    }
  }

  const formatSize = (bytes?: number) => {
    if (!bytes) return ''
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  return (
    <div className="flex flex-col h-full border rounded-lg">
      <div className="flex items-center justify-between p-3 border-b bg-muted/30">
        <span className="text-sm font-medium">
          已选择 ({selectedItems.length})
        </span>
        {selectedItems.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onClearAll}
            className="h-auto p-0 text-xs text-muted-foreground hover:text-destructive"
          >
            清除全部
          </Button>
        )}
      </div>
      <ScrollArea className="flex-1">
        {selectedItems.length === 0 ? (
          <div className="text-center text-muted-foreground py-8 text-sm">
            尚未选择任何文件
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {selectedItems.map((item) => (
              <div
                key={item.id}
                className="flex items-center gap-2 p-2 bg-background border rounded group hover:bg-muted/50"
              >
                {getIcon(item)}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <p className="text-sm truncate">{item.name}</p>
                    {item.is_scanned_pdf && (
                      <span className="shrink-0 text-[10px] px-1 py-0.5 rounded bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400" title="扫描件PDF">
                        <Scan className="h-2.5 w-2.5 inline mr-0.5" />扫描件
                      </span>
                    )}
                    {item.force_ocr && (
                      <span className="shrink-0 text-[10px] px-1 py-0.5 rounded bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" title="强制OCR">
                        <Zap className="h-2.5 w-2.5 inline mr-0.5" />OCR
                      </span>
                    )}
                    {item.has_md_cache && (
                      <span className="shrink-0 text-[10px] px-1 py-0.5 rounded bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" title="已有MD缓存">
                        <Database className="h-2.5 w-2.5 inline mr-0.5" />缓存
                      </span>
                    )}
                  </div>
                  {item.path && (
                    <p className="text-xs text-muted-foreground truncate">
                      {item.path}
                    </p>
                  )}
                </div>
                {item.size && (
                  <span className="text-xs text-muted-foreground shrink-0">
                    {formatSize(item.size)}
                  </span>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onRemove(item.id)}
                  className={cn(
                    'h-6 w-6 p-0 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity'
                  )}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
