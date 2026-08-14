import { api } from './http'
import type { User } from '../stores/auth'

export interface TokenResponse {
  access_token: string
  refresh_token: string
  expires_in: number
}

export function login(email: string, password: string) {
  return api<TokenResponse>({ method: 'POST', url: '/auth/login', data: { email, password } })
}

export function register(data: { email: string; username: string; password: string }) {
  return api<User>({ method: 'POST', url: '/auth/register', data })
}

export function getMe() {
  return api<User>({ method: 'GET', url: '/users/me' })
}

export function logout() {
  return api<null>({ method: 'POST', url: '/auth/logout' }).catch(() => null)
}
