<script setup>
import { computed } from 'vue'
import { formatDuration } from '../../lib/grades.js'

const props = defineProps({ telemetry: { type: Object, default: null } })
const t = computed(() => props.telemetry || {})
const latency = computed(() => {
  if (t.value.average_latency_ms == null) return { value: '—', note: 'No completed scans yet', tone: 'muted' }
  const seconds = (t.value.average_latency_ms / 1000).toFixed(2)
  return { value: `${seconds} s`, note: t.value.latency_within_target ? 'Within < 2 s target' : 'Above 2 s target', tone: t.value.latency_within_target ? 'ok' : 'bad' }
})
const temperature = computed(() => {
  if (t.value.cpu_temperature_c == null) return { value: '—', tone: 'muted' }
  const c = t.value.cpu_temperature_c
  return { value: `${c.toFixed(1)} °C`, tone: c < 70 ? 'ok' : c < 80 ? 'warn' : 'bad' }
})
const fan = computed(() => {
  const f = t.value.fan
  if (!f) return 'Active cooler not reported'
  return f.active ? `Active cooler running · level ${f.level}/${f.max_level ?? '?'}` : 'Active cooler idle'
})
</script>

<template>
  <div class="panel">
    <p class="eyebrow">Operational summary</p>
    <h2>Edge device telemetry</h2>
    <div class="telemetry-grid">
      <div><span>Service uptime</span><strong>{{ formatDuration(t.service_uptime_s) }}</strong><small>Device up {{ formatDuration(t.system_uptime_s) }}</small></div>
      <div><span>CPU temperature</span><strong :class="temperature.tone">{{ temperature.value }}</strong><small>{{ fan }}</small></div>
      <div><span>Avg. inference latency</span><strong :class="latency.tone">{{ latency.value }}</strong><small>{{ latency.note }} · last 50 scans</small></div>
      <div><span>SQLite database</span><strong :class="t.database_connected ? 'ok' : 'bad'">{{ t.database_connected ? 'Connected' : telemetry ? 'Unreachable' : '—' }}</strong><small>{{ t.database || 'banagrade.db' }}</small></div>
    </div>
  </div>
</template>
