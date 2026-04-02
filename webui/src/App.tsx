import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Layout } from '@/components/Layout'
import { Dashboard } from '@/pages/Dashboard'
import { KnowledgeBase } from '@/pages/KnowledgeBase'
import { Search } from '@/pages/Search'
import { Query } from '@/pages/Query'
import { Import } from '@/pages/Import'
import { Tasks } from '@/pages/Tasks'
import { Evaluate } from '@/pages/Evaluate'
import { Models } from '@/pages/Models'
import { Settings } from '@/pages/Settings'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60,
      retry: 1,
    },
  },
})

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/knowledge-base" element={<KnowledgeBase />} />
            <Route path="/search" element={<Search />} />
            <Route path="/query" element={<Query />} />
            <Route path="/import" element={<Import />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/evaluate" element={<Evaluate />} />
            <Route path="/models" element={<Models />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App