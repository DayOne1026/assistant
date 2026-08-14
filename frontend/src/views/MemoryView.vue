<template>
  <div class="app-page">
    <h2 class="app-page__title">记忆与图谱</h2>
    <p class="app-muted">偏好 / 记忆问答 / 知识图谱 / 工具调用日志</p>

    <el-tabs v-model="tab">
      <el-tab-pane label="偏好" name="pref">
        <div class="add-row">
          <el-input v-model="prefKey" placeholder="键（如 location）" class="k" />
          <el-input v-model="prefValue" placeholder="值（如 上海）" class="v" />
          <el-button type="primary" @click="onAddPref">写入</el-button>
        </div>
        <el-table :data="prefs" size="small" border>
          <el-table-column prop="key" label="键" width="200" />
          <el-table-column label="值">
            <template #default="{ row }">{{ typeof row.value === 'object' ? JSON.stringify(row.value) : row.value }}</template>
          </el-table-column>
          <el-table-column prop="source" label="来源" width="100" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="记忆问答" name="query">
        <div class="add-row">
          <el-input v-model="question" placeholder="问记忆，如：我住在哪里" class="q" @keyup.enter="onQuery" />
          <el-button type="primary" @click="onQuery">提问</el-button>
        </div>
        <div v-if="answer" class="answer app-card">
          <div class="ans-text">{{ answer }}</div>
          <div v-if="sources.length" class="app-muted" style="margin-top: 8px">
            来源：{{ sources.join('、') }}
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="知识图谱" name="graph">
        <div class="add-row">
          <el-input v-model="entity" placeholder="输入实体名，如：上海" class="q" @keyup.enter="onGraph" />
          <el-button type="primary" @click="onGraph">展开</el-button>
        </div>
        <div ref="graphEl" class="graph" />
      </el-tab-pane>

      <el-tab-pane label="工具日志" name="logs">
        <ToolCallTimeline :logs="logs" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import ToolCallTimeline from '../components/ToolCallTimeline.vue'
import { errMsg } from '../api/http'
import { listPreferences, putPreference, queryMemory, graphEntities, listToolLogs } from '../api/memory'

const tab = ref('pref')
const prefs = ref<{ key: string; value: unknown; source?: string }[]>([])
const prefKey = ref('')
const prefValue = ref('')
const question = ref('')
const answer = ref('')
const sources = ref<string[]>([])
const entity = ref('')
const logs = ref<Awaited<ReturnType<typeof listToolLogs>>['items']>([])

const graphEl = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

async function loadPrefs() {
  prefs.value = await listPreferences()
}
async function onAddPref() {
  if (!prefKey.value.trim()) return
  try {
    await putPreference(prefKey.value.trim(), prefValue.value)
    prefKey.value = ''
    prefValue.value = ''
    loadPrefs()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
async function onQuery() {
  if (!question.value.trim()) return
  try {
    const r = await queryMemory(question.value.trim())
    answer.value = r.answer
    sources.value = r.sources
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
async function onGraph() {
  if (!entity.value.trim()) return
  try {
    const triples = await graphEntities(entity.value.trim())
    renderGraph(triples)
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
function renderGraph(triples: { subject: string; predicate: string; object: string; confidence: number }[]) {
  if (!graphEl.value) return
  if (!chart) chart = echarts.init(graphEl.value)
  const nodes = new Map<string, { name: string }>()
  const links: { source: string; target: string; label: { show: boolean; formatter: string } }[] = []
  for (const t of triples) {
    if (!nodes.has(t.subject)) nodes.set(t.subject, { name: t.subject })
    if (!nodes.has(t.object)) nodes.set(t.object, { name: t.object })
    links.push({ source: t.subject, target: t.object, label: { show: true, formatter: t.predicate } })
  }
  chart.setOption({
    tooltip: {},
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        data: [...nodes.values()],
        links,
        force: { repulsion: 200 },
        label: { show: true, color: '#1a1a1a' },
        lineStyle: { color: '#c8cdd4', width: 1 },
        itemStyle: { color: '#3b82f6' },
        emphasis: { focus: 'adjacency' },
      },
    ],
  })
}
function onResize() {
  chart?.resize()
}

onMounted(async () => {
  loadPrefs()
  try {
    logs.value = (await listToolLogs()).items
  } catch {
    /* 无日志不报错 */
  }
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.add-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  align-items: center;
}
.q,
.k {
  width: 240px;
}
.v {
  width: 240px;
}
.answer {
  margin-top: 8px;
}
.ans-text {
  white-space: pre-wrap;
}
.graph {
  height: 460px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
}
</style>
