import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

interface DangerConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  kbName: string
  onConfirm: () => Promise<void>
  variant?: 'delete' | 'initialize'
}

export function DangerConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  kbName,
  onConfirm,
  variant = 'delete',
}: DangerConfirmDialogProps) {
  const [inputName, setInputName] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const isConfirmed = inputName === kbName

  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen) {
      setInputName('')
    }
    onOpenChange(newOpen)
  }

  const handleConfirm = async () => {
    if (!isConfirmed) {
      toast.error(`请输入正确的知识库名称: ${kbName}`)
      return
    }
    setIsLoading(true)
    try {
      await onConfirm()
      setInputName('')
      handleOpenChange(false)
    } catch (error: any) {
      const message = error?.response?.data?.detail || '操作失败'
      toast.error(message)
    } finally {
      setIsLoading(false)
    }
  }

  const variantColors = {
    delete: 'text-destructive',
    initialize: 'text-orange-500',
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className={`flex items-center gap-2 ${variantColors[variant]}`}>
            <AlertTriangle className="h-5 w-5" />
            {title}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <p className="text-sm text-muted-foreground">{description}</p>

          <div className="p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg">
            <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200">
              知识库名称: <code className="bg-yellow-100 dark:bg-yellow-800 px-1.5 py-0.5 rounded font-mono">{kbName}</code>
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="confirm-name">请输入知识库名称以确认操作（区分大小写）</Label>
            <Input
              id="confirm-name"
              value={inputName}
              onChange={(e) => setInputName(e.target.value)}
              placeholder={kbName}
              autoComplete="off"
              className="font-mono"
            />
            <p className="text-xs text-muted-foreground">
              必须完全匹配 "{kbName}" 才能执行操作
            </p>
          </div>
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={isLoading}>
            取消
          </Button>
          <Button
            variant={variant === 'delete' ? 'destructive' : 'default'}
            onClick={handleConfirm}
            disabled={!isConfirmed || isLoading}
          >
            {isLoading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            确认{title}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}