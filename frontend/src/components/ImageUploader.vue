<template>
  <el-upload
    drag
    multiple
    :show-file-list="false"
    :http-request="doUpload"
    accept="image/*"
  >
    <el-icon class="up-icon"><Plus /></el-icon>
    <div class="el-upload__text">拖拽图片到此处，或<em>点击上传</em></div>
  </el-upload>
</template>

<script setup lang="ts">
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { uploadImage } from '../api/images'
import { errMsg } from '../api/http'

const emit = defineEmits<{ (e: 'uploaded'): void }>()

async function doUpload(options: { file: File }) {
  try {
    await uploadImage(options.file)
    ElMessage.success('上传成功')
    emit('uploaded')
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
</script>

<style scoped>
.up-icon {
  font-size: 32px;
  color: var(--app-text-secondary);
  margin: 8px 0;
}
</style>
