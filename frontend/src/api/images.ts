import { api } from './http'
import type { Page } from './chat'

export interface ImageItem {
  id: string
  url: string
  thumbnail_url?: string | null
  filename: string
  content_type: string
  size: number
  created_at: string
}

export const listImages = (page = 1, pageSize = 24) =>
  api<Page<ImageItem>>({ method: 'GET', url: '/images', params: { page, page_size: pageSize } })

export const uploadImage = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api<ImageItem>({ method: 'POST', url: '/images', data: form })
}

export function searchImages(file?: File, queryText?: string) {
  const form = new FormData()
  if (file) form.append('file', file)
  if (queryText) form.append('query_text', queryText)
  return api<ImageItem[]>({ method: 'POST', url: '/images/search', data: form })
}

export const requestDeleteImage = (id: string) =>
  api<{ delete_token: string }>({ method: 'DELETE', url: `/images/${id}` })

export const confirmDeleteImage = (id: string, token: string) =>
  api<null>({ method: 'POST', url: `/images/${id}/confirm`, data: { delete_token: token } })
