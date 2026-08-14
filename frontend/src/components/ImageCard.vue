<template>
  <div class="img-card app-card">
    <img :src="item.url" class="img" loading="lazy" alt="" />
    <div class="meta">
      <span class="app-muted name" :title="item.filename">{{ item.filename }}</span>
      <el-button link type="danger" size="small" @click="$emit('delete', item)">删除</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ImageItem } from '../api/images'

defineProps<{ item: ImageItem }>()
defineEmits<{ (e: 'delete', item: ImageItem): void }>()
</script>

<style scoped>
.img-card {
  padding: 8px;
}
.img {
  width: 100%;
  height: 160px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--app-border);
}
.meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
}
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 8px;
}
</style>
