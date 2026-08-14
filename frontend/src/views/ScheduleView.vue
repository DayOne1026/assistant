<template>
  <div class="app-page">
    <h2 class="app-page__title">日程</h2>
    <p class="app-muted">时间重叠会提醒但不阻止创建；删除走二次确认</p>

    <div class="add-card app-card">
      <el-input v-model="form.title" placeholder="日程标题" class="q" />
      <el-date-picker
        v-model="form.start_at"
        type="datetime"
        placeholder="开始时间"
        value-format="YYYY-MM-DDTHH:mm:ss"
      />
      <el-date-picker
        v-model="form.end_at"
        type="datetime"
        placeholder="结束时间（可选）"
        value-format="YYYY-MM-DDTHH:mm:ss"
      />
      <el-date-picker
        v-model="form.reminder_at"
        type="datetime"
        placeholder="提醒时间（可选）"
        value-format="YYYY-MM-DDTHH:mm:ss"
      />
      <el-button type="primary" @click="onAdd">添加</el-button>
    </div>

    <div v-if="!items.length" class="app-muted">暂无日程</div>
    <div v-else class="sch-list">
      <div v-for="s in items" :key="s.id" class="sch app-card app-card--flat">
        <div class="sch-main">
          <div class="sch-title">{{ s.title }}</div>
          <div class="app-muted">{{ fmt(s.start_at) }}{{ s.end_at ? ' → ' + fmt(s.end_at) : '' }}</div>
          <div v-if="s.reminder_at" class="app-muted">提醒：{{ fmt(s.reminder_at) }}</div>
        </div>
        <el-button link type="danger" size="small" @click="onDelete(s)">删除</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errMsg } from '../api/http'
import {
  listSchedules, createSchedule, requestDeleteSchedule, confirmDeleteSchedule, type Schedule,
} from '../api/schedule'

const items = ref<Schedule[]>([])
const form = reactive<{ title: string; start_at?: string; end_at?: string; reminder_at?: string }>({ title: '' })

async function load() {
  try {
    items.value = (await listSchedules()).items
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function onAdd() {
  if (!form.title.trim() || !form.start_at) {
    ElMessage.warning('标题和开始时间必填')
    return
  }
  try {
    await createSchedule({ title: form.title.trim(), start_at: form.start_at, end_at: form.end_at, reminder_at: form.reminder_at })
    ElMessage.success('已添加')
    form.title = ''
    form.start_at = form.end_at = form.reminder_at = undefined
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function onDelete(s: Schedule) {
  try {
    const { delete_token } = await requestDeleteSchedule(s.id)
    await ElMessageBox.confirm(`删除日程「${s.title}」？`, '二次确认', { type: 'warning' })
    await confirmDeleteSchedule(s.id, delete_token)
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
.add-card {
  display: flex;
  gap: 10px;
  align-items: center;
  margin: 16px 0;
  flex-wrap: wrap;
}
.q {
  width: 200px;
}
.sch-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
}
.sch-title {
  font-weight: 600;
}
</style>
