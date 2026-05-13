import { useState, useEffect, useRef } from 'react'
import { useKBs, useChat, useChatSessions, useChatHistory, useDeleteChatSession, useModels } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Label } from '@/components/ui/label'
import { MessageSquare, Loader2, Send, Trash2, Plus, Clock, User, Bot, Settings2, ChevronDown, ChevronUp } from 'lucide-react'
import { toast } from 'sonner'
import { MarkdownRenderer } from '@/components/MarkdownRenderer'
import type { ChatMessage } from '@/types/api'

export function Chat() {
  const { data: kbs } = useKBs()
  const [selectedKB, setSelectedKB] = useState<string>('')
  const [selectedSession, setSelectedSession] = useState<string>('')
  const chatMutation = useChat(selectedKB)
  const { data: sessions, refetch: refetchSessions } = useChatSessions(selectedKB)
  const { data: history } = useChatHistory(selectedKB, selectedSession)
  const deleteSession = useDeleteChatSession()
  const { data: models } = useModels('llm')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputMessage, setInputMessage] = useState('')
  const [currentSessionId, setCurrentSessionId] = useState<string>('')
  const [chatMode, setChatMode] = useState<string>('condense_question')
  const [temperature, setTemperature] = useState<number>(0.7)
  const [maxTokens, setMaxTokens] = useState<string>('')
  const [topK, setTopK] = useState<string>('')
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [showSettings, setShowSettings] = useState(false)
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
        session_id: currentSessionId || undefined,
        chat_mode: chatMode,
        model_id: selectedModel || undefined,
        temperature: temperature,
        max_tokens: maxTokens ? parseInt(maxTokens, 10) : undefined,
        top_k: topK ? parseInt(topK, 10) : undefined,
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

        <div className="mb-4 space-y-2">
          <Label>Chat Mode</Label>
          <Select value={chatMode} onValueChange={setChatMode}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="condense_question">Condense Question</SelectItem>
              <SelectItem value="context">Context</SelectItem>
              <SelectItem value="condense_plus_context">Condense + Context</SelectItem>
              <SelectItem value="simple">Simple</SelectItem>
              <SelectItem value="best">Best</SelectItem>
            </SelectContent>
          </Select>

          <details className="text-xs border rounded-md p-2 bg-muted/30">
            <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
              What does each mode do?
            </summary>
            <div className="mt-2 space-y-2 text-muted-foreground">
              <div>
                <span className="font-medium text-foreground">Condense Question</span> (default)
                <p className="mt-0.5">将历史对话压缩成独立问题，再检索相关上下文。适合多轮对话场景，推荐大多数情况使用。</p>
              </div>
              <div>
                <span className="font-medium text-foreground">Context</span>
                <p className="mt-0.5">仅根据当前问题检索上下文，不利用对话历史。适合单轮问答或不需要记忆的简单查询。</p>
              </div>
              <div>
                <span className="font-medium text-foreground">Condense + Context</span>
                <p className="mt-0.5">结合历史压缩与上下文检索，在多轮对话中获得更丰富的上下文支撑。</p>
              </div>
              <div>
                <span className="font-medium text-foreground">Simple</span>
                <p className="mt-0.5">无检索模式，直接与 LLM 对话。不依赖知识库内容，适合闲聊或通用知识问答。</p>
              </div>
              <div>
                <span className="font-medium text-foreground">Best</span>
                <p className="mt-0.5">自动选择最优模式（由 LLM 判断当前对话应使用哪种策略）。适合不想手动选择的用户。</p>
              </div>
            </div>
          </details>
        </div>

        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowSettings(!showSettings)}
          className="mb-2 w-full justify-start text-muted-foreground"
        >
          <Settings2 className="h-4 w-4 mr-2" />
          Advanced Settings
          {showSettings ? <ChevronUp className="h-4 w-4 ml-auto" /> : <ChevronDown className="h-4 w-4 ml-auto" />}
        </Button>

        {showSettings && (
          <div className="mb-4 space-y-3 pl-2 border-l-2 border-muted">
            <div className="space-y-1">
              <Label className="text-xs">Model</Label>
              <Select value={selectedModel} onValueChange={setSelectedModel}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="Default model" />
                </SelectTrigger>
                <SelectContent>
                  {models?.map((model) => (
                    <SelectItem key={model.id} value={model.id}>
                      {model.name || model.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs flex justify-between">
                Temperature
                <span className="text-muted-foreground font-normal">{temperature.toFixed(1)}</span>
              </Label>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value))}
                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Max Tokens</Label>
              <Input
                type="number"
                placeholder="No limit"
                value={maxTokens}
                onChange={(e) => setMaxTokens(e.target.value)}
                className="h-8 text-xs"
                min="1"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Top K (Retrieval)</Label>
              <Input
                type="number"
                placeholder="Default (5)"
                value={topK}
                onChange={(e) => setTopK(e.target.value)}
                className="h-8 text-xs"
                min="1"
                max="100"
              />
            </div>
          </div>
        )}

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
                      className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`
                      }
                    >
                      <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
                        msg.role === 'user' ? 'bg-primary' : 'bg-muted'
                      }`}>
                        {msg.role === 'user' ? (
                          <User className="w-4 h-4 text-primary-foreground" />
                        ) : (
                          <Bot className="w-4 h-4 text-muted-foreground" />
                        )}
                      </div>
                      <div
                        className={`max-w-[70%] p-4 rounded-2xl ${
                          msg.role === 'user'
                            ? 'bg-primary text-primary-foreground rounded-tr-sm'
                            : 'bg-muted rounded-tl-sm'
                        }`}
                      >
                        <MarkdownRenderer content={msg.content} />
                      </div>
                    </div>
                  ))
                )}
                {chatMutation.isPending && (
                  <div className="flex gap-3">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-muted flex items-center justify-center">
                      <Bot className="w-4 h-4 text-muted-foreground" />
                    </div>
                    <div className="bg-muted p-4 rounded-2xl rounded-tl-sm">
                      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
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

export function ChatPage() {
  return <Chat />
}