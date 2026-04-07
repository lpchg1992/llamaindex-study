import { useState } from 'react'
import { useKBs, useLanceStats, useLanceDocs, useLanceDuplicates } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Database, FileText, AlertTriangle, Loader2, BarChart3 } from 'lucide-react'

export function LanceDB() {
  const { data: kbs } = useKBs()
  const [selectedKB, setSelectedKB] = useState<string>('')
  const { data: stats, isLoading: statsLoading } = useLanceStats(selectedKB)
  const { data: docs, isLoading: docsLoading } = useLanceDocs(selectedKB)
  const { data: duplicates, isLoading: duplicatesLoading } = useLanceDuplicates(selectedKB)

  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-bold">LanceDB Management</h1>

      <div className="mb-6">
        <label className="text-sm font-medium mb-2 block">Knowledge Base</label>
        <Select value={selectedKB} onValueChange={setSelectedKB}>
          <SelectTrigger className="w-64">
            <SelectValue placeholder="Select a knowledge base..." />
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

      {selectedKB ? (
        <Tabs defaultValue="stats" className="w-full">
          <TabsList>
            <TabsTrigger value="stats">
              <BarChart3 className="mr-2 h-4 w-4" />
              Statistics
            </TabsTrigger>
            <TabsTrigger value="documents">
              <FileText className="mr-2 h-4 w-4" />
              Documents
            </TabsTrigger>
            <TabsTrigger value="duplicates">
              <AlertTriangle className="mr-2 h-4 w-4" />
              Duplicates
            </TabsTrigger>
          </TabsList>

          <TabsContent value="stats" className="mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Database className="h-5 w-5" />
                  Table Statistics
                </CardTitle>
              </CardHeader>
              <CardContent>
                {statsLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : stats ? (
                  <div className="grid gap-4 md:grid-cols-3">
                    <div className="p-4 border rounded-lg">
                      <p className="text-sm text-muted-foreground">Total Rows</p>
                      <p className="text-2xl font-bold">{stats.row_count.toLocaleString()}</p>
                    </div>
                    <div className="p-4 border rounded-lg">
                      <p className="text-sm text-muted-foreground">Table Size</p>
                      <p className="text-2xl font-bold">{stats.size_mb.toFixed(2)} MB</p>
                    </div>
                    <div className="p-4 border rounded-lg">
                      <p className="text-sm text-muted-foreground">Knowledge Base</p>
                      <p className="text-2xl font-bold font-mono">{stats.kb_id}</p>
                    </div>
                  </div>
                ) : (
                  <p className="text-muted-foreground text-center py-4">No statistics available</p>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="documents" className="mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FileText className="h-5 w-5" />
                  Document Summary
                </CardTitle>
              </CardHeader>
              <CardContent>
                {docsLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : docs && docs.docs && docs.docs.length > 0 ? (
                  <ScrollArea className="h-96">
                    <div className="space-y-2">
                      {docs.docs.map((doc, index) => (
                        <div key={index} className="p-3 border rounded-lg">
                          <div className="flex items-center justify-between">
                            <div className="flex-1 min-w-0">
                              <p className="font-medium truncate">{doc.source}</p>
                              <div className="flex items-center gap-2 mt-1">
                                <Badge variant="secondary">{doc.node_count} nodes</Badge>
                                <span className="text-xs text-muted-foreground">
                                  {new Date(doc.created_at).toLocaleDateString()}
                                </span>
                              </div>
                            </div>
                            <p className="text-xs text-muted-foreground font-mono ml-2">
                              {doc.doc_id.slice(0, 8)}...
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                ) : (
                  <p className="text-muted-foreground text-center py-4">No documents found</p>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="duplicates" className="mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertTriangle className="h-5 w-5" />
                  Duplicate Sources
                </CardTitle>
              </CardHeader>
              <CardContent>
                {duplicatesLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : duplicates && duplicates.duplicates && duplicates.duplicates.length > 0 ? (
                  <ScrollArea className="h-96">
                    <div className="space-y-3">
                      {duplicates.duplicates.map((dup, index) => (
                        <div key={index} className="p-3 border border-yellow-200 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
                          <p className="font-medium">{dup.source}</p>
                          <p className="text-sm text-muted-foreground mt-1">
                            {dup.count} duplicate entries
                          </p>
                          <div className="flex flex-wrap gap-1 mt-2">
                            {dup.doc_ids.map((id, i) => (
                              <Badge key={i} variant="outline" className="text-xs font-mono">
                                {id.slice(0, 8)}...
                              </Badge>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                ) : (
                  <p className="text-muted-foreground text-center py-4">No duplicates found</p>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      ) : (
        <div className="flex items-center justify-center h-64 border rounded-lg">
          <p className="text-muted-foreground">Select a knowledge base to view LanceDB data</p>
        </div>
      )}
    </div>
  )
}

export function LanceDBPage() {
  return <LanceDB />
}