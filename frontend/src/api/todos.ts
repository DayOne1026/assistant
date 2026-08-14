import { api } from './http'
import type { Page } from './chat'

export interface Todo {
  id: string
  title: string
  description?: string | null
  due_at?: string | null
  completed: boolean
  completed_at?: string | null
  created_at: string
}

export const listTodos = (page = 1, pageSize = 100) =>
  api<Page<Todo>>({ method: 'GET', url: '/todos', params: { page, page_size: pageSize } })

export const createTodo = (data: { title: string; description?: string; due_at?: string }) =>
  api<Todo>({ method: 'POST', url: '/todos', data })

export const updateTodo = (id: string, data: Partial<{ title: string; description?: string; due_at?: string }>) =>
  api<Todo>({ method: 'PATCH', url: `/todos/${id}`, data })

export const toggleTodo = (id: string, completed: boolean) =>
  api<Todo>({ method: 'POST', url: `/todos/${id}/toggle`, data: { completed } })

export const requestDeleteTodo = (id: string) =>
  api<{ delete_token: string }>({ method: 'DELETE', url: `/todos/${id}` })

export const confirmDeleteTodo = (id: string, token: string) =>
  api<null>({ method: 'POST', url: `/todos/${id}/confirm`, data: { delete_token: token } })
