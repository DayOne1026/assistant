import axios, { type AxiosRequestConfig } from 'axios'

export interface ApiResponse<T = unknown> {
  code: string
  data: T
  message: string
}

// baseURL /api/v1：dev 走 vite proxy（同源），生产 Nginx 反代
const http = axios.create({ baseURL: '/api/v1', timeout: 60000 })

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 401 → /auth/refresh 换新 → 重试一次；refresh 失败清 token 跳登录（13 鉴权流程）
let refreshing: Promise<string> | null = null

http.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    const { response, config } = error
    if (response?.status === 401 && !config._retry) {
      config._retry = true
      try {
        const rt = localStorage.getItem('refresh_token')
        if (!rt) throw new Error('no refresh token')
        refreshing =
          refreshing ||
          axios
            .post('/api/v1/auth/refresh', { refresh_token: rt })
            .then((r) => {
              const d = r.data.data
              localStorage.setItem('access_token', d.access_token)
              localStorage.setItem('refresh_token', d.refresh_token)
              return d.access_token as string
            })
            .finally(() => {
              refreshing = null
            })
        const token = await refreshing
        config.headers.Authorization = `Bearer ${token}`
        return http(config)
      } catch {
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        if (!window.location.pathname.startsWith('/login')) {
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(error)
  },
)

/** 发请求并解包统一响应 {code,data,message}；code != 0 抛错。 */
export async function api<T>(config: AxiosRequestConfig): Promise<T> {
  const resp = await http.request<ApiResponse<T>>(config)
  const body = resp.data
  if (body.code !== '0') throw new Error(body.message || '请求失败')
  return body.data
}

/** 错误信息提取（后端 message 或网络错误）。 */
export function errMsg(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const msg = (e.response?.data as ApiResponse | undefined)?.message
    return msg || e.message
  }
  return e instanceof Error ? e.message : String(e)
}

export default http
