import { useState } from 'react'
import { Check, Copy, RefreshCw, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { CodeBlock } from './CodeBlock'
import type { ChatMessage } from '../lib/types'

function formatLatency(latency: number | null): string {
  return typeof latency === 'number' ? `${latency.toFixed(2)}s` : 'n/a'
}

export function AssistantAvatar() {
  return (
    <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent text-accent-ink">
      <Sparkles size={14} strokeWidth={2} />
    </div>
  )
}

function SourceChips({ sources }: { sources: NonNullable<ChatMessage['sources']> }) {
  if (sources.length === 0) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {sources.map((source) => (
        <span
          key={`${source.citation}-${source.filename}-${source.page}`}
          className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface px-2 py-1 text-xs text-ink-muted"
        >
          <span className="font-semibold text-accent">[{source.citation}]</span>
          <span className="max-w-[16rem] truncate">{source.filename}</span>
          {source.page !== null && <span className="text-ink-faint">· p.{source.page}</span>}
        </span>
      ))}
    </div>
  )
}

function AssistantActions({ content, onRegenerate }: { content: string; onRegenerate?: () => void }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard API unavailable — nothing to fall back to.
    }
  }

  return (
    <div className="mt-1.5 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
      <button
        type="button"
        onClick={handleCopy}
        className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-ink-faint hover:bg-surface-hover hover:text-ink"
      >
        {copied ? <Check size={13} /> : <Copy size={13} />}
        {copied ? 'Copied' : 'Copy'}
      </button>
      {onRegenerate && (
        <button
          type="button"
          onClick={onRegenerate}
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-ink-faint hover:bg-surface-hover hover:text-ink"
        >
          <RefreshCw size={13} />
          Regenerate
        </button>
      )}
    </div>
  )
}

export function MessageBubble({
  message,
  isLatestAssistant,
  onRegenerate,
}: {
  message: ChatMessage
  isLatestAssistant?: boolean
  onRegenerate?: () => void
}) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="message-in flex justify-end">
        <div className="max-w-[75%] rounded-2xl bg-accent px-4 py-2.5 text-sm leading-relaxed text-accent-ink">
          <div className="markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content || ' '}</ReactMarkdown>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="message-in group flex gap-3">
      <AssistantAvatar />
      <div className="min-w-0 flex-1">
        <div className="markdown text-ink">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code: CodeBlock,
            }}
          >
            {message.content || ' '}
          </ReactMarkdown>
        </div>
        {message.sources && <SourceChips sources={message.sources} />}
        {message.meta && (
          <p className="mt-1.5 font-mono text-[0.7rem] text-ink-faint">
            {message.meta.model} · {message.meta.tokens ?? 'n/a'} tokens · {formatLatency(message.meta.latency)}
          </p>
        )}
        {message.content && (
          <AssistantActions content={message.content} onRegenerate={isLatestAssistant ? onRegenerate : undefined} />
        )}
      </div>
    </div>
  )
}
