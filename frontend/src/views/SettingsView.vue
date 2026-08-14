<template>
  <div class="app-page">
    <h2 class="app-page__title">设置 · 自定义人设</h2>
    <p class="app-muted">System Prompt 配置，启用的 prompt 会拼入对话系统提示</p>

    <div class="add-card app-card">
      <el-input v-model="form.name" placeholder="人设名（如：专业翻译）" class="n" />
      <el-input v-model="form.prompt" type="textarea" :rows="2" placeholder="人设描述…" />
      <el-button type="primary" @click="onAdd">添加</el-button>
    </div>

    <div v-if="!items.length" class="app-muted">暂无人设</div>
    <div v-else class="list">
      <div v-for="p in items" :key="p.id" class="item app-card app-card--flat">
        <div class="item-main">
          <div class="item-name">{{ p.name }}</div>
          <div class="app-muted item-prompt">{{ p.prompt }}</div>
        </div>
        <div class="item-actions">
          <el-switch :model-value="p.enabled" @change="(v: boolean | string | number) => onEnable(p, !!v)" />
          <el-button link type="danger" size="small" @click="onDelete(p)">删除</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errMsg } from '../api/http'
import {
  listPrompts, createPrompt, enablePrompt, requestDeletePrompt, confirmDeletePrompt, type Prompt,
} from '../api/prompts'

const items = ref<Prompt[]>([])
const form = reactive({ name: '', prompt: '' })

async function load() {
  try {
    items.value = (await listPrompts()).items
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function onAdd() {
  if (!form.name.trim() || !form.prompt.trim()) {
    ElMessage.warning('名称和内容必填')
    return
  }
  try {
    await createPrompt(form.name.trim(), form.prompt.trim())
    ElMessage.success('已添加')
    form.name = ''
    form.prompt = ''
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function onEnable(p: Prompt, enabled: boolean) {
  try {
    await enablePrompt(p.id, enabled)
    p.enabled = enabled
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function onDelete(p: Prompt) {
  try {
    const { delete_token } = await requestDeletePrompt(p.id)
    await ElMessageBox.confirm(`删除人设「${p.name}」？`, '二次确认', { type: 'warning' })
    await confirmDeletePrompt(p.id, delete_token)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(errMsg(e))
  }
}

onMounted(load)
</script>

<style scoped>
.add-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 16px 0;
}
.n {
  width: 240px;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
}
.item-name {
  font-weight: 600;
}
.item-prompt {
  margin-top: 2px;
  max-width: 560px;
}
.item-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
</style>
