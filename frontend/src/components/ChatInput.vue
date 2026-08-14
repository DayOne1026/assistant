<template>
  <div class="chat-input">
    <el-input
      v-model="text"
      type="textarea"
      :rows="3"
      :placeholder="placeholder"
      resize="none"
      @keydown.enter.exact.prevent="onSend"
    />
    <div class="chat-input__foot">
      <span class="app-muted">Enter 发送，Shift+Enter 换行</span>
      <el-button type="primary" :loading="loading" :disabled="!text.trim()" @click="onSend">
        发送
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ loading: boolean; placeholder?: string }>()
const emit = defineEmits<{ (e: 'send', text: string): void }>()

const text = ref('')

function onSend() {
  const v = text.value.trim()
  if (!v) return
  emit('send', v)
  text.value = ''
}
</script>

<style scoped>
.chat-input {
  border-top: 1px solid var(--app-border);
  padding: 12px 16px;
  background: #fff;
}
.chat-input__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}
</style>
