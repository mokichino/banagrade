<script setup>
import { computed, onMounted, ref } from 'vue'
import { BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, Tooltip } from 'chart.js'
import { Bar, Doughnut } from 'vue-chartjs'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend)
const props = defineProps({ apiBase: { type: String, required: true } })
const summary = ref({})
const loading = ref(true)
const error = ref('')
const gradeChart = computed(() => ({ labels: ['Class A', 'Class B', 'Rejected', 'Technical'], datasets: [{ data: [summary.value.class_a_count || 0, summary.value.class_b_count || 0, summary.value.rejected_count || 0, summary.value.technical_failure_count || 0], backgroundColor: ['#F4C542', '#3B82F6', '#EF4444', '#9CA3AF'], borderWidth: 0 }] }))
const latencyChart = computed(() => ({ labels: ['Average latency'], datasets: [{ label: 'Milliseconds', data: [summary.value.average_inference_latency_ms || 0], backgroundColor: '#111827' }] }))
const chartOptions = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }

async function load() {
  try {
    const response = await fetch(`${props.apiBase}/api/analytics/summary`)
    if (!response.ok) throw new Error('Analytics are unavailable')
    summary.value = await response.json()
  } catch (loadError) { error.value = loadError.message } finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <section class="content-grid analytics-view">
    <div v-if="error" class="alert">{{ error }}</div>
    <div v-if="loading" class="loading">Loading analytics...</div>
    <template v-else>
      <div class="chart-grid">
        <div class="panel chart-panel"><div class="panel-heading"><div><p class="eyebrow">YIELD DISTRIBUTION</p><h2>Completed grades</h2></div></div><div class="chart-area"><Doughnut :data="gradeChart" :options="chartOptions" /></div></div>
        <div class="panel chart-panel"><div class="panel-heading"><div><p class="eyebrow">LATENCY PROFILE</p><h2>Average processing time</h2></div></div><div class="chart-area"><Bar :data="latencyChart" :options="chartOptions" /></div></div>
      </div>
      <div class="panel"><p class="eyebrow">OPERATIONAL SUMMARY</p><div class="analytics-stats"><div><strong>{{ summary.total_completed_scans || 0 }}</strong><span>Completed scans</span></div><div><strong>{{ summary.export_acceptance_rate || 0 }}%</strong><span>Acceptance rate</span></div><div><strong>{{ summary.rejection_rate || 0 }}%</strong><span>Commercial rejection rate</span></div><div><strong>{{ summary.technical_failure_count || 0 }}</strong><span>Technical failures</span></div></div></div>
    </template>
  </section>
</template>