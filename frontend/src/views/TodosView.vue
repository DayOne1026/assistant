<template>
  <div class="app-page">
    <h2 class="app-page__title">任务</h2>
    <p class="app-muted">勾选完成，超期提醒由后端调度</p>

    <div class="add-row">
      <el-input v-model="title" placeholder="新任务" class="q" @keyup.enter="onAdd" />
      <el-date-picker
        v-model="dueAt"
        type="datetime"
        placeholder="截止时间（可选）"
        value-format="YYYY-MM-DDTHH:mm:ss"
      />
      <el-button type="primary" @click="onAdd">添加</el-button>
    </div>

    <div v-if="!items.length" class="app-muted">暂无任务</div>
    <div v-else class="todo-list">
      <div v-for="t in items" :key="t.id" class="todo app-card app-card--flat">
        <el-checkbox :model-value="t.completed" @change="(v: boolean | string | number) => onToggle(t, !!v)">
          <span :class="{ done: t.completed }">{{ t.title }}</span>
        </el-checkbox>
        <div class="todo-right">
          <span v-if="t.due_at" class="app-muted">{{ fmt(t.due_at) }}</span>
          <el-button link type="danger" size="small" @click="onDelete(t)">删除</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errMsg } from '../api/http'
import {
  listTodos, createTodo, toggleTodo, requestDeleteTodo, confirmDeleteTodo, type Todo,
} from '../api/todos'

const items = ref<Todo[]>([])
const title = ref('')
const dueAt = ref<string>()

async function load() {
  try {
    items.value = (await listTodos()).items
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function onAdd() {
  if (!title.value.trim()) return
  try {
    await createTodo({ title: title.value.trim(), due_at: dueAt.value })
    ElMessage.success('已添加')
    title.value = ''
    dueAt.value = undefined
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function onToggle(t: Todo, completed: boolean) {
  try {
    await toggleTodo(t.id, completed)
    t.completed = completed
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function onDelete(t: Todo) {
  try {
    const { delete_token } = await requestDeleteTodo(t.id)
    await ElMessageBox.confirm(`删除任务「${t.title}」？`, '二次确认', { type: 'warning' })
    await confirmDeleteTodo(t.id, delete_token)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(errMsg(e))
  }
}

function fmt(v: string) {
  return new Date(v).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

onMounted(load)
</script>

<style scoped>
.add-row {
  display: flex;
  gap: 10px;
  margin: 16px 0;
}
.q {
  flex: 1;
  max-width: 360px;
}
.todo-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.todo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
}
.done {
  text-decoration: line-through;
  color: var(--app-text-secondary);
}
.todo-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
</style>
