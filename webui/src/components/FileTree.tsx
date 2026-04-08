import { useState, useMemo, useEffect, useRef } from 'react'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ChevronRight, ChevronDown, File, Folder, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface FileTreeItem {
  id: string
  name: string
  type: 'folder' | 'file' | 'collection' | 'item'
  path?: string
  children?: FileTreeItem[]
  item_id?: number
  md_count?: number
  has_file?: boolean
  has_children?: boolean
  selected?: boolean
  partial?: boolean
  size?: number
}

interface FileTreeProps {
  items: FileTreeItem[]
  selectedIds: Set<string>
  onSelectionChange: (selectedIds: Set<string>, selectedItems: FileTreeItem[]) => void
  loading?: boolean
  searchPlaceholder?: string
  defaultExpandedTypes?: string[]
}

function getDefaultExpandedIds(items: FileTreeItem[], expandedTypes: string[]): Set<string> {
  const result = new Set<string>()
  const collect = (nodes: FileTreeItem[]) => {
    for (const item of nodes) {
      if (expandedTypes.includes(item.type) && item.children && item.children.length > 0) {
        result.add(item.id)
        collect(item.children)
      }
    }
  }
  collect(items)
  return result
}

export function FileTree({
  items,
  selectedIds,
  onSelectionChange,
  loading,
  searchPlaceholder = '搜索...',
  defaultExpandedTypes,
}: FileTreeProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const hasInitializedRef = useRef(false)

  useEffect(() => {
    if (!defaultExpandedTypes || hasInitializedRef.current) return
    if (items.length > 0) {
      hasInitializedRef.current = true
      setExpandedIds(getDefaultExpandedIds(items, defaultExpandedTypes))
    }
  }, [items, defaultExpandedTypes])

  const toggleExpanded = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const handleItemSelect = (item: FileTreeItem, checked: boolean) => {
    const newSelected = new Set(selectedIds)
    const idsToToggle = getAllItemIds(item, checked)

    idsToToggle.forEach((id) => {
      if (checked) {
        newSelected.add(id)
      } else {
        newSelected.delete(id)
      }
    })

    const selectedItems = flattenItems(items).filter((i) => newSelected.has(i.id))
    onSelectionChange(newSelected, selectedItems)
  }

  const getAllItemIds = (item: FileTreeItem, include: boolean): string[] => {
    const ids = [item.id]
    if (item.type === 'folder' && item.children) {
      item.children.forEach((child) => {
        ids.push(...getAllItemIds(child, include))
      })
    }
    return ids
  }

  const flattenItems = (items: FileTreeItem[]): FileTreeItem[] => {
    const result: FileTreeItem[] = []
    const flatten = (items: FileTreeItem[]) => {
      for (const item of items) {
        if (item.type === 'file' || item.type === 'item') {
          result.push(item)
        }
        if (item.children) {
          flatten(item.children)
        }
      }
    }
    flatten(items)
    return result
  }

  const isItemSelected = (item: FileTreeItem): boolean => {
    return selectedIds.has(item.id)
  }

  const isItemPartial = (item: FileTreeItem): boolean => {
    if (item.type !== 'folder' && item.type !== 'collection') return false
    if (!item.children) return false

    const childFileItems = flattenItems([item]).filter(
      (i) => i.type === 'file' || i.type === 'item'
    )
    if (childFileItems.length === 0) return false

    const selectedCount = childFileItems.filter((i) => selectedIds.has(i.id)).length
    return selectedCount > 0 && selectedCount < childFileItems.length
  }

  const filterItems = (items: FileTreeItem[], query: string): FileTreeItem[] => {
    if (!query) return items

    const result: FileTreeItem[] = []
    const lowerQuery = query.toLowerCase()

    for (const item of items) {
      const nameMatch = item.name.toLowerCase().includes(lowerQuery)
      const childMatches = item.children
        ? filterItems(item.children, query).length > 0
        : false

      if (nameMatch || childMatches) {
        result.push({
          ...item,
          children: childMatches && !nameMatch ? filterItems(item.children || [], query) : item.children,
        })
      }
    }
    return result
  }

  const filteredItems = useMemo(
    () => filterItems(items, searchQuery),
    [items, searchQuery]
  )

  const renderItem = (item: FileTreeItem, depth: number = 0) => {
    const isExpanded = expandedIds.has(item.id)
    const isSelected = isItemSelected(item)
    const isPartial = isItemPartial(item)
    const hasChildren = item.children && item.children.length > 0
    const isFolder = item.type === 'folder' || item.type === 'collection'

    return (
      <div key={item.id}>
        <div
          className={cn(
            'flex items-center gap-2 py-1 px-2 hover:bg-muted/50 rounded cursor-pointer',
            isSelected && 'bg-primary/10'
          )}
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          {isFolder && hasChildren ? (
            <button
              onClick={() => toggleExpanded(item.id)}
              className="p-0.5 hover:bg-muted rounded"
            >
              {isExpanded ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </button>
          ) : (
            <div className="w-5" />
          )}

          {(item.type === 'file' || item.type === 'item') && (
            <Checkbox
              checked={isSelected}
              onCheckedChange={(checked) => handleItemSelect(item, !!checked)}
              className="shrink-0"
            />
          )}

          {isFolder && (
            <Checkbox
              checked={isSelected}
              ref={(el) => {
                if (el) {
                  (el as HTMLButtonElement).dataset.state = isPartial ? 'indeterminate' : isSelected ? 'checked' : 'unchecked'
                }
              }}
              aria-label="Select folder"
              className="shrink-0"
              onCheckedChange={(checked) => handleItemSelect(item, !!checked)}
            />
          )}

          {item.type === 'folder' || item.type === 'collection' ? (
            <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <File className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}

          <span
            className="flex-1 truncate text-sm"
            onClick={() => isFolder && hasChildren && toggleExpanded(item.id)}
          >
            {item.name}
          </span>

          {item.md_count !== undefined && (
            <span className="text-xs text-muted-foreground">
              {item.md_count} notes
            </span>
          )}

          {item.has_file !== undefined && (
            <span className="text-xs text-muted-foreground">
              {item.has_file ? '📎' : ''}
            </span>
          )}
        </div>

        {hasChildren && isExpanded && (
          <div>
            {item.children!.map((child) => renderItem(child, depth + 1))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-2 border-b">
        <Input
          placeholder={searchPlaceholder}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="h-8"
        />
      </div>
      <ScrollArea className="flex-1">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="text-center text-muted-foreground py-8 text-sm">
            {searchQuery ? '没有找到匹配的结果' : '没有可用项'}
          </div>
        ) : (
          <div className="py-2">
            {filteredItems.map((item) => renderItem(item))}
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
