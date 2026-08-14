<template>
  <div class="app-page">
    <h2 class="app-page__title">图片库</h2>
    <p class="app-muted">CLIP 多模态检索：文字搜图 / 图片搜图 / 图查图</p>

    <div class="tools">
      <el-input v-model="query" placeholder="输入描述搜图（如：日落、猫）" class="q" clearable @keyup.enter="onTextSearch">
        <template #append>
          <el-button @click="onTextSearch">文字搜图</el-button>
        </template>
      </el-input>
      <el-upload :show-file-list="false" :http-request="onImageSearch" accept="image/*">
        <el-button>上传图片搜相似</el-button>
      </el-upload>
    </div>

    <div class="upload-wrap">
      <ImageUploader @uploaded="load" />
    </div>

    <div v-if="loading" class="app-muted">加载中…</div>
    <div v-else-if="!items.length" class="app-muted">暂无图片</div>
    <div v-else class="grid">
      <ImageCard v-for="it in items" :key="it.id" :item="it" @delete="onDelete" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ImageCard from '../components/ImageCard.vue'
import ImageUploader from '../components/ImageUploader.vue'
import { errMsg } from '../api/http'
import { listImages, searchImages, requestDeleteImage, confirmDeleteImage, type ImageItem } from '../api/images'

const items = ref<ImageItem[]>([])
const query = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    items.value = (await listImages()).items
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

async function onTextSearch() {
  if (!query.value.trim()) return
  loading.value = true
  try {
    items.value = await searchImages(undefined, query.value.trim())
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

async function onImageSearch(options: { file: File }) {
  loading.value = true
  try {
    items.value = await searchImages(options.file)
    ElMessage.success('相似图片检索完成')
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

async function onDelete(item: ImageItem) {
  try {
    const { delete_token } = await requestDeleteImage(item.id)
    await ElMessageBox.confirm(`删除图片「${item.filename}」？`, '二次确认', { type: 'warning' })
    await confirmDeleteImage(item.id, delete_token)
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
.tools {
  display: flex;
  gap: 12px;
  margin: 16px 0;
  align-items: center;
}
.q {
  width: 360px;
}
.upload-wrap {
  margin-bottom: 20px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 14px;
}
</style>
