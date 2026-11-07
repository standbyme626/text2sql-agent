<template>
  <div class="sql-block">
    <div class="sql-head">
      <span class="tag">生成的 SQL</span>
      <span class="attempt badge" v-if="attempt > 1">第 {{ attempt }} 次生成</span>
      <div class="spacer"></div>
      <button @click="copy">{{ copied || '复制' }}</button>
      <button @click="toggle">{{ editing ? '取消' : '编辑' }}</button>
      <button v-if="editing" class="primary" @click="rerun">重跑</button>
    </div>
    <textarea v-if="editing" v-model="draft" rows="6" spellcheck="false"></textarea>
    <pre v-else><code>{{ sql }}</code></pre>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({ sql: String, attempt: { type: Number, default: 1 } })
const emit = defineEmits(['rerun'])
const editing = ref(false)
const draft = ref(props.sql || '')
const copied = ref('')
watch(() => props.sql, v => { if (!editing.value) draft.value = v || '' })

function toggle() {
  editing.value = !editing.value
  if (editing.value) draft.value = props.sql || ''
}
async function copy() {
  const text = props.sql || ''
  const fallback = () => {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    copied.value = ok ? '已复制' : '复制失败'
  }
  try {
    if (!navigator.clipboard?.writeText) return fallback()
    await navigator.clipboard.writeText(text)
    copied.value = '已复制'
  } catch (_) { fallback() }
  setTimeout(() => { copied.value = '' }, 1800)
}
function rerun() {
  editing.value = false      // 退出编辑态，让 <pre> 显示真正执行的 SQL
  emit('rerun', draft.value)
}
</script>
