import { api } from './http'
import type { Page } from './chat'

export interface Prompt {
  id: string
  name: string
  prompt: string
  enabled: boolean
}

export const listPrompts = () => api<Page<Prompt>>({ method: 'GET', url: '/prompts' })

export const createPrompt = (name: string, prompt: string) =>
  api<Prompt>({ method: 'POST', url: '/prompts', data: { name, prompt } })

export const enablePrompt = (id: string, enabled: boolean) =>
  api<null>({ method: 'POST', url: `/prompts/${id}/enable`, data: { enabled } })

export const requestDeletePrompt = (id: string) =>
  api<{ delete_token: string }>({ method: 'DELETE', url: `/prompts/${id}` })

export const confirmDeletePrompt = (id: string, token: string) =>
  api<null>({ method: 'POST', url: `/prompts/${id}/confirm`, data: { delete_token: token } })
