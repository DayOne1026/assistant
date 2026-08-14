<template>
  <div class="msg-list">
    <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
      <div class="bubble">
        <div v-for="a in m.attachments" :key="a.url || a.image_id" class="attach">
          <img v-if="a.type === 'image'" :src="a.url" class="attach-img" loading="lazy" />
          <a v-else :href="a.url" target="_blank">{{ a.filename || '附件' }}</a>
        </div>
        <div class="msg-text" :class="{ 'has-attach': m.attachments.length }">{{ m.content }}</div>
        <div v-if="m.role === 'assistant' && isPending(m.content)" class="confirm-row">
          <el-button size="small" type="primary" @click="$emit('confirm')">执行该操作</el-button>
        </div>
        <div v-if="m.role === 'assistant' && m.wait_ms != null" class="app-muted wait-time">
          本次回复用时 {{ (m.wait_ms / 1000).toFixed(1) }}s
        </div>
      </div>
    </div>
    <!-- 等待中：spinner + 累加计时 -->
    <div v-if="waiting" class="msg assistant">
      <div class="bubble bubble-waiting">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span class="app-muted">思考中… {{ (waitMs / 1000).toFixed(1) }}s</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Loading } from '@element-plus/icons-vue'
import type { Message } from '../api/chat'

defineProps<{ messages: Message[]; waiting: boolean; waitMs: number }>()
defineEmits<{ (e: 'confirm'): void }>()

function isPending(content: string): boolean {
  return content.includes('待确认')
}
</script>

<style scoped>
.msg-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px 24px;
}
.msg {
  display: flex;
}
.msg.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 72%;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  padding: 10px 14px;
  background: #fff;
}
.msg.user .bubble {
  background: #f2f5fb;
  border-color: #e2e9f7;
}
.msg-text {
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-text.has-attach {
  margin-top: 8px;
}
.attach-img {
  max-width: 260px;
  border-radius: 8px;
  border: 1px solid var(--app-border);
  display: block;
}
.confirm-row {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--app-border);
}
.bubble-waiting {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--app-text-secondary);
  min-width: 120px;
}
.wait-time {
  margin-top: 6px;
  text-align: right;
}
</style>
