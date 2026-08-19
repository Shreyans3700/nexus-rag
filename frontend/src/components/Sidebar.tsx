import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { LogOut, PanelLeftClose, PanelLeftOpen, Plus, Search, X } from 'lucide-react'
import { ApiError } from '../lib/api'
import type { SessionMeta, User } from '../lib/types'
import { ThemeToggle } from './ThemeToggle'

type Tab = 'login' | 'signup'
const COLLAPSED_KEY = 'sidebar_collapsed'
const WIDTH_KEY = 'sidebar_width'
const COLLAPSED_WIDTH = 64
const DEFAULT_WIDTH = 272
const MIN_WIDTH = 220
const MAX_WIDTH = 440

function AuthForms({
  onLogin,
  onSignup,
}: {
  onLogin: (email: string, password: string) => Promise<void>
  onSignup: (email: string, password: string) => Promise<void>
}) {
  const [tab, setTab] = useState<Tab>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (tab === 'login') {
        await onLogin(email, password)
      } else {
        await onSignup(email, password)
      }
      setEmail('')
      setPassword('')
    } catch (err) {
      if (tab === 'signup' && err instanceof ApiError && err.status === 409) {
        setError("That email's already registered. Log in instead.")
      } else {
        setError(err instanceof Error ? err.message : String(err))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="mb-3 flex gap-1 rounded-full bg-panel p-1 text-sm">
        {(['login', 'signup'] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => {
              setTab(value)
              setError(null)
            }}
            className={`flex-1 rounded-full py-1.5 font-medium transition-colors ${
              tab === value ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted'
            }`}
          >
            {value === 'login' ? 'Log in' : 'Sign up'}
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-2">
        <input
          type="email"
          required
          placeholder="name@company.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="rounded-xl border border-border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
        />
        <input
          type="password"
          required
          minLength={8}
          placeholder={tab === 'signup' ? 'At least 8 characters' : '••••••••'}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="rounded-xl border border-border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
        />
        {error && <p className="text-xs text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-50"
        >
          {tab === 'login' ? 'Log in' : 'Create account'}
        </button>
      </form>
    </div>
  )
}

export function Sidebar({
  user,
  isAuthenticated,
  sessions,
  currentSessionId,
  onLogin,
  onSignup,
  onLogout,
  onNewChat,
  onSwitchSession,
  mobileOpen,
  onCloseMobile,
}: {
  user: User | null
  isAuthenticated: boolean
  sessions: SessionMeta[]
  currentSessionId: string
  onLogin: (email: string, password: string) => Promise<void>
  onSignup: (email: string, password: string) => Promise<void>
  onLogout: () => void
  onNewChat: () => void
  onSwitchSession: (sessionId: string) => void
  mobileOpen: boolean
  onCloseMobile: () => void
}) {
  const [collapsedPref, setCollapsedPref] = useState(() => localStorage.getItem(COLLAPSED_KEY) === '1')
  const [query, setQuery] = useState('')
  const [width, setWidth] = useState(() => {
    const stored = Number(localStorage.getItem(WIDTH_KEY))
    return stored >= MIN_WIDTH && stored <= MAX_WIDTH ? stored : DEFAULT_WIDTH
  })
  const [isResizing, setIsResizing] = useState(false)
  // Never collapse before login — the auth form must stay reachable.
  const collapsed = collapsedPref && isAuthenticated

  function toggleCollapsed() {
    setCollapsedPref((prev) => {
      const next = !prev
      localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0')
      return next
    })
  }

  useEffect(() => {
    if (!isResizing) return

    function handleMouseMove(event: MouseEvent) {
      const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, event.clientX))
      setWidth(next)
    }
    function handleMouseUp() {
      setIsResizing(false)
    }

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing])

  useEffect(() => {
    localStorage.setItem(WIDTH_KEY, String(width))
  }, [width])

  const filteredSessions = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return sessions
    return sessions.filter((s) => (s.title || '').toLowerCase().includes(q))
  }, [sessions, query])

  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/30 md:hidden"
          onClick={onCloseMobile}
          aria-hidden="true"
        />
      )}
      <aside
        style={{ width: collapsed ? COLLAPSED_WIDTH : width }}
        className={`fixed inset-y-0 left-0 z-30 flex shrink-0 flex-col bg-panel p-3 md:static md:translate-x-0 ${
          isResizing ? '' : 'transition-[width,transform] duration-200'
        } ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}`}
      >
        {!collapsed && (
          <div
            onMouseDown={(event) => {
              event.preventDefault()
              setIsResizing(true)
            }}
            className="absolute inset-y-0 right-0 hidden w-1.5 cursor-col-resize hover:bg-accent/40 md:block"
            title="Drag to resize"
          />
        )}
        <div className="mb-2 flex items-center justify-between">
          {!collapsed && <span className="px-1 font-serif text-sm font-semibold text-ink">Corpus</span>}
          <button
            type="button"
            onClick={toggleCollapsed}
            className="hidden h-8 w-8 items-center justify-center rounded-lg text-ink-muted hover:bg-surface-hover md:flex"
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
          <button
            type="button"
            onClick={onCloseMobile}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-muted hover:bg-surface-hover md:hidden"
          >
            <X size={16} />
          </button>
        </div>

        <button
          type="button"
          onClick={onNewChat}
          disabled={!isAuthenticated}
          className={`mb-3 flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-sm font-medium text-ink transition-colors hover:border-accent hover:text-accent disabled:opacity-50 ${
            collapsed ? 'justify-center' : ''
          }`}
          title="New chat"
        >
          <Plus size={16} />
          {!collapsed && <span>New chat</span>}
        </button>

        {!collapsed && (
          <div className="flex min-h-0 flex-1 flex-col">
            {isAuthenticated && sessions.length > 0 && (
              <div className="relative mb-2">
                <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint" />
                <input
                  type="search"
                  placeholder="Search chats..."
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  className="w-full rounded-lg border border-border bg-surface py-1.5 pl-8 pr-3 text-xs text-ink outline-none focus:border-accent"
                />
              </div>
            )}
            <h3 className="mb-1 px-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">Chats</h3>

            {!isAuthenticated ? (
              <p className="px-1 text-xs text-ink-muted">Log in to see your past conversations here.</p>
            ) : filteredSessions.length === 0 ? (
              <p className="px-1 text-xs text-ink-muted">
                {sessions.length === 0 ? 'No saved chats yet. Send a message to start one.' : 'No chats match your search.'}
              </p>
            ) : (
              <div className="flex flex-col gap-0.5 overflow-y-auto">
                {filteredSessions.map((session) => {
                  const isCurrent = session.session_id === currentSessionId
                  const title = session.title?.trim() || `Chat ${session.session_id.slice(0, 8)}`
                  return (
                    <button
                      key={session.session_id}
                      type="button"
                      onClick={() => {
                        onSwitchSession(session.session_id)
                        onCloseMobile()
                      }}
                      className={`truncate rounded-lg border-l-2 px-2.5 py-2 text-left text-sm transition-colors ${
                        isCurrent
                          ? 'border-accent bg-surface-hover font-medium text-ink'
                          : 'border-transparent text-ink-muted hover:bg-surface-hover hover:text-ink'
                      }`}
                    >
                      {title}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )}

        <div className="mt-auto pt-3">
          {!collapsed && <hr className="mb-3 border-border" />}
          {isAuthenticated ? (
            <div className={`flex items-center gap-2 ${collapsed ? 'flex-col' : 'justify-between'}`}>
              {!collapsed && (
                <span className="truncate text-xs text-ink-muted" title={user?.email}>
                  {user?.email ?? 'unknown'}
                </span>
              )}
              {!collapsed && <ThemeToggle />}
              <button
                type="button"
                onClick={onLogout}
                className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-ink-muted hover:bg-surface-hover hover:text-ink"
                title="Log out"
              >
                <LogOut size={13} />
                {!collapsed && 'Log out'}
              </button>
            </div>
          ) : (
            !collapsed && <AuthForms onLogin={onLogin} onSignup={onSignup} />
          )}
        </div>
      </aside>
    </>
  )
}
