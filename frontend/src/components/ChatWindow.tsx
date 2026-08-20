import { useEffect, useRef } from 'react'
import { MessageSquare } from 'lucide-react'
import type { ChatMessage } from '../lib/types'
import { AssistantAvatar, MessageBubble } from './MessageBubble'
import { TypingIndicator } from './TypingIndicator'

const SUGGESTED_PROMPTS = [
  'Summarize the key points of my uploaded document',
  'What questions should I ask about this material?',
  'Explain this topic like I’m new to it',
  'Find any risks or open issues mentioned in my files',
]

function LoggedOutState() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 text-center">
      <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-2xl bg-accent-soft text-accent">
        <MessageSquare size={20} strokeWidth={1.75} />
      </div>
      <h2 className="mb-2 font-serif text-lg font-semibold">Ask anything about your documents</h2>
      <p className="max-w-sm text-sm text-ink-muted">
        Log in or create an account on the left to start a conversation. Your chat history will show up here.
      </p>
    </div>
  )
}

function EmptySessionState({ onSuggestedPrompt }: { onSuggestedPrompt: (text: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 text-center">
      <h2 className="mb-6 font-serif text-2xl font-semibold text-ink">Where should we begin?</h2>
      <div className="grid w-full max-w-xl grid-cols-1 gap-2 sm:grid-cols-2">
        {SUGGESTED_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            type="button"
            onClick={() => onSuggestedPrompt(prompt)}
            className="rounded-xl border border-border bg-surface px-4 py-3 text-left text-sm text-ink-muted transition-colors hover:border-accent hover:text-ink"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  )
}

export function ChatWindow({
  isAuthenticated,
  messages,
  isThinking,
  onSuggestedPrompt,
  onRegenerate,
}: {
  isAuthenticated: boolean
  messages: ChatMessage[]
  isThinking: boolean
  onSuggestedPrompt: (text: string) => void
  onRegenerate: () => void
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isThinking])

  if (!isAuthenticated) {
    return <LoggedOutState />
  }

  if (messages.length === 0) {
    return <EmptySessionState onSuggestedPrompt={onSuggestedPrompt} />
  }

  const lastAssistantIndex = [...messages].map((m) => m.role).lastIndexOf('assistant')

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-7 px-4 py-6 lg:px-6">
      {messages.map((message, index) => (
        <MessageBubble
          key={index}
          message={message}
          isLatestAssistant={index === lastAssistantIndex}
          onRegenerate={onRegenerate}
        />
      ))}
      {isThinking && (
        <div className="flex gap-3">
          <AssistantAvatar />
          <TypingIndicator />
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}
