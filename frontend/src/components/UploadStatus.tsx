import { CheckCircle2, Clock, Loader2, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import type { IngestionStatusMap } from '../hooks/useDocumentUpload'

const ICONS: Record<string, ReactNode> = {
  queued: <Clock size={14} className="text-ink-faint" />,
  processing: <Loader2 size={14} className="animate-spin text-accent" />,
  ready: <CheckCircle2 size={14} className="text-emerald-600" />,
  failed: <XCircle size={14} className="text-red-600" />,
}

export function UploadStatus({ statuses }: { statuses: IngestionStatusMap }) {
  const entries = Object.entries(statuses)
  if (entries.length === 0) {
    return null
  }

  return (
    <div className="flex flex-col gap-1.5 rounded-2xl border border-border bg-surface-hover p-3 text-sm">
      {entries.map(([documentId, entry]) => (
        <div key={documentId} className="flex items-center gap-2">
          {ICONS[entry.status] ?? ICONS.queued}
          <span className="font-medium text-ink">{entry.filename}</span>
          <span className="text-ink-muted">
            {entry.status}
            {entry.status === 'failed' && entry.failure_reason ? `: ${entry.failure_reason.slice(0, 80)}` : ''}
          </span>
        </div>
      ))}
    </div>
  )
}
