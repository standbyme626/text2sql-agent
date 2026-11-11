<template>
  <div>
    <div class="result-head">
      <span class="stat">返回 <b>{{ result.row_count ?? 0 }}</b> 行，耗时 {{ result.elapsed_ms ?? 0 }} ms</span>
      <span class="stat" v-if="result.truncated">（已按上限截断，非全量）</span>
      <div class="spacer"></div>
      <button v-if="chart && chartPoints.length" @click="showChart = !showChart">
        {{ showChart ? '收起图表' : '查看图表' }}</button>
      <button @click="exportCsv">导出 CSV</button>
      <button @click="explain" :disabled="explaining">
        {{ explaining ? '解读中…' : (insight && !insight.fallback ? '重新解读' : 'AI 解读') }}
      </button>
    </div>

    <div v-if="insight && insight.summary" class="insight-box">
      <div class="insight-label"><span class="insight-dot"></span>{{ insight.fallback ? '数据摘要（AI 暂不可用）' : '结论' }}</div>
      <div class="insight-text">{{ insight.summary }}</div>
      <div class="followups" v-if="insight.followups && insight.followups.length">
        <span class="followups-label">继续追问</span>
        <button v-for="(q, i) in insight.followups" :key="i" class="followup-chip"
                @click="$emit('followup', q)">{{ q }}</button>
      </div>
    </div>

    <div v-if="chart && chartPoints.length === 0" class="hint">该结果没有可用于绘图的数值列。</div>
    <div v-if="chart && chartPoints.length && showChart" class="chart-box">
      <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="xMidYMid meet">
        <line :x1="pad" :y1="zeroY" :x2="W - 12" :y2="zeroY" stroke="#cbd5e1" stroke-width="1" />
        <line :x1="pad" :y1="12" :x2="pad" :y2="H - 28" stroke="#cbd5e1" stroke-width="1" />
        <template v-if="chart.type === 'bar'">
          <g v-for="(p, i) in points" :key="'b' + i">
            <rect :x="p.x" :y="Math.min(zeroY, p.y)" :width="barW"
                  :height="Math.max(1, Math.abs(zeroY - p.y))"
                  :fill="p.value < 0 ? '#ef4444' : '#0e9384'" rx="2" />
            <text v-if="i % labelStep === 0" :x="p.x + barW / 2" :y="H - 12"
                  text-anchor="middle" font-size="9" fill="#64748b">{{ p.label }}</text>
          </g>
        </template>
        <template v-else>
          <polyline :points="points.map(p => `${p.x + barW / 2},${p.y}`).join(' ')"
                    fill="none" stroke="#0e9384" stroke-width="2.2" />
          <g v-for="(p, i) in points" :key="'l' + i">
            <circle :cx="p.x + barW / 2" :cy="p.y" r="2.6" fill="#0e9384" />
            <text v-if="i % labelStep === 0" :x="p.x + barW / 2" :y="H - 12"
                  text-anchor="middle" font-size="9" fill="#64748b">{{ p.label }}</text>
          </g>
        </template>
        <text :x="pad" :y="10" font-size="10" fill="#94a3b8">{{ chart.y }}（{{ minVal }} ~ {{ maxVal }}）</text>
      </svg>
    </div>

    <div class="table-wrap" v-if="(result.rows || []).length">
      <table>
        <thead><tr><th v-for="c in result.columns" :key="c">{{ c }}</th></tr></thead>
        <tbody>
          <tr v-for="(row, i) in shownRows" :key="i">
            <td v-for="(v, j) in row" :key="j" :class="{ num: typeof v === 'number' }"
                :title="String(v ?? '')">{{ formatCell(v) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty">查询成功，但没有返回数据</div>
    <div v-if="shownRows.length < (result.rows || []).length" class="hint">
      表格仅显示前 {{ shownRows.length }} 行，可用「导出 CSV」获取全部。
    </div>

    <div v-if="error" class="err">{{ error }}</div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'

const props = defineProps({
  result: { type: Object, required: true },
  question: { type: String, default: '' },
  insight: { type: Object, default: null },
})
const emit = defineEmits(['followup', 'refresh-insight'])
const showChart = ref(true)
const explaining = ref(false)
const error = ref('')
const narrow = ref(typeof window !== 'undefined' && window.innerWidth < 860)
const onResize = () => { narrow.value = window.innerWidth < 860 }
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

const W = computed(() => narrow.value ? 360 : 660)
const H = 220
const pad = computed(() => narrow.value ? 26 : 46)
const MAX_TABLE_ROWS = 200

const chart = computed(() => props.result.chart || null)
const shownRows = computed(() => (props.result.rows || []).slice(0, MAX_TABLE_ROWS))
const chartPoints = computed(() => {
  const c = chart.value
  if (!c) return []
  const xi = (props.result.columns || []).indexOf(c.x)
  const yi = (props.result.columns || []).indexOf(c.y)
  if (xi < 0 || yi < 0) return []
  const maxPts = narrow.value ? 8 : (c.max_points || 30)
  return (props.result.rows || [])
    .filter(r => typeof r[yi] === 'number' && Number.isFinite(r[yi]))
    .slice(0, maxPts)
    .map(r => ({ label: String(r[xi] ?? '').slice(0, narrow.value ? 5 : 10), value: Number(r[yi]) }))
    .reverse()
})
const maxVal = computed(() => chartPoints.value.length
  ? Math.max(0, ...chartPoints.value.map(p => p.value)) : 0)
const minVal = computed(() => chartPoints.value.length
  ? Math.min(0, ...chartPoints.value.map(p => p.value)) : 0)
// 零值基线：负值向下画而不是被裁到轴外
const zeroY = computed(() => {
  const span = (maxVal.value - minVal.value) || 1
  return 14 + (maxVal.value / span) * (H - 48)
})
const points = computed(() => {
  const ps = chartPoints.value
  if (!ps.length) return []
  const span = (maxVal.value - minVal.value) || 1
  const slot = (W.value - pad.value - 16) / ps.length
  const bw = Math.max(3, Math.min(38, slot * 0.62))
  return ps.map((p, i) => ({
    ...p,
    x: pad.value + i * slot + (slot - bw) / 2,
    y: 14 + ((maxVal.value - p.value) / span) * (H - 48),
  }))
})
const barW = computed(() => {
  const ps = chartPoints.value
  if (!ps.length) return 10
  const slot = (W.value - pad.value - 16) / ps.length
  return Math.max(3, Math.min(38, slot * 0.62))
})
const labelStep = computed(() =>
  Math.max(1, Math.ceil(points.value.length / (narrow.value ? 5 : 10))))

function formatCell(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (typeof v === 'number') {
    if (Number.isInteger(v) && Math.abs(v) >= 1e15) return String(v)
    return v.toLocaleString('zh-CN', { maximumFractionDigits: 6 })
  }
  return String(v)
}

function exportCsv() {
  const esc = v => {
    let s = v === null || v === undefined ? '' : String(v)
    // CSV 公式注入防护（纯负数不处理，避免破坏数值）
    if (/^[=+@\t\r]/.test(s) || (/^-/.test(s) && !/^-?\d+(\.\d+)?$/.test(s))) s = "'" + s
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [(props.result.columns || []).map(esc).join(','),
    ...(props.result.rows || []).map(r => r.map(esc).join(','))]
  const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'query_result.csv'
  document.body.appendChild(a)
  a.click()
  setTimeout(() => { URL.revokeObjectURL(url); a.remove() }, 0)
}

async function explain() {
  error.value = ''
  explaining.value = true
  try {
    const d = await api.explain({
      question: props.question, sql: props.result.sql,
      columns: props.result.columns, rows: (props.result.rows || []).slice(0, 8),
      truncated: !!props.result.truncated,
    })
    const summary = d.summary || d.text || ''
    emit('refresh-insight', { summary, text: summary, followups: d.followups || [] })
  } catch (e) { error.value = e.message }
  finally { explaining.value = false }
}
</script>
