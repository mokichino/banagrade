<script setup>
import { computed } from 'vue'
import { formatTimestamp } from '../../lib/grades.js'

const props = defineProps({ pipeline: { type: Object, default: null }, models: { type: Object, default: null }, telemetry: { type: Object, default: null }, clock: { type: Object, default: null } })

// Shifts change over by date, so a wrong clock matters. With no internet and no RTC battery, the Pi takes the time from
// a phone that opens the dashboard.
function clockRow(clock) {
  const name = 'Clock'
  if (!clock) return { name, detail: 'Not reported', status: 'Unavailable', ok: false }
  if (!clock.trusted) return { name, detail: 'Reads earlier than scans already recorded · connect to the internet or check the RTC battery', status: 'Wrong date', ok: false }
  if (clock.synchronized === false && clock.set_by_dashboard_at) return { name, detail: `No internet · set from a dashboard's time at ${formatTimestamp(clock.set_by_dashboard_at)}`, status: 'Phone time', ok: true }
  if (clock.synchronized === false) return { name, detail: 'No internet time since boot · opening the dashboard on a phone sets it', status: 'Not synced', ok: null }
  return { name, detail: clock.synchronized ? 'Set from internet time' : 'Device clock', status: 'OK', ok: true }
}

const rows = computed(() => {
  const p = props.pipeline
  const led = p?.led
  const pipelineOk = props.models?.available && p && !['ERROR', 'DISABLED', 'BOOTING'].includes(p.state)
  return [
    { name: 'Raspberry Pi 5', detail: props.telemetry?.device_model || 'Edge device', status: props.telemetry ? 'Online' : 'Unreachable', ok: !!props.telemetry },
    { name: 'Camera Module', detail: 'Camera Module 3 · IMX708', status: p?.camera?.available ? 'Online' : 'Unavailable', ok: !!p?.camera?.available },
    { name: 'AI Pipeline', detail: props.models?.available ? 'Stage 1 + Stage 2 loaded' : 'Models not loaded', status: p?.state || 'Unavailable', ok: !!pipelineOk },
    led?.mode === 'software'
      ? { name: 'GPIO LEDs', detail: 'Not connected yet · simulated under the camera preview', status: 'Software only', ok: null }
      : { name: 'GPIO LEDs', detail: led?.hardware_available ? `Pins G${led.pins.green} Y${led.pins.yellow} B${led.pins.blue} R${led.pins.red}` : led?.error || 'Not initialised', status: led?.hardware_available ? 'Ready' : 'Unavailable', ok: !!led?.hardware_available },
    clockRow(props.clock)
  ]
})
</script>

<template>
  <div class="panel">
    <p class="eyebrow">Hardware status</p>
    <h2>Connected components</h2>
    <ul class="diagnostic-list">
      <li v-for="row in rows" :key="row.name" class="diagnostic-row">
        <span class="diagnostic-name"><i :class="['status-dot', row.ok === null ? '' : row.ok ? 'online' : 'offline']" aria-hidden="true"></i><span><b>{{ row.name }}</b><small>{{ row.detail }}</small></span></span>
        <span :class="['status-badge', row.ok === null ? 'neutral' : row.ok ? 'loaded' : 'missing']">{{ row.status }}</span>
      </li>
    </ul>
  </div>
</template>
