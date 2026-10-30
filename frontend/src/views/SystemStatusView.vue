<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { request } from '../composables/useApi.js'
import CameraCard from '../components/status/CameraCard.vue'
import LedPanelCard from '../components/status/LedPanelCard.vue'
import HardwareStatusCard from '../components/status/HardwareStatusCard.vue'
import ModelsCard from '../components/status/ModelsCard.vue'
import OperationalSummaryCard from '../components/status/OperationalSummaryCard.vue'
import DriftCard from '../components/status/DriftCard.vue'
import PowerCard from '../components/status/PowerCard.vue'

defineProps({ led: { type: String, default: 'offline' } })
const emit = defineEmits(['error'])
const status = ref(null)
const telemetry = ref(null)
const drift = ref(null)
let timer

async function load() {
  try {
    const [statusData, telemetryData, driftData] = await Promise.all([request('/api/system/status'), request('/api/system/telemetry'), request('/api/system/drift')])
    status.value = statusData
    telemetry.value = telemetryData
    drift.value = driftData
  } catch (error) {
    status.value = null
    telemetry.value = null
    drift.value = null
    emit('error', `System status unavailable: ${error.message}`)
  }
}

onMounted(() => { load(); timer = window.setInterval(load, 5000) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <section class="content-grid status-stack">
    <CameraCard :pipeline="status?.pipeline">
      <template #below-preview>
        <LedPanelCard embedded :led="led" :led-status="status?.pipeline?.led" />
      </template>
    </CameraCard>
    <OperationalSummaryCard :telemetry="telemetry" />
    <HardwareStatusCard :pipeline="status?.pipeline" :models="status?.models" :telemetry="telemetry" :clock="status?.clock" />
    <ModelsCard :models="status?.models" />
    <DriftCard :drift="drift" />
    <PowerCard :power="status?.power" />
  </section>
</template>
