<template>
  <div class="chat">
    <aside class="conv-list">
      <el-button class="new-btn" type="primary" plain @click="newConv">＋ 新对话</el-button>
      <div class="conv-items">
        <div
          v-for="c in convs"
          :key="c.id"
          class="conv-item"
          :class="{ active: c.id === current }"
          :title="c.title"
          @click="select(c.id)"
          @dblclick="onRename(c)"
        >
          {{ c.title }}
        </div>
        <div class="app-muted rename-hint">双击会话可改名</div>
      </div>
    </aside>
    <div class="chat-main">
      <template v-if="current">
        <div class="msg-scroll" ref="scrollEl">
          <MessageList
            :messages="messages"
            :waiting="loading"
            :wait-ms="waitingMs"
            @confirm="sendConfirm"
          />
        </div>
        <ChatInput :loading="loading" @send="send" />
      </template>
      <div v-else class="chat-empty app-muted">选择左侧会话，或点「新对话」开始</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MessageList from '../components/MessageList.vue'
import ChatInput from '../components/ChatInput.vue'
import { errMsg } from '../api/http'
import {
  listConversations, createConversation, updateConversationTitle, listMessages, sendMessage,
  type Message, type Attachment,
} from '../api/chat'

const convs = ref<{ id: string; title: string }[]>([])
const current = ref('')
const messages = ref<Message[]>([])
const loading = ref(false)
const waitingMs = ref(0)
const scrollEl = ref<HTMLElement>()
let timer: ReturnType<typeof setInterval> | null = null
let startTs = 0
let seq = 0

// 新消息/等待态变化 → 自动滚到最新（nextTick 等 DOM 更新后）
watch([messages, loading], () => nextTick(scrollToBottom))

function scrollToBottom() {
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}

async function loadConvs() {
  try {
    convs.value = (await listConversations()).items
    if (!current.value && convs.value.length) await select(convs.value[0].id)
    else if (!convs.value.length) await newConv()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function newConv() {
  try {
    const c = await createConversation() // 后端 title 可选，默认"新对话"
    convs.value.unshift(c)
    await select(c.id)
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function onRename(c: { id: string; title: string }) {
  try {
    const { value } = await ElMessageBox.prompt('修改对话名称', '重命名', {
      inputValue: c.title,
      inputPlaceholder: '对话名称',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    if (!value || !value.trim() || value.trim() === c.title) return
    const updated = await updateConversationTitle(c.id, value.trim())
    const item = convs.value.find((x) => x.id === c.id)
    if (item) item.title = updated.title
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(errMsg(e))
  }
}

async function select(id: string) {
  current.value = id
  try {
    messages.value = (await listMessages(id)).items
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

function pushLocal(role: 'user' | 'assistant', content: string, attachments: Attachment[] = [], waitMs?: number) {
  messages.value.push({
    id: `local-${seq++}`,
    role,
    content,
    attachments,
    created_at: new Date().toISOString(),
    wait_ms: waitMs,
  })
}

function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

async function send(text: string) {
  if (!current.value || loading.value) return
  pushLocal('user', text)
  loading.value = true
  waitingMs.value = 0
  startTs = Date.now()
  timer = setInterval(() => {
    waitingMs.value = Date.now() - startTs
  }, 100)
  try {
    const r = await sendMessage(current.value, text)
    // wait_ms 优先用服务端记录（graph 处理耗时），兼容旧后端回退本地实测
    const waitMs = r.wait_ms ?? Date.now() - startTs
    pushLocal('assistant', r.reply, r.attachments || [], waitMs)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    stopTimer()
    loading.value = false
  }
}

function sendConfirm() {
  if (!loading.value) send('确认')
}

onMounted(loadConvs)
onUnmounted(stopTimer)
</script>

<style scoped>
.chat {
  display: flex;
  height: 100%;
}
.conv-list {
  width: 200px;
  flex-shrink: 0;
  border-right: 1px solid var(--app-border);
  display: flex;
  flex-direction: column;
}
.new-btn {
  margin: 12px;
}
.conv-items {
  flex: 1;
  overflow-y: auto;
  padding: 0 10px 10px;
}
.conv-item {
  padding: 9px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 1px solid transparent;
}
.conv-item:hover {
  background: #f6f7f8;
}
.conv-item.active {
  border-color: var(--app-border);
  font-weight: 600;
}
.rename-hint {
  padding: 6px 12px 0;
}
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.msg-scroll {
  flex: 1;
  overflow-y: auto;
}
.chat-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
