import { api } from './http'
import type { Page } from './chat'

export interface Schedule {
  id: string
  title: string
  description?: string | null
  start_at: string
  end_at?: string | null
  reminder_at?: string | null
  status: string
  created_at: string
}

export interface ScheduleInput {
  title: string
  description?: string
  start_at: string
  end_at?: string
  reminder_at?: string
}

export const listSchedules = (page = 1, pageSize = 100) =>
  api<Page<Schedule>>({ method: 'GET', url: '/schedules', params: { page, page_size: pageSize } })

export const createSchedule = (data: ScheduleInput) =>
  api<Schedule>({ method: 'POST', url: '/schedules', data })

export const updateSchedule = (id: string, data: Partial<ScheduleInput>) =>
  api<Schedule>({ method: 'PATCH', url: `/schedules/${id}`, data })

export const requestDeleteSchedule = (id: string) =>
  api<{ delete_token: string }>({ method: 'DELETE', url: `/schedules/${id}` })

export const confirmDeleteSchedule = (id: string, token: string) =>
  api<null>({ method: 'POST', url: `/schedules/${id}/confirm`, data: { delete_token: token } })
