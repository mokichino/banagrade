<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ArcElement, CategoryScale, Chart as ChartJS, DoughnutController, Filler, LineElement, LinearScale, PointElement, Tooltip } from 'chart.js'
import { Doughnut, Line } from 'vue-chartjs'
import { request } from '../composables/useApi.js'
import { formatTimestamp } from '../lib/grades.js'
import ScanTable from '../components/ScanTable.vue'

ChartJS.register(ArcElement, CategoryScale, DoughnutController, Filler, LineElement, LinearScale, PointElement, Tooltip)

const props = defineProps({ refreshKey: { type: Number, default: 0 } })
const emit = defineEmits(['navigate', 'dispute', 'select', 'error'])

const COLORS = { a: '#D9A300', b: '#2563EB', r: '#DC2626' }
const scope = ref('active')
const bucketMinutes = ref(15)
const summary = ref({})
const trend = ref([])
const session = ref(null)
const recent = ref([])
const loading = ref(true)
const shiftBusy = ref(false)

const scopeQuery = computed(() => (scope.value === 'active' ? '?session=active' : ''))
const accepted = computed(() => (summary.value.class_a_count || 0) + (summary.value.class_b_count || 0))
const sharePct = n => (accepted.value ? Math.round((n / accepted.value) * 1000) / 10 : 0)

const yieldChart = computed(() => ({
  labels: ['Class A', 'Class B'],
  datasets: [{
    data: [summary.value.class_a_count || 0, summary.value.class_b_count || 0],
    backgroundColor: [COLORS.a, COLORS.b],
    borderColor: '#ffffff',
    borderWidth: 2,
    hoverOffset: 4
  }]
}))
const yieldOptions = {
  responsive: true,
  maintainAspectRatio: false,
  cutout: '68%',
  plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed} (${sharePct(ctx.parsed)}%)` } } }
}

function bucketLabel(iso) {
  const date = new Date(iso)
  const sameDay = new Date().toDateString() === date.toDateString()
  return date.toLocaleString(undefined, sameDay ? { hour: '2-digit', minute: '2-digit', hour12: false } : { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
}
const trendChart = computed(() => ({
  labels: trend.value.map(item => bucketLabel(item.bucket_start)),
  datasets: [{
    label: 'Rejection rate',
    data: trend.value.map(item => item.rejection_rate),
    borderColor: COLORS.r,
    backgroundColor: 'rgba(220, 38, 38, .10)',
    borderWidth: 2,
    pointRadius: 4,
    pointHoverRadius: 6,
    pointBackgroundColor: COLORS.r,
    pointBorderColor: '#ffffff',
    pointBorderWidth: 2,
    fill: true,
    tension: 0.25
  }]
}))
const trendOptions = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { display: false },
    tooltip: { callbacks: { label: ctx => { const item = trend.value[ctx.dataIndex]; return ` ${ctx.parsed.y}% rejected (${item.rejected} of ${item.total})` } } }
  },
  scales: {
    x: { grid: { display: false }, ticks: { color: '#6b7280', maxRotation: 0, autoSkip: true } },
    y: { beginAtZero: true, max: 100, grid: { color: '#f0f1f3' }, border: { display: false }, ticks: { color: '#6b7280', callback: value => `${value}%` } }
  }
}

async function load() {
  try {
    const [summaryData, trendData, sessionData, scanData] = await Promise.all([
      request(`/api/analytics/summary${scopeQuery.value}`),
      request(`/api/analytics/trend${scopeQuery.value ? scopeQuery.value + '&' : '?'}bucket_minutes=${bucketMinutes.value}`),
      request('/api/sessions/active'),
      request('/api/inspection/scans?limit=8')
    ])
    summary.value = summaryData
    trend.value = trendData.items
    session.value = sessionData.session
    recent.value = scanData.items
  } catch (error) {
    emit('error', `Dashboard data unavailable: ${error.message}`)
  } finally {
    loading.value = false
  }
}

async function startNewShift() {
  shiftBusy.value = true
  try {
    await request('/api/sessions', { method: 'POST', body: JSON.stringify({ notes: 'Shift started from dashboard' }) })
    scope.value = 'active'
    await load()
  } catch (error) { emit('error', `Unable to start shift: ${error.message}`) } finally { shiftBusy.value = false }
}

onMounted(load)
watch(() => props.refreshKey, load)
watch([scope, bucketMinutes], load)
defineExpose({ load })
</script>

<template>
  <section class="content-grid">
    <div class="dashboard-toolbar">
      <div class="segmented" role="group" aria-label="Analytics scope">
        <button :class="{ active: scope === 'active' }" @click="scope = 'active'">Current shift</button>
        <button :class="{ active: scope === 'all' }" @click="scope = 'all'">All time</button>
      </div>
      <p class="muted shift-meta" v-if="session">Shift started {{ formatTimestamp(session.started_at) }}</p>
      <button class="secondary-button" :disabled="shiftBusy" @click="startNewShift">{{ shiftBusy ? 'Starting…' : 'Start new shift' }}</button>
    </div>

    <div class="volume-row">
      <article class="panel volume-card">
        <p class="eyebrow">Session processing volume</p>
        <strong class="hero-number">{{ loading ? '—' : (summary.total_scans ?? 0).toLocaleString() }}</strong>
        <p class="muted">Cardava bunches scanned {{ scope === 'active' ? 'this shift' : 'in total' }}</p>
        <p class="volume-foot"><span>{{ summary.total_completed_scans ?? 0 }} graded</span><span v-if="summary.technical_failure_count">· {{ summary.technical_failure_count }} technical failure{{ summary.technical_failure_count === 1 ? '' : 's' }} (excluded from rates)</span></p>
      </article>
      <div class="kpi-grid three">
        <article class="kpi-card grade-a"><span>CLASS A</span><strong>{{ summary.class_a_count ?? 0 }}</strong><small>Large hand · ≥ 12 cm</small></article>
        <article class="kpi-card grade-b"><span>CLASS B</span><strong>{{ summary.class_b_count ?? 0 }}</strong><small>Small hand · 8–12 cm</small></article>
        <article class="kpi-card reject"><span>REJECTED</span><strong>{{ summary.rejected_count ?? 0 }}</strong><small>{{ summary.rejection_rate ?? 0 }}% · unhealthy at Stage 1</small></article>
      </div>
    </div>

    <div class="chart-grid">
      <div class="panel chart-panel">
        <div class="panel-heading"><div><p class="eyebrow">Yield distribution</p><h2>Accepted export grades</h2></div><span class="muted small">{{ summary.export_acceptance_rate ?? 0 }}% of graded bunches accepted</span></div>
        <div v-if="!accepted" class="chart-empty">No accepted bunches yet.</div>
        <div v-else class="yield-layout">
          <div class="doughnut-area">
            <Doughnut :data="yieldChart" :options="yieldOptions" aria-label="Class A versus Class B doughnut chart" />
            <div class="doughnut-center"><strong>{{ accepted }}</strong><span>accepted</span></div>
          </div>
          <ul class="yield-legend">
            <li><span class="swatch a"></span><div><b>Class A</b><small>Large hand ≥ 12 cm</small></div><strong>{{ summary.class_a_count }}<em>{{ sharePct(summary.class_a_count) }}%</em></strong></li>
            <li><span class="swatch b"></span><div><b>Class B</b><small>Small hand 8–12 cm</small></div><strong>{{ summary.class_b_count }}<em>{{ sharePct(summary.class_b_count) }}%</em></strong></li>
          </ul>
        </div>
      </div>
      <div class="panel chart-panel">
        <div class="panel-heading">
          <div><p class="eyebrow">Rejection analytics</p><h2>Rejection rate over time</h2></div>
          <label class="inline-select">Interval
            <select v-model.number="bucketMinutes" aria-label="Trend interval">
              <option :value="5">5 min</option><option :value="15">15 min</option><option :value="60">1 hour</option><option :value="1440">1 day</option>
            </select>
          </label>
        </div>
        <div v-if="!trend.length" class="chart-empty">No graded scans in this period yet.</div>
        <div v-else class="chart-area"><Line :data="trendChart" :options="trendOptions" aria-label="Rejection rate line chart" /></div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-heading"><div><p class="eyebrow">Recent scans</p><h2>Latest grading results</h2></div><button class="text-button" @click="$emit('navigate', 'history')">View all scans</button></div>
      <ScanTable :scans="recent" @select="$emit('select', $event)" @dispute="$emit('dispute', $event)" />
    </div>
  </section>
</template>
