import { api } from './http'

export interface Attachment {
  type: 'image' | 'file'
  image_id?: string
  url?: string
  thumbnail_url?: string
  filename?: string
}

export interface ChatReply {
  reply: string
  intent: { intent: string }
  tool_calls: string[]
  attachments: Attachment[]
  wait_ms?: number | null
}

export interface Conversation {
  id: string
  title: string
  created_at: string
}

export interface Message {
  id: string
  role: string
  content: string
  tool_name?: string | null
  attachments: Attachment[]
  created_at: string
  /** 前端本地字段：本轮回复等待耗时（毫秒），历史消息来自后端时为空 */
  wait_ms?: number
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export const listConversations = (page = 1, pageSize = 50) =>
  api<Page<Conversation>>({ method: 'GET', url: '/conversations', params: { page, page_size: pageSize } })

export const createConversation = (title?: string) =>
  api<Conversation>({ method: 'POST', url: '/conversations', data: { title } })

export const updateConversationTitle = (convId: string, title: string) =>
  api<Conversation>({ method: 'PATCH', url: `/conversations/${convId}`, data: { title } })

export const listMessages = (convId: string) =>
  api<Page<Message>>({
    method: 'GET',
    url: `/conversations/${convId}/messages`,
    params: { page: 1, page_size: 100 },
  })

export const sendMessage = (convId: string, content: string) =>
  api<ChatReply>({
    method: 'POST',
    url: `/conversations/${convId}/messages`,
    data: { conversation_id: convId, content },
  })

export function confirmTool(conversationId: string, callId?: string) {
  return api<{ status: string; data?: unknown; message?: string }>({
    method: 'POST',
    url: '/agent/tools/confirm',
    data: callId
      ? { call_id: callId, conversation_id: conversationId }
      : { confirm_latest: true, conversation_id: conversationId },
  })
}

export function denyTool(conversationId: string, callId?: string) {
  return api<{ status: string; message?: string }>({
    method: 'POST',
    url: '/agent/tools/deny',
    data: callId
      ? { call_id: callId, conversation_id: conversationId }
      : { deny_latest: true, conversation_id: conversationId },
  })
}
