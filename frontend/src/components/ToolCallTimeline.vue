<template>
  <div>
    <div v-if="!logs.length" class="app-muted">暂无工具调用记录</div>
    <el-table v-else :data="logs" size="small" border>
      <el-table-column prop="tool_name" label="工具" min-width="140" />
      <el-table-column label="等级" width="120">
        <template #default="{ row }">
          <el-tag size="small" :type="levelTag(row.level)">{{ row.level }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="决策" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="decisionTag(row.decision)">{{ row.decision }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="时间" width="160">
        <template #default="{ row }">{{ fmt(row.created_at) }}</template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import type { ToolLog } from '../api/memory'

defineProps<{ logs: ToolLog[] }>()

function fmt(v: string) {
  return new Date(v).toLocaleString('zh-CN')
}
function levelTag(level: string) {
  if (level === 'read_only') return 'info'
  if (level === 'send_delete') return 'danger'
  return 'warning'
}
function decisionTag(d: string) {
  if (d === 'approved') return 'success'
  if (d === 'denied') return 'danger'
  return 'info'
}
</script>
