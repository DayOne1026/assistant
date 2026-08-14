<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">assistant</div>
      <nav class="nav">
        <router-link
          v-for="n in navs"
          :key="n.to"
          :to="n.to"
          class="nav-item"
          active-class="active"
        >
          <el-icon><component :is="n.icon" /></el-icon>
          <span>{{ n.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar-foot">
        <span class="app-muted">{{ auth.user?.username || '' }}</span>
        <el-button link type="primary" @click="onLogout">退出</el-button>
      </div>
    </aside>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ChatDotRound,
  Picture,
  Calendar,
  Check,
  DataAnalysis,
  Setting,
} from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { getMe, logout } from '../api/auth'
import { connectWS, stopWS } from '../ws'

const auth = useAuthStore()
const router = useRouter()

const navs = [
  { to: '/chat', label: '对话', icon: ChatDotRound },
  { to: '/schedule', label: '日程', icon: Calendar },
  { to: '/todos', label: '任务', icon: Check },
  { to: '/memory', label: '记忆', icon: DataAnalysis },
  { to: '/images', label: '图片库', icon: Picture },
  { to: '/settings', label: '设置', icon: Setting },
]

function onWsMessage(data: Record<string, unknown>) {
  if (data.type === 'notification' || data.type === 'reminder') {
    ElMessage({ message: String(data.title || data.message || '新通知'), type: 'info' })
  }
}

async function onLogout() {
  await logout()
  stopWS()
  auth.logout()
  router.push('/login')
}

onMounted(async () => {
  try {
    auth.setUser(await getMe())
  } catch {
    /* 401 已由拦截器处理 */
  }
  connectWS(onWsMessage)
})

onUnmounted(stopWS)
</script>

<style scoped>
.layout {
  display: flex;
  height: 100%;
}
.sidebar {
  width: 200px;
  flex-shrink: 0;
  border-right: 1px solid var(--app-border);
  display: flex;
  flex-direction: column;
}
.brand {
  font-size: 18px;
  font-weight: 700;
  padding: 20px 20px 16px;
  letter-spacing: 0.5px;
}
.nav {
  flex: 1;
  padding: 4px 10px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  margin: 2px 0;
  border-radius: 8px;
  color: var(--app-text);
  text-decoration: none;
  border: 1px solid transparent;
}
.nav-item:hover {
  background: #f6f7f8;
}
.nav-item.active {
  border-color: var(--app-border);
  background: #fff;
  font-weight: 600;
  color: var(--app-accent);
}
.sidebar-foot {
  padding: 12px 16px;
  border-top: 1px solid var(--app-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.content {
  flex: 1;
  overflow-y: auto;
}
</style>
