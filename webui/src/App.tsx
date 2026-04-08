import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Layout } from '@/components/Layout'
import { Dashboard } from '@/pages/Dashboard'
import { KnowledgeBase } from '@/pages/KnowledgeBase'
import { Search } from '@/pages/Search'
import { Query } from '@/pages/Query'
import { Tasks } from '@/pages/Tasks'
import { Models } from '@/pages/Models'
import { Settings } from '@/pages/Settings'
import { ChatPage } from '@/pages/Chat'

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
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/models" element={<Models />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/chat" element={<ChatPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App