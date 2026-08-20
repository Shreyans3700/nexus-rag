import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { SessionMeta } from '../lib/types'

const SESSION_KEY = 'current_session_id'

function newSessionId(): string {
  return crypto.randomUUID()
}

export function useSessions(token: string | null) {
  const [sessions, setSessions] = useState<SessionMeta[]>([])
  const [currentSessionId, setCurrentSessionIdState] = useState<string>(
    () => localStorage.getItem(SESSION_KEY) || newSessionId(),
  )

  const setCurrentSessionId = useCallback((id: string) => {
    localStorage.setItem(SESSION_KEY, id)
    setCurrentSessionIdState(id)
  }, [])

  const refresh = useCallback(async () => {
    if (!token) {
      setSessions([])
      return
    }
    const data = await api.getSessions(token)
    setSessions(data)
  }, [token])

  const startNewChat = useCallback(() => {
    const id = newSessionId()
    setCurrentSessionId(id)
    return id
  }, [setCurrentSessionId])

  useEffect(() => {
    refresh().catch(() => {
      setSessions([])
    })
  }, [refresh])

  return { sessions, currentSessionId, setCurrentSessionId, startNewChat, refreshSessions: refresh }
}
