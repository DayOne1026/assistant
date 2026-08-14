<template>
  <div class="login">
    <div class="login-card app-card">
      <h1 class="login-title">assistant</h1>
      <p class="app-muted">多用户 AI 私人助理</p>
      <el-tabs v-model="tab" stretch>
        <el-tab-pane label="登录" name="login">
          <el-form @submit.prevent="onLogin" label-position="top">
            <el-form-item label="邮箱">
              <el-input v-model="loginForm.email" placeholder="you@example.com" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="loginForm.password" type="password" show-password @keyup.enter="onLogin" />
            </el-form-item>
            <el-button type="primary" class="w-full" :loading="loading" @click="onLogin">登录</el-button>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="注册" name="register">
          <el-form @submit.prevent="onRegister" label-position="top">
            <el-form-item label="邮箱">
              <el-input v-model="regForm.email" placeholder="you@example.com" />
            </el-form-item>
            <el-form-item label="用户名">
              <el-input v-model="regForm.username" placeholder="3-50 位字母数字下划线" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="regForm.password" type="password" show-password />
            </el-form-item>
            <el-button type="primary" class="w-full" :loading="loading" @click="onRegister">注册</el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login, register } from '../api/auth'
import { errMsg } from '../api/http'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const tab = ref('login')
const loading = ref(false)
const loginForm = reactive({ email: '', password: '' })
const regForm = reactive({ email: '', username: '', password: '' })

async function onLogin() {
  loading.value = true
  try {
    const t = await login(loginForm.email, loginForm.password)
    auth.setAuth(t.access_token, t.refresh_token)
    router.push('/chat')
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

async function onRegister() {
  loading.value = true
  try {
    await register({ ...regForm })
    ElMessage.success('注册成功，请登录')
    tab.value = 'login'
    loginForm.email = regForm.email
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fafafa;
}
.login-card {
  width: 360px;
  padding: 32px;
}
.login-title {
  margin: 0 0 4px;
  font-size: 24px;
  font-weight: 700;
  text-align: center;
}
.login-card p {
  text-align: center;
  margin: 0 0 20px;
}
.w-full {
  width: 100%;
  margin-top: 4px;
}
</style>
