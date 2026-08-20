import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { ArrowUp, FileSpreadsheet, FileText, Paperclip, Square, X } from 'lucide-react'
import type { IngestionStatusMap } from '../hooks/useDocumentUpload'
import { UploadStatus } from './UploadStatus'

const ACCEPTED_EXTENSIONS = '.pdf,.docx,.txt,.md,.csv'
const MAX_TEXTAREA_HEIGHT = 200

function FileTypeIcon({ filename }: { filename: string }) {
  const ext = filename.split('.').pop()?.toLowerCase() ?? ''
  if (ext === 'csv') return <FileSpreadsheet size={14} />
  return <FileText size={14} />
}

export function ChatInput({
  isStreaming,
  uploadStatuses,
  onSubmit,
  onStop,
}: {
  isStreaming: boolean
  uploadStatuses: IngestionStatusMap
  onSubmit: (text: string, files: File[]) => void
  onStop: () => void
}) {
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT)}px`
  }, [text])

  const canSubmit = !isStreaming && (text.trim().length > 0 || files.length > 0)

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!canSubmit) return
    onSubmit(text.trim(), files)
    setText('')
    setFiles([])
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleSubmit(event)
    }
  }

  function removeFile(index: number) {
    setFiles((prev) => prev.filter((_, i) => i !== index))
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 pb-4 lg:px-6">
      <form
        onSubmit={handleSubmit}
        className="flex flex-col gap-2 rounded-3xl border border-border bg-surface p-3 shadow-[0_2px_16px_rgba(0,0,0,0.06)]"
      >
        <UploadStatus statuses={uploadStatuses} />

        {files.length > 0 && (
          <div className="flex flex-wrap gap-2 px-1">
            {files.map((file, index) => (
              <span
                key={`${file.name}-${index}`}
                className="flex items-center gap-1.5 rounded-full bg-surface-hover px-3 py-1 text-xs text-ink-muted"
              >
                <FileTypeIcon filename={file.name} />
                {file.name}
                <button
                  type="button"
                  onClick={() => removeFile(index)}
                  className="ml-1 text-ink-faint hover:text-ink"
                  aria-label={`Remove ${file.name}`}
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isStreaming}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-ink-muted transition-colors hover:bg-surface-hover disabled:opacity-40"
            title="Attach documents"
          >
            <Paperclip size={18} strokeWidth={1.75} />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_EXTENSIONS}
            className="hidden"
            onChange={(event) => setFiles((prev) => [...prev, ...Array.from(event.target.files ?? [])])}
          />
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder="Ask a question, or attach documents..."
            className="max-h-[200px] flex-1 resize-none bg-transparent px-1 py-1.5 text-sm text-ink outline-none placeholder:text-ink-faint"
          />
          {isStreaming ? (
            <button
              type="button"
              onClick={onStop}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink text-canvas transition-opacity hover:opacity-80"
              title="Stop generating"
              aria-label="Stop generating"
            >
              <Square size={13} fill="currentColor" strokeWidth={0} />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!canSubmit}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-accent-ink transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="Send message"
            >
              <ArrowUp size={18} strokeWidth={2.25} />
            </button>
          )}
        </div>
      </form>
    </div>
  )
}
