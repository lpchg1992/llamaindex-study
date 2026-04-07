import { useState, useEffect, useRef } from 'react'
import { useKBs, useChat, useChatSessions, useChatHistory, useDeleteChatSession } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { MessageSquare, Loader2, Send, Trash2, Plus, Clock } from 'lucide-react'
import { toast } from 'sonner'
import type { ChatMessage } from '@/types/api'

export function Chat() {
  const { data: kbs } = useKBs()
  const [selectedKB, setSelectedKB] = useState<string>('')
  const [selectedSession, setSelectedSession] = useState<string>('')
  const chatMutation = useChat(selectedKB)
  const { data: sessions, refetch: refetchSessions } = useChatSessions(selectedKB)
  const { data: history } = useChatHistory(selectedKB, selectedSession)
  const deleteSession = useDeleteChatSession()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputMessage, setInputMessage] = useState('')
  const [currentSessionId, setCurrentSessionId] = useState<string>('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (history?.history) {
      setMessages(history.history)
    }
  }, [history])

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSelectKB = (kbId: string) => {
    setSelectedKB(kbId)
    setSelectedSession('')
    setMessages([])
  }

  const handleSelectSession = (sessionId: string) => {
    setSelectedSession(sessionId)
    setCurrentSessionId(sessionId)
  }

  const handleNewChat = () => {
    setSelectedSession('')
    setCurrentSessionId('')
    setMessages([])
  }

  const handleSend = async () => {
    if (!inputMessage.trim() || !selectedKB) return

    const userMessage: ChatMessage = { role: 'user', content: inputMessage }
    setMessages(prev => [...prev, userMessage])
    setInputMessage('')

    try {
      const result = await chatMutation.mutateAsync({
        message: inputMessage,
        sessionId: currentSessionId || undefined,
      })
      const assistantMessage: ChatMessage = { role: 'assistant', content: result.response }
      setMessages(prev => [...prev, assistantMessage])
      if (result.session_id && !currentSessionId) {
        setCurrentSessionId(result.session_id)
      }
      refetchSessions()
    } catch (error) {
      toast.error('Failed to send message')
      setMessages(prev => prev.filter(m => m !== userMessage))
    }
  }

  const handleDeleteSession = async (kbId: string, sessionId: string) => {
    if (!confirm('Delete this chat session?')) return
    try {
      await deleteSession.mutateAsync({ kbId, sessionId })
      if (selectedSession === sessionId) {
        setSelectedSession('')
        setMessages([])
      }
      toast.success('Session deleted')
      refetchSessions()
    } catch (error) {
      toast.error('Failed to delete session')
    }
  }

  return (
    <div className="flex h-full">
      <div className="w-80 border-r p-4 flex flex-col">
        <h2 className="mb-4 text-lg font-semibold">Chat</h2>

        <div className="mb-4 space-y-2">
          <Label>Knowledge Base</Label>
          <Select value={selectedKB} onValueChange={handleSelectKB}>
            <SelectTrigger>
              <SelectValue placeholder="Select KB..." />
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

        <div className="flex items-center justify-between mb-2">
          <Label>Sessions</Label>
          <Button variant="ghost" size="sm" onClick={handleNewChat} disabled={!selectedKB}>
            <Plus className="h-4 w-4 mr-1" />
            New
          </Button>
        </div>

        <ScrollArea className="flex-1">
          <div className="space-y-2">
            {sessions?.sessions && sessions.sessions.length > 0 ? (
              sessions.sessions.map((session) => (
                <div
                  key={session.session_id}
                  className={`p-2 border rounded-lg cursor-pointer transition-colors ${
                    selectedSession === session.session_id
                      ? 'border-primary bg-primary/5'
                      : 'hover:border-primary/50'
                  }`}
                  onClick={() => handleSelectSession(session.session_id)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Clock className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm truncate">
                        {new Date(session.updated_at).toLocaleDateString()}
                      </span>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteSession(selectedKB, session.session_id)
                      }}
                    >
                      <Trash2 className="h-3 w-3 text-destructive" />
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    {session.message_count} messages
                  </p>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">
                {selectedKB ? 'No sessions yet' : 'Select a KB first'}
              </p>
            )}
          </div>
        </ScrollArea>
      </div>

      <div className="flex-1 flex flex-col p-4">
        {selectedKB ? (
          <>
            <div className="mb-4 flex items-center gap-2">
              <MessageSquare className="h-5 w-5 text-muted-foreground" />
              <span className="font-medium">
                {selectedKB} {currentSessionId && <span className="text-muted-foreground text-sm">({currentSessionId.slice(0, 8)}...)</span>}
              </span>
            </div>

            <ScrollArea className="flex-1 mb-4">
              <div className="space-y-4">
                {messages.length === 0 ? (
                  <div className="flex items-center justify-center h-full text-muted-foreground">
                    Start a conversation by typing a message
                  </div>
                ) : (
                  messages.map((msg, index) => (
                    <div
                      key={index}
                      className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
                      <div
                        className={`max-w-[70%] p-3 rounded-lg ${
                          msg.role === 'user'
                            ? 'bg-primary text-primary-foreground'
                            : 'bg-muted'
                        }`}
                      >
                        <p className="whitespace-pre-wrap">{msg.content}</p>
                      </div>
                    </div>
                  ))
                )}
                {chatMutation.isPending && (
                  <div className="flex justify-start">
                    <div className="bg-muted p-3 rounded-lg">
                      <Loader2 className="h-5 w-5 animate-spin" />
                    </div>
                  </div>
                )}
                <div ref={scrollRef} />
              </div>
            </ScrollArea>

            <div className="flex gap-2">
              <Textarea
                placeholder="Type your message..."
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
                className="min-h-[80px]"
              />
              <Button onClick={handleSend} disabled={!inputMessage.trim() || chatMutation.isPending}>
                {chatMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </>
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            Select a knowledge base to start chatting
          </div>
        )}
      </div>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <span className="text-sm font-medium">{children}</span>
}

export function ChatPage() {
  return <Chat />
}