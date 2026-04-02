import { useState } from 'react'
import { useKBs, useSearch } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Search as SearchIcon, FileText } from 'lucide-react'
import type { SearchResult } from '@/types/api'

export function SearchPage() {
  const { data: kbs } = useKBs()
  const searchMutation = useSearch()

  const [query, setQuery] = useState('')
  const [selectedKBs, setSelectedKBs] = useState<string[]>([])
  const [results, setResults] = useState<SearchResult[]>([])
  const [hasSearched, setHasSearched] = useState(false)

  const toggleKB = (kbId: string) => {
    setSelectedKBs((prev) =>
      prev.includes(kbId) ? prev.filter((id) => id !== kbId) : [...prev, kbId]
    )
  }

  const handleSearch = async () => {
    if (!query || selectedKBs.length === 0) return
    setHasSearched(true)
    try {
      const response = await searchMutation.mutateAsync({
        query,
        kb_ids: selectedKBs.join(','),
        top_k: 10,
        route_mode: 'general',
      })
      setResults(response)
    } catch (error) {
      console.error('Search failed:', error)
    }
  }

  return (
    <div className="flex h-full">
      <div className="w-80 border-r p-4">
        <h2 className="mb-4 text-lg font-semibold">Search</h2>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Knowledge Bases</Label>
            <ScrollArea className="h-64">
              <div className="space-y-2">
                {kbs?.map((kb) => (
                  <div key={kb.id} className="flex items-center space-x-2">
                    <Checkbox
                      id={kb.id}
                      checked={selectedKBs.includes(kb.id)}
                      onCheckedChange={() => toggleKB(kb.id)}
                    />
                    <Label htmlFor={kb.id} className="text-sm font-normal">
                      {kb.name || kb.id}
                      <span className="ml-2 text-xs text-muted-foreground">
                        ({kb.row_count || 0})
                      </span>
                    </Label>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col p-4">
        <div className="mb-4 flex gap-2">
          <Input
            placeholder="Enter search query..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          />
          <Button onClick={handleSearch} disabled={searchMutation.isPending || !query || selectedKBs.length === 0}>
            <SearchIcon className="mr-2 h-4 w-4" />
            {searchMutation.isPending ? 'Searching...' : 'Search'}
          </Button>
        </div>

        <ScrollArea className="flex-1">
          {hasSearched && results.length === 0 ? (
            <p className="text-muted-foreground">No results found</p>
          ) : (
            <div className="space-y-4">
              {results.map((result, index) => (
                <Card key={index}>
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4 text-muted-foreground" />
                        <CardTitle className="text-sm">
                          {result.metadata?.file_name as string || 'Document'}
                        </CardTitle>
                      </div>
                      <Badge variant="outline">
                        Score: {(result.score * 100).toFixed(1)}%
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-muted-foreground line-clamp-3">
                      {result.text}
                    </p>
                    {result.kb_id && (
                      <p className="mt-2 text-xs text-muted-foreground">
                        KB: {result.kb_id}
                      </p>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </ScrollArea>
      </div>
    </div>
  )
}

export function Search() {
  return <SearchPage />
}