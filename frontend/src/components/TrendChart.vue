<template>
  <div class="adm-chart">
    <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" role="img" aria-label="调用趋势">
      <defs>
        <linearGradient :id="gid" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#2563eb" stop-opacity=".28" />
          <stop offset="100%" stop-color="#2563eb" stop-opacity="0" />
        </linearGradient>
      </defs>
      <g stroke="#eef2f7" stroke-width="1">
        <line x1="0" y1="20" :x2="W" y2="20" />
        <line x1="0" y1="60" :x2="W" y2="60" />
        <line x1="0" y1="100" :x2="W" y2="100" />
      </g>
      <path v-if="area" :d="area" :fill="`url(#${gid})`" />
      <path v-if="line" :d="line" fill="none" stroke="#2563eb" stroke-width="2.2" stroke-linecap="round" />
      <circle v-if="points.length" :cx="last.x" :cy="last.y" r="3.5" fill="#2563eb" />
      <g v-for="(p, i) in labels" :key="p.text">
        <text :x="p.x" :y="H - 4" text-anchor="middle" font-size="9" fill="#94a3b8">{{ p.text }}</text>
      </g>
    </svg>
    <div v-if="!points.length" class="adm-hint" style="padding:16px 0;text-align:center">暂无趋势数据</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  points: { type: Array, default: () => [] },
})
const W = 640
const H = 120
const gid = 'adm-trend-grad'

const scaled = computed(() => {
  const pts = props.points || []
  if (!pts.length) return []
  const max = Math.max(1, ...pts.map(p => Number(p.value) || 0))
  const step = pts.length > 1 ? W / (pts.length - 1) : W
  return pts.map((p, i) => ({
    x: Math.round(i * step),
    y: Math.round(100 - (Number(p.value) || 0) / max * 80),
    text: p.label || '',
    value: p.value,
  }))
})
const line = computed(() => scaled.value.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' '))
const area = computed(() => {
  if (!scaled.value.length) return ''
  const s = scaled.value
  return `${line.value} L${s[s.length - 1].x},${H} L${s[0].x},${H} Z`
})
const last = computed(() => scaled.value[scaled.value.length - 1] || { x: 0, y: 0 })
const labels = computed(() => {
  const s = scaled.value
  if (!s.length) return []
  const step = Math.max(1, Math.ceil(s.length / 7))
  return s.filter((_, i) => i % step === 0 || i === s.length - 1)
})
</script>
