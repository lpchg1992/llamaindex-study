import { useState } from 'react'
import { useKBs, useIngestFile, useIngestObsidian, useIngestZotero, useZoteroCollections, useSearchZoteroCollections, useObsidianVaults } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Upload, FolderOpen, Book, FileText, Loader2, Search, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import type { ZoteroCollection } from '@/types/api'

export function Import() {
  const { data: kbs } = useKBs()
  const ingestFile = useIngestFile()
  const ingestObsidian = useIngestObsidian()
  const ingestZotero = useIngestZotero()

  const [selectedKB, setSelectedKB] = useState<string>('')
  const [filePath, setFilePath] = useState('')
  const [vaultPath, setVaultPath] = useState('')
  const [folderPath, setFolderPath] = useState('')
  const [collectionName, setCollectionName] = useState('')
  const [asyncMode, setAsyncMode] = useState(true)
  const [isLoading, setIsLoading] = useState(false)

  const handleFileImport = async () => {
    if (!selectedKB || !filePath) return
    setIsLoading(true)
    try {
      const result = await ingestFile.mutateAsync({
        kbId: selectedKB,
        req: { path: filePath, async_mode: asyncMode, refresh_topics: true },
      })
      if (result.task_id) {
        toast.success(`Import started. Task ID: ${result.task_id}`)
      } else {
        toast.success(`Import completed: ${result.message}`)
      }
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'Import failed')
    } finally {
      setIsLoading(false)
    }
  }

  const handleObsidianImport = async () => {
    if (!selectedKB || !vaultPath) return
    setIsLoading(true)
    try {
      const result = await ingestObsidian.mutateAsync({
        kbId: selectedKB,
        req: {
          vault_path: vaultPath,
          folder_path: folderPath || undefined,
          async_mode: asyncMode,
          refresh_topics: true,
        },
      })
      if (result.task_id) {
        toast.success(`Import started. Task ID: ${result.task_id}`)
      } else {
        toast.success(`Import completed: ${result.message}`)
      }
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'Import failed')
    } finally {
      setIsLoading(false)
    }
  }

  const handleZoteroImport = async () => {
    if (!selectedKB || !collectionName) return
    setIsLoading(true)
    try {
      const result = await ingestZotero.mutateAsync({
        kbId: selectedKB,
        req: {
          collection_name: collectionName,
          async_mode: asyncMode,
          refresh_topics: true,
        },
      })
      if (result.task_id) {
        toast.success(`Import started. Task ID: ${result.task_id}`)
      } else {
        toast.success(`Import completed: ${result.message}`)
      }
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'Import failed')
    } finally {
      setIsLoading(false)
    }
  }

  const { data: zoteroCollections, isLoading: collectionsLoading, refetch: refetchCollections } = useZoteroCollections()
  const searchCollections = useSearchZoteroCollections()
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCollection, setSelectedCollection] = useState<ZoteroCollection | null>(null)

  const handleSearchCollections = async () => {
    if (!searchQuery.trim()) {
      refetchCollections()
      return
    }
    try {
      await searchCollections.mutateAsync(searchQuery)
    } catch (error) {
      console.error('Search failed:', error)
    }
  }

  const displayedCollections = searchQuery.trim() 
    ? searchCollections.data?.collections || [] 
    : zoteroCollections?.collections || []

  const handleSelectCollection = (collection: ZoteroCollection) => {
    setSelectedCollection(collection)
    setCollectionName(collection.collectionName)
  }

  const { data: obsidianVaults, isLoading: vaultsLoading, refetch: refetchVaults } = useObsidianVaults()
  const [selectedVault, setSelectedVault] = useState<string>('')

  const handleSelectVault = (vaultPath: string) => {
    setSelectedVault(vaultPath)
    setVaultPath(vaultPath)
  }

  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-bold">Import Documents</h1>

      <div className="mb-6">
        <Label>Target Knowledge Base</Label>
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

      <Tabs defaultValue="file" className="w-full">
        <TabsList>
          <TabsTrigger value="file">
            <FileText className="mr-2 h-4 w-4" />
            File
          </TabsTrigger>
          <TabsTrigger value="obsidian">
            <Book className="mr-2 h-4 w-4" />
            Obsidian
          </TabsTrigger>
          <TabsTrigger value="zotero">
            <FolderOpen className="mr-2 h-4 w-4" />
            Zotero
          </TabsTrigger>
        </TabsList>

        <TabsContent value="file" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Upload className="h-5 w-5" />
                File Import
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>File or Folder Path</Label>
                <Input
                  placeholder="/path/to/file.pdf or /path/to/folder"
                  value={filePath}
                  onChange={(e) => setFilePath(e.target.value)}
                />
              </div>
              <div className="flex items-center space-x-2">
                <Button
                  variant="outline"
                  onClick={() => setAsyncMode(!asyncMode)}
                >
                  Async: {asyncMode ? 'ON' : 'OFF'}
                </Button>
                <span className="text-sm text-muted-foreground">
                  {asyncMode ? 'Submit as background task' : 'Process synchronously'}
                </span>
              </div>
              <Button onClick={handleFileImport} disabled={!selectedKB || !filePath || isLoading}>
                {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isLoading ? 'Importing...' : 'Start Import'}
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="obsidian" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Book className="h-5 w-5" />
                Obsidian Vault Import
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Select Vault</Label>
                <div className="flex gap-2">
                  <Select value={selectedVault} onValueChange={handleSelectVault}>
                    <SelectTrigger>
                      <SelectValue placeholder="Choose a vault..." />
                    </SelectTrigger>
                    <SelectContent>
                      {vaultsLoading ? (
                        <div className="flex items-center justify-center py-2">
                          <Loader2 className="h-4 w-4 animate-spin" />
                        </div>
                      ) : obsidianVaults?.vaults && obsidianVaults.vaults.length > 0 ? (
                        obsidianVaults.vaults.map((vault) => (
                          <SelectItem key={vault.name} value={vault.path}>
                            {vault.name} ({vault.note_count || 0} notes)
                          </SelectItem>
                        ))
                      ) : (
                        <div className="p-2 text-sm text-muted-foreground">No vaults found</div>
                      )}
                    </SelectContent>
                  </Select>
                  <Button variant="outline" onClick={() => refetchVaults()} disabled={vaultsLoading}>
                    <RefreshCw className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              <div className="space-y-2">
                <Label>Or Enter Vault Path Manually</Label>
                <Input
                  placeholder="~/Documents/Obsidian Vault"
                  value={vaultPath}
                  onChange={(e) => { setVaultPath(e.target.value); setSelectedVault('') }}
                />
              </div>
              
              <div className="space-y-2">
                <Label>Folder Path (optional)</Label>
                <Input
                  placeholder="IT/Programming"
                  value={folderPath}
                  onChange={(e) => setFolderPath(e.target.value)}
                />
              </div>
              <div className="flex items-center space-x-2">
                <Button
                  variant="outline"
                  onClick={() => setAsyncMode(!asyncMode)}
                >
                  Async: {asyncMode ? 'ON' : 'OFF'}
                </Button>
                <span className="text-sm text-muted-foreground">
                  {asyncMode ? 'Submit as background task' : 'Process synchronously'}
                </span>
              </div>
              <Button onClick={handleObsidianImport} disabled={!selectedKB || !vaultPath || isLoading}>
                {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isLoading ? 'Importing...' : 'Start Import'}
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="zotero" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FolderOpen className="h-5 w-5" />
                Zotero Collection Import
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                <Input
                  placeholder="Search collections..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearchCollections()}
                />
                <Button variant="outline" onClick={handleSearchCollections} disabled={searchCollections.isPending}>
                  <Search className="h-4 w-4" />
                </Button>
                <Button variant="ghost" onClick={() => { setSearchQuery(''); refetchCollections() }} disabled={collectionsLoading}>
                  <RefreshCw className="h-4 w-4" />
                </Button>
              </div>
              
              <ScrollArea className="h-64">
                {collectionsLoading || searchCollections.isPending ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : displayedCollections.length > 0 ? (
                  <div className="space-y-2">
                    {displayedCollections.map((collection) => (
                      <div
                        key={collection.collectionID}
                        className={`p-3 border rounded-lg cursor-pointer transition-colors ${
                          selectedCollection?.collectionID === collection.collectionID
                            ? 'border-primary bg-primary/5'
                            : 'hover:border-primary/50'
                        }`}
                        onClick={() => handleSelectCollection(collection)}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium">{collection.collectionName}</span>
                          {collection.numItems !== undefined && (
                            <Badge variant="secondary">{collection.numItems} items</Badge>
                          )}
                        </div>
                        {collection.parentCollectionID && (
                          <p className="text-xs text-muted-foreground mt-1">
                            Parent ID: {collection.parentCollectionID}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-center text-muted-foreground py-8">
                    {searchQuery ? 'No collections found' : 'No collections available'}
                  </p>
                )}
              </ScrollArea>

              {selectedCollection && (
                <div className="p-3 bg-muted rounded-lg">
                  <div className="flex items-center justify-between">
                    <span className="text-sm">Selected: <strong>{selectedCollection.collectionName}</strong></span>
                    <Button variant="ghost" size="sm" onClick={() => { setSelectedCollection(null); setCollectionName('') }}>
                      Clear
                    </Button>
                  </div>
                </div>
              )}

              <div className="flex items-center space-x-2">
                <Button
                  variant="outline"
                  onClick={() => setAsyncMode(!asyncMode)}
                >
                  Async: {asyncMode ? 'ON' : 'OFF'}
                </Button>
                <span className="text-sm text-muted-foreground">
                  {asyncMode ? 'Submit as background task' : 'Process synchronously'}
                </span>
              </div>
              <Button onClick={handleZoteroImport} disabled={!selectedKB || !collectionName || isLoading}>
                {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isLoading ? 'Importing...' : 'Start Import'}
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}