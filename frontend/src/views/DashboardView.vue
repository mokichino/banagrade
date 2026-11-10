<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArcElement, Chart as ChartJS, DoughnutController, Filler, LineElement, LinearScale, PointElement, Tooltip } from 'chart.js'
import { Doughnut, Line } from 'vue-chartjs'
import { request } from '../composables/useApi.js'
import { WIDTH_THRESHOLD_PX, formatPercent } from '../lib/grades.js'
import { currentShift, scopeQuery, scopeShift, shiftDuration, shiftStart } from '../lib/shifts.js'
import { bucketLabel, intervalName, isIsolated, tickLabels, tickStep, timeTicks, trendBounds, trendPoints } from '../lib/trend.js'
import ScanTable from '../components/ScanTable.vue'
import RenameShiftDialog from '../components/RenameShiftDialog.vue'
import ShiftSelect from '../components/ShiftSelect.vue'

ChartJS.register(ArcElement, DoughnutController, Filler, LineElement, LinearScale, PointElement, Tooltip)

const props = defineProps({ refreshKey: { type: Number, default: 0 } })
const emit = defineEmits(['navigate', 'dispute', 'select', 'void', 'error'])
// Shared with Recent Scans through App, so both pages show the same shift.
const scope = defineModel('scope', { type: String, default: 'active' })

const COLORS = { a: '#D9A300', b: '#2563EB', r: '#DC2626', muted: '#6b7280', grid: '#f0f1f3' }
const bucketMinutes = ref(15)
const summary = ref({})
const trend = ref([])
const shifts = ref([])
// From /api/sessions: `trusted` is false when the Pi's clock reads earlier than scans already recorded.
const clock = ref(null)
const recent = ref([])
const loading = ref(true)
const renaming = ref(false)

const withScope = (path, extra = '') => {
  const query = [scopeQuery(scope.value), extra].filter(Boolean).join('&')
  return query ? `${path}?${query}` : path
}
const shown = computed(() => scopeShift(scope.value, shifts.value))
const open = computed(() => currentShift(shifts.value))
const viewingPast = computed(() => !['active', 'all'].includes(scope.value))
// Recorded by the service once a minute while a shift is open (thesis §4.7).
const cpuNote = computed(() => {
  const cpu = summary.value.cpu_temperature
  return cpu ? `CPU ${cpu.mean_c.toFixed(1)} °C average, ${cpu.max_c.toFixed(1)} °C peak` : ''
})
const scopeNote = computed(() => {
  if (scope.value === 'all') return ['Totals across every shift', cpuNote.value].filter(Boolean).join(' · ')
  if (!shown.value) return ''
  const when = viewingPast.value ? `Ran for ${shiftDuration(shown.value)}` : `Started ${shiftStart(shown.value)}`
  return [shown.value.name, when, cpuNote.value].filter(Boolean).join(' · ')
})
const scopePhrase = computed(() => (scope.value === 'all' ? 'across all shifts' : viewingPast.value ? 'in this shift' : 'this shift'))
const emptyNote = computed(() => (viewingPast.value ? 'in this shift' : scope.value === 'all' ? 'yet' : 'in this shift yet'))

const count = key => summary.value[key] ?? 0
const graded = computed(() => count('total_completed_scans'))
const accepted = computed(() => count('class_a_count') + count('class_b_count'))
const rejectionRate = computed(() => (graded.value ? (count('rejected_count') / graded.value) * 100 : null))
const shareOfAccepted = n => (accepted.value ? formatPercent((n / accepted.value) * 100) : '')
const threshold = `${WIDTH_THRESHOLD_PX.toLocaleString()} px`
// Total scans = graded + technical failures; voided scans sit outside the total.
const volumeRows = computed(() => [
  { label: 'Graded', value: graded.value, tone: 'graded' },
  { label: 'Technical failures', value: count('technical_failure_count'), tone: 'failed', note: 'Left out of rates' },
  { label: 'Voided', value: count('voided_count'), tone: 'voided', note: 'Not in the total' }
])
// The breakdown drops down over the page, so opening it never resizes the card row; a click elsewhere or Escape closes it.
const breakdownOpen = ref(false)
const breakdown = ref(null)
function closeBreakdown(event) {
  if (event.type === 'keydown' ? event.key === 'Escape' : !breakdown.value?.contains(event.target)) breakdownOpen.value = false
}
onMounted(() => { document.addEventListener('click', closeBreakdown); document.addEventListener('keydown', closeBreakdown) })
onBeforeUnmount(() => { document.removeEventListener('click', closeBreakdown); document.removeEventListener('keydown', closeBreakdown) })

