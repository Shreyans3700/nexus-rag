import { useCallback, useEffect, useRef, useState } from 'react'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ThemeProvider } from './context/ThemeContext'
import { Sidebar } from './components/Sidebar'
import { ChatWindow } from './components/ChatWindow'
import { ChatInput } from './components/ChatInput'
import { useSessions } from './hooks/useSessions'
import { isAbortError, streamChat } from './hooks/useChatStream'
import { uploadAndTrackDocuments } from './hooks/useDocumentUpload'
import type { IngestionStatusMap } from './hooks/useDocumentUpload'
import { ApiError, api } from './lib/api'
import type { ChatMessage } from './lib/types'

const APP_NAME = 'Corpus'

function ChatApp() {
  const { token, user, isAuthenticated, login, signup, logout } = useAuth()
  const { sessions, currentSessionId, setCurrentSessionId, startNewChat, refreshSessions } = useSessions(token)

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [isThinking, setIsThinking] = useState(false)
  const [uploadStatuses, setUploadStatuses] = useState<IngestionStatusMap>({})
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const lastUserQueryRef = useRef<string>('')

  useEffect(() => {
    if (!token) {
      setMessages([])
      return
    }
    let cancelled = false
    api
      .getSessionHistory(token, currentSessionId)
      .then((response) => {
        if (cancelled) return
        setMessages(
          response.history.map((entry) => ({
            role: entry.role === 'Human' ? 'user' : 'assistant',
            content: entry.content,
            sources: entry.sources,
          })),
        )
      })
      .catch((error) => {
        if (cancelled) return
        if (error instanceof ApiError && error.status === 401) {
          logout()
          return
        }
        // 404 for a brand-new session that has no history yet — start empty.
        setMessages([])
      })
    return () => {
      cancelled = true
    }
  }, [token, currentSessionId, logout])

  const handleNewChat = useCallback(() => {
    startNewChat()
    setMessages([])
  }, [startNewChat])

  const handleLogout = useCallback(() => {
    logout()
    startNewChat()
    setMessages([])
  }, [logout, startNewChat])

  const runChatTurn = useCallback(
    async (text: string) => {
      if (!token) return
      const sessionId = currentSessionId
      lastUserQueryRef.current = text

      const controller = new AbortController()
      abortRef.current = controller
      setIsStreaming(true)
      setIsThinking(true)

      let hasStarted = false

      try {
        const done = await streamChat(
          token,
          sessionId,
          text,
          {
            onToken: (chunk) => {
              setIsThinking(false)
              if (!hasStarted) {
                hasStarted = true
                setMessages((prev) => [...prev, { role: 'assistant', content: chunk }])
                return
              }
              setMessages((prev) => {
                const next = [...prev]
                const last = next[next.length - 1]
                next[next.length - 1] = { ...last, content: last.content + chunk }
                return next
              })
            },
          },
          controller.signal,
        )

        if (done) {
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last?.role === 'assistant') {
              next[next.length - 1] = {
                ...last,
                content: last.content || done.answer,
                sources: done.sources,
                meta: { model: done.model, tokens: done.tokens, latency: done.latency },
              }
            } else {
              next.push({
                role: 'assistant',
                content: done.answer,
                sources: done.sources,
                meta: { model: done.model, tokens: done.tokens, latency: done.latency },
              })
            }
            return next
          })
        }
        refreshSessions().catch(() => {})
      } catch (error) {
        if (isAbortError(error)) {
          // User clicked Stop — keep whatever partial content already streamed in.
        } else if (error instanceof ApiError && error.status === 401) {
          logout()
        } else {
          const message = error instanceof Error ? error.message : String(error)
          setMessages((prev) => [...prev, { role: 'assistant', content: `*(couldn't reach the backend: ${message})*` }])
        }
      } finally {
        setIsStreaming(false)
        setIsThinking(false)
        abortRef.current = null
      }
    },
    [token, currentSessionId, logout, refreshSessions],
  )

  const handleSend = useCallback(
    async (text: string, files: File[]) => {
      if (!token) return
      const sessionId = currentSessionId

      let uploadError: string | null = null
      if (files.length > 0) {
        setUploadStatuses({})
        try {
          await uploadAndTrackDocuments(token, sessionId, files, setUploadStatuses)
        } catch (error) {
          uploadError = error instanceof Error ? error.message : String(error)
        }
      }

      const displayParts: string[] = []
      if (files.length > 0) {
        const names = files.map((file) => file.name).join(', ')
        displayParts.push(
          uploadError
            ? `📎 *Attached but failed to upload:* ${names}\n\n*Error: ${uploadError}*`
            : `📎 *Attached:* ${names}`,
        )
      }
      if (text) {
        displayParts.push(text)
      }
      const userContent = displayParts.length > 0 ? displayParts.join('\n\n') : '📎 Uploaded documents.'

      setMessages((prev) => [...prev, { role: 'user', content: userContent }])
      setUploadStatuses({})

      if (!text) {
        if (!uploadError) {
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', content: "Got it — ask me a question about that whenever you're ready." },
          ])
        }
        return
      }

      await runChatTurn(text)
    },
    [token, currentSessionId, runChatTurn],
  )

  const handleRegenerate = useCallback(() => {
    if (!lastUserQueryRef.current || isStreaming) return
    setMessages((prev) => {
      const lastAssistantIndex = [...prev].map((m) => m.role).lastIndexOf('assistant')
      if (lastAssistantIndex === -1) return prev
      return prev.slice(0, lastAssistantIndex)
    })
    runChatTurn(lastUserQueryRef.current)
  }, [isStreaming, runChatTurn])

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  return (
    <div className="flex h-screen bg-canvas">
      <Sidebar
        user={user}
        isAuthenticated={isAuthenticated}
        sessions={sessions}
        currentSessionId={currentSessionId}
        onLogin={login}
        onSignup={signup}
        onLogout={handleLogout}
        onNewChat={handleNewChat}
        onSwitchSession={setCurrentSessionId}
        mobileOpen={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-border px-4 py-3 md:px-6">
          <button
            type="button"
            onClick={() => setMobileSidebarOpen(true)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-muted hover:bg-surface-hover md:hidden"
            aria-label="Open sidebar"
          >
            ☰
          </button>
          <h1 className="font-serif text-lg font-semibold text-ink">{APP_NAME}</h1>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <ChatWindow
            isAuthenticated={isAuthenticated}
            messages={messages}
            isThinking={isThinking}
            onSuggestedPrompt={(prompt) => handleSend(prompt, [])}
            onRegenerate={handleRegenerate}
          />
        </div>
        {isAuthenticated && (
          <ChatInput isStreaming={isStreaming} uploadStatuses={uploadStatuses} onSubmit={handleSend} onStop={handleStop} />
        )}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <ChatApp />
      </AuthProvider>
    </ThemeProvider>
  )
}
