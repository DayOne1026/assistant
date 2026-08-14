import { useAuthStore } from './stores/auth'

// WebSocket 连接管理：/api/v1/ws?token=，断线指数退避重连（13 蓝图）
let ws: WebSocket | null = null
let retries = 0
let stopped = false

export function connectWS(onMessage: (data: Record<string, unknown>) => void) {
  const auth = useAuthStore()
  if (!auth.token || stopped) return
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/api/v1/ws?token=${auth.token}`)
  ws.onopen = () => {
    retries = 0
  }
  ws.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data))
    } catch {
      /* 忽略非 JSON */
    }
  }
  ws.onclose = () => {
    if (stopped) return
    const delay = Math.min(1000 * 2 ** retries, 30000)
    retries += 1
    setTimeout(() => connectWS(onMessage), delay)
  }
}

export function stopWS() {
  stopped = true
  ws?.close()
  ws = null
}