const yieldChart = computed(() => ({
  labels: ['Class A', 'Class B'],
  datasets: [{
    data: [count('class_a_count'), count('class_b_count')],
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
  plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed} (${shareOfAccepted(ctx.parsed)} of accepted)` } } }
}

const points = computed(() => trendPoints(trend.value, bucketMinutes.value))
const dense = computed(() => points.value.length > 48)
const trendChart = computed(() => ({
  datasets: [{
    label: 'Rejection rate',
    data: points.value,
    borderColor: COLORS.r,
    backgroundColor: 'rgba(220, 38, 38, .10)',
    borderWidth: 2,
    // Markers on every bucket until they crowd; a lone bucket between gaps always keeps one, or it would vanish.
    pointRadius: ctx => (dense.value && !isIsolated(points.value, ctx.dataIndex) ? 0 : 4),
    pointHoverRadius: 6,
    pointBackgroundColor: COLORS.r,
    pointBorderColor: '#ffffff',
    pointBorderWidth: 2,
    fill: 'origin',
    spanGaps: false,
    tension: 0
  }]
}))

// The shift's overall rate as a quiet dashed reference, drawn under the data.
const averageLine = {
  id: 'averageLine',
  beforeDatasetsDraw(chart, _args, options) {
    if (options.value == null) return
    const { ctx, chartArea, scales } = chart
    const y = scales.y.getPixelForValue(options.value)
    ctx.save()
    ctx.strokeStyle = COLORS.muted
    ctx.lineWidth = 1
    ctx.setLineDash([4, 4])
    ctx.beginPath()
    ctx.moveTo(chartArea.left, y)
    ctx.lineTo(chartArea.right, y)
    ctx.stroke()
    ctx.restore()
  }
}

const trendOptions = computed(() => {
  if (!points.value.length) return {}
  const { min, max } = trendBounds(points.value, bucketMinutes.value)
  const step = tickStep(min, max)
  const spansDays = new Date(min).toDateString() !== new Date(max).toDateString()
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    plugins: {
      legend: { display: false },
      averageLine: { value: rejectionRate.value },
      tooltip: {
        filter: item => item.raw.y != null,
        callbacks: {
          title: items => bucketLabel(items[0].raw.x, bucketMinutes.value),
          label: ctx => ` ${formatPercent(ctx.raw.y)} rejected (${ctx.raw.rejected} of ${ctx.raw.total} graded)`
        }
      }
    },
    scales: {
      x: {
        type: 'linear',
        min,
        max,
        grid: { display: false },
        afterBuildTicks: axis => { axis.ticks = timeTicks(min, max).map(value => ({ value })) },
        ticks: { color: COLORS.muted, maxRotation: 0, autoSkip: false, callback: (_value, index, ticks) => tickLabels(ticks.map(tick => tick.value), step, spansDays)[index] }
      },
      y: { min: 0, max: 100, grid: { color: COLORS.grid }, border: { display: false }, ticks: { stepSize: 25, color: COLORS.muted, callback: value => `${value}%` } }
    }
  }
})

async function load() {
  try {
    const [summaryData, trendData, shiftData, scanData] = await Promise.all([
      request(withScope('/api/analytics/summary')),
      request(withScope('/api/analytics/trend', `bucket_minutes=${bucketMinutes.value}&utc_offset_minutes=${-new Date().getTimezoneOffset()}`)),
      request('/api/sessions'),
      request(withScope('/api/inspection/scans', 'limit=8'))
    ])
    summary.value = summaryData
    trend.value = trendData.items
    shifts.value = shiftData.items
    clock.value = shiftData.clock || null
    recent.value = scanData.items
  } catch (error) {
    emit('error', `Dashboard data unavailable: ${error.message}`)
  } finally {
    loading.value = false
  }
}

function onShiftRenamed() {
  renaming.value = false
  load()
}

onMounted(load)
watch(() => props.refreshKey, load)
watch([scope, bucketMinutes], load)
defineExpose({ load })
</script>

<template>
  <section class="content-grid">
    <div class="dashboard-toolbar">
      <label class="inline-select">Showing <ShiftSelect v-model="scope" :shifts="shifts" /></label>
      <p class="muted shift-meta">{{ scopeNote }}</p>
      <div v-if="open && scope === 'active'" class="shift-actions">
        <button class="secondary-button" @click="renaming = true">{{ open.name ? 'Rename shift' : 'Name shift' }}</button>
      </div>
    </div>
    <div v-if="clock && clock.trusted === false" class="alert" role="alert">
      <span><b>The Pi's clock looks wrong.</b> It reads earlier than scans already recorded, so new scans may get the wrong date and today's shift will not change over. Connect the Pi to the internet, or check its RTC battery.</span>
    </div>
    <div v-if="viewingPast" class="scope-notice" role="status">
      <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
      <span><b>Past shift.</b> These totals are final and its scans are read-only. New scans count toward today's shift.</span>
      <button class="text-button" @click="scope = 'active'">Back to current shift</button>
    </div>

    <div class="volume-row">
      <article class="panel volume-card">
        <p class="eyebrow">Processing volume</p>
        <strong class="hero-number">{{ loading ? '—' : count('total_scans').toLocaleString() }}</strong>
        <p class="muted">Cardava bunches scanned {{ scopePhrase }}</p>
        <div ref="breakdown" class="volume-breakdown">
          <button type="button" class="volume-toggle" :aria-expanded="breakdownOpen" aria-controls="volume-breakdown" @click="breakdownOpen = !breakdownOpen">
            Breakdown
            <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6" /></svg>
          </button>
          <dl v-show="breakdownOpen" id="volume-breakdown" class="volume-stats">
            <div v-for="row in volumeRows" :key="row.label" :class="{ zero: !row.value }">
              <dt><span :class="['volume-dot', row.tone]" aria-hidden="true"></span>{{ row.label }}<small v-if="row.note">{{ row.note }}</small></dt>
              <dd class="tabular">{{ row.value.toLocaleString() }}</dd>
            </div>
          </dl>
        </div>
      </article>
      <div class="kpi-grid three">
        <article class="kpi-card grade-a"><span>Class A</span><strong>{{ count('class_a_count') }}</strong><small>Large hand, width ≥ {{ threshold }}</small></article>
        <article class="kpi-card grade-b"><span>Class B</span><strong>{{ count('class_b_count') }}</strong><small>Small hand, width &lt; {{ threshold }}</small></article>
        <article class="kpi-card reject"><span>Rejected</span><strong>{{ count('rejected_count') }}</strong><small>Unhealthy at Stage 1</small></article>
      </div>
    </div>

    <div class="chart-grid">
      <div class="panel chart-panel">
        <div class="panel-heading">
          <div><p class="eyebrow">Yield distribution</p><h2>Accepted export grades</h2></div>
          <span v-if="graded" class="muted small">{{ formatPercent(count('export_acceptance_rate')) }} of graded bunches accepted</span>
        </div>
        <div v-if="!accepted" class="chart-empty">No accepted bunches {{ emptyNote }}.</div>
        <div v-else class="yield-layout">
          <div class="doughnut-area">
            <Doughnut :data="yieldChart" :options="yieldOptions" aria-label="Class A versus Class B doughnut chart" />
            <div class="doughnut-center"><strong>{{ accepted }}</strong><span>accepted</span></div>
          </div>
          <ul class="yield-legend">
            <li><span class="swatch a"></span><b>Class A</b><strong>{{ count('class_a_count') }}<em>{{ shareOfAccepted(count('class_a_count')) }}</em></strong></li>
            <li><span class="swatch b"></span><b>Class B</b><strong>{{ count('class_b_count') }}<em>{{ shareOfAccepted(count('class_b_count')) }}</em></strong></li>
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
        <div v-if="!points.length" class="chart-empty">No graded scans {{ emptyNote }}.</div>
        <template v-else>
          <ul class="chart-keys">
            <li><span class="key-line"></span>Rejected per {{ intervalName(bucketMinutes) }}, % of graded</li>
            <li><span class="key-line average"></span>{{ scope === 'all' ? 'Overall' : 'Shift' }} average {{ formatPercent(rejectionRate) }}</li>
            <li class="muted">Gaps: nothing graded</li>
          </ul>
          <div class="chart-area"><Line :data="trendChart" :options="trendOptions" :plugins="[averageLine]" aria-label="Rejection rate line chart. The same numbers are in the table below." /></div>
          <details class="chart-table">
            <summary>Show as table</summary>
            <div class="chart-table-wrap">
              <table>
                <thead><tr><th scope="col">Interval</th><th scope="col">Graded</th><th scope="col">Rejected</th><th scope="col">Rate</th></tr></thead>
                <tbody>
                  <tr v-for="item in points.filter(point => point.y != null)" :key="item.x"><td>{{ bucketLabel(item.x, bucketMinutes) }}</td><td class="tabular">{{ item.total }}</td><td class="tabular">{{ item.rejected }}</td><td class="tabular">{{ formatPercent(item.y) }}</td></tr>
                </tbody>
              </table>
            </div>
          </details>
        </template>
      </div>
    </div>

    <div class="panel">
      <div class="panel-heading"><div><p class="eyebrow">Recent scans</p><h2>Latest grading results</h2></div><button class="text-button" @click="$emit('navigate', 'history')">View all scans</button></div>
      <ScanTable :scans="recent" :empty-text="`No scans ${emptyNote}.`" @select="$emit('select', $event)" @dispute="$emit('dispute', $event)" @void="$emit('void', $event)" />
    </div>

    <RenameShiftDialog :open="renaming" :current="open" @close="renaming = false" @renamed="onShiftRenamed" />
  </section>
</template>
