import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

interface MarkdownRendererProps {
  content: string
  className?: string
}

export function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  return (
    <div className={cn('prose prose-sm dark:prose-invert max-w-none', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre: ({ children, ...props }) => (
            <pre className="bg-muted p-3 rounded-lg overflow-x-auto text-xs my-2" {...props}>
              {children}
            </pre>
          ),
          code: ({ className, children, ...props }) => {
            const isInline = !className
            if (isInline) {
              return <code className="bg-muted px-1 py-0.5 rounded text-xs" {...props}>{children}</code>
            }
            return <code className={cn('text-xs', className)} {...props}>{children}</code>
          },
          table: ({ children }) => (
            <div className="overflow-x-auto my-2">
              <table className="min-w-full border-collapse border text-xs">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border bg-muted px-2 py-1 text-left font-medium">{children}</th>
          ),
          td: ({ children }) => (
            <td className="border px-2 py-1">{children}</td>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
