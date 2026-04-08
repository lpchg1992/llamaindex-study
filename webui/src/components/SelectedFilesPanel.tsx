import { File, X, Book, FileText } from 'lucide-react'
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
                  <p className="text-sm truncate">{item.name}</p>
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
