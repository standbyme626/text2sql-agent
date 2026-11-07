<template>
  <div class="schema-panel">
    <div class="schema-head">
      <button class="drawer-close" aria-label="关闭表结构" @click="$emit('close')">×</button>
      <h3>表结构浏览 · {{ tables.length }} 张表</h3>
      <input class="schema-search" v-model="q" placeholder="搜索表名 / 中文名 / 业务域" />
    </div>
    <div class="schema-list">
      <div class="schema-row" v-for="t in filtered" :key="t.name">
        <button class="row-head" type="button" :aria-expanded="open === t.name"
                @click="toggle(t.name)" @keydown.enter.space.prevent="toggle(t.name)">
          <span class="tname">{{ t.name }}</span>
          <span class="tcn">{{ t.cn }}</span>
          <span class="domain">{{ t.domain }} · {{ t.rows }} 行</span>
        </button>
        <div class="schema-detail" v-if="open === t.name">
          <div class="kv" v-if="detail.keywords"><b>检索关键词：</b>{{ detail.keywords }}</div>
          <div class="kv" v-if="colsText"><b>字段：</b>{{ colsText }}</div>
          <pre>{{ detail.ddl }}</pre>
          <div class="kv" v-if="enumText"><b>枚举值：</b>{{ enumText }}</div>
          <div class="kv" v-if="detail.sample && detail.sample.rows && detail.sample.rows.length">
            <b>样例：</b>{{ JSON.stringify(detail.sample.rows[0]) }}
          </div>
          <div class="kv" v-if="loading">加载中…</div>
        </div>
      </div>
      <div class="empty" v-if="!filtered.length">没有匹配的表</div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'

const props = defineProps({ tables: { type: Array, default: () => [] } })
defineEmits(['close'])
const q = ref('')
const open = ref('')
const loading = ref(false)
const detail = ref({})
let reqSeq = 0        // 快速点 A→B 时，慢返回的 A 不能覆盖 B

const filtered = computed(() => {
  const s = q.value.trim().toLowerCase()
  if (!s) return props.tables
  return props.tables.filter(t =>
    [t.name, t.cn, t.domain, t.keywords].join(' ').toLowerCase().includes(s))
})
const colsText = computed(() => {
  const cs = detail.value.columns || []
  return cs.slice(0, 8).map(c => `${c.name}(${c.cn})`).join('、') + (cs.length > 8 ? ' …' : '')
})
const enumText = computed(() => {
  const e = detail.value.enums || {}
  return Object.entries(e).slice(0, 4).map(([k, v]) => `${k}: ${v.slice(0, 6).join('/')}`).join('；')
})

async function toggle(name) {
  if (open.value === name) { open.value = ''; return }
  const seq = ++reqSeq
  open.value = name
  detail.value = {}
  loading.value = true
  try {
    const d = await api.table(name)
    if (seq === reqSeq) detail.value = d
  } catch (e) {
    if (seq === reqSeq) detail.value = { ddl: `加载失败：${e.message}` }
  } finally {
    if (seq === reqSeq) loading.value = false
  }
}
</script>
