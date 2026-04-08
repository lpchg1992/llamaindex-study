import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Database,
  Search,
  MessageSquare,
  ListTodo,
  Settings,
  Cpu,
  ChevronLeft,
  ChevronRight,
  MessagesSquare,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'

interface NavItem {
  to?: string
  icon?: React.ComponentType<{ className?: string }>
  label?: string
  divider?: boolean
}

const navItems: NavItem[] = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { divider: true },
  { to: '/chat', icon: MessagesSquare, label: 'Chat' },
  { to: '/query', icon: MessageSquare, label: 'Query' },
  { to: '/search', icon: Search, label: 'Search' },
  { divider: true },
  { to: '/knowledge-base', icon: Database, label: 'Knowledge Base' },
  { to: '/models', icon: Cpu, label: 'Models' },
  { to: '/tasks', icon: ListTodo, label: 'Tasks' },
  { divider: true },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <aside
      className={cn(
        'relative flex flex-col border-r bg-card transition-all duration-300',
        collapsed ? 'w-16' : 'w-64'
      )}
    >
      <div className="flex h-14 items-center border-b px-4">
        {!collapsed && (
          <h1 className="text-lg font-semibold">LlamaIndex RAG</h1>
        )}
        {collapsed && <span className="text-xl font-bold mx-auto">LR</span>}
      </div>

      <nav className="flex-1 overflow-y-auto p-2">
        <ul className="space-y-1">
          {navItems.map((item, index) => {
            if (item.divider) {
              return (
                <li key={`divider-${index}`} className="my-2">
                  <Separator />
                </li>
              )
            }
            if (!item.to || !item.icon || !item.label) return null
            return (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                      collapsed && 'justify-center px-2'
                    )
                  }
                >
                  <item.icon className="h-5 w-5 shrink-0" />
                  {!collapsed && <span>{item.label}</span>}
                </NavLink>
              </li>
            )
          })}
        </ul>
      </nav>

      <div className="border-t p-2">
        <Button
          variant="ghost"
          size="sm"
          className="w-full"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <>
              <ChevronLeft className="mr-2 h-4 w-4" />
              Collapse
            </>
          )}
        </Button>
      </div>
    </aside>
  )
}