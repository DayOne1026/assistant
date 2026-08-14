import { api } from './http'
import type { Page } from './chat'

export interface Preference {
  key: string
  value: unknown
  source?: string  // 后端 MemoryItem 只回 key/value，无 source
}

export interface Triple {
  subject: string
  predicate: string
  object: string
  confidence: number
}

export interface ToolLog {
  id: string
  tool_name: string
  level: string
  decision: string
  created_at: string
}

export const listPreferences = () => api<Preference[]>({ method: 'GET', url: '/memory/preferences' })

export const putPreference = (key: string, value: unknown) =>
  api<null>({ method: 'PUT', url: `/memory/preferences/${encodeURIComponent(key)}`, data: { value } })

export const queryMemory = (question: string) =>
  api<{ answer: string; sources: string[] }>({ method: 'POST', url: '/memory/query', data: { question } })

export const graphEntities = (name: string) =>
  api<Triple[]>({ method: 'GET', url: `/graph/entities/${encodeURIComponent(name)}` })

export const listToolLogs = (page = 1, pageSize = 50) =>
  api<Page<ToolLog>>({ method: 'GET', url: '/tool-logs', params: { page, page_size: pageSize } })
