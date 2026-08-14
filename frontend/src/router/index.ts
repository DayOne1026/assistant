import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
    {
      path: '/',
      component: () => import('../layouts/DefaultLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        { path: '', redirect: '/chat' },
        { path: 'chat', name: 'chat', component: () => import('../views/ChatView.vue') },
        { path: 'images', name: 'images', component: () => import('../views/ImagesView.vue') },
        { path: 'schedule', name: 'schedule', component: () => import('../views/ScheduleView.vue') },
        { path: 'todos', name: 'todos', component: () => import('../views/TodosView.vue') },
        { path: 'memory', name: 'memory', component: () => import('../views/MemoryView.vue') },
        { path: 'settings', name: 'settings', component: () => import('../views/SettingsView.vue') },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.token) return { name: 'login' }
  if (to.name === 'login' && auth.token) return { name: 'chat' }
})

export default router
