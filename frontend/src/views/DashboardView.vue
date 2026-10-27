<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ArcElement, Chart as ChartJS, DoughnutController, Filler, LineElement, LinearScale, PointElement, Tooltip } from 'chart.js'
import { Doughnut, Line } from 'vue-chartjs'
import { request } from '../composables/useApi.js'
import { formatPercent } from '../lib/grades.js'
import { currentShift, plural, scopeQuery, scopeShift, shiftDuration, shiftStart } from '../lib/shifts.js'
import { bucketLabel, intervalName, isIsolated, tickLabels, tickStep, timeTicks, trendBounds, trendPoints } from '../lib/trend.js'
import ScanTable from '../components/ScanTable.vue'
import ShiftSelect from '../components/ShiftSelect.vue'
import StartShiftDialog from '../components/StartShiftDialog.vue'

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
const recent = ref([])
const loading = ref(true)
const starting = ref(false)

const withScope = (path, extra = '') => {
  const query = [scopeQuery(scope.value), extra].filter(Boolean).join('&')
  return query ? `${path}?${query}` : path
}
const shown = computed(() => scopeShift(scope.value, shifts.value))
const viewingPast = computed(() => !['active', 'all'].includes(scope.value))
const scopeNote = computed(() => {
  if (scope.value === 'all') return 'Totals across every shift'
  if (!shown.value) return ''
  const name = shown.value.name ? `${shown.value.name} · ` : ''
  return viewingPast.value ? `${name}Ran for ${shiftDuration(shown.value)}` : `${name}Started ${shiftStart(shown.value)}`
})
const scopePhrase = computed(() => (scope.value === 'all' ? 'across all shifts' : viewingPast.value ? 'in this shift' : 'this shift'))
const emptyNote = computed(() => (viewingPast.value ? 'in this shift' : scope.value === 'all' ? 'yet' : 'in this shift yet'))

const count = key => summary.value[key] ?? 0
const graded = computed(() => count('total_completed_scans'))
const accepted = computed(() => count('class_a_count') + count('class_b_count'))
const rejectionRate = computed(() => (graded.value ? (count('rejected_count') / graded.value) * 100 : null))
// The three grade cards share one denominator, so their percentages add up to 100.
const ofGraded = n => (graded.value ? `${formatPercent((n / graded.value) * 100)} of graded` : 'No graded scans yet')
const shareOfAccepted = n => (accepted.value ? formatPercent((n / accepted.value) * 100) : '')

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
    recent.value = scanData.items
  } catch (error) {
    emit('error', `Dashboard data unavailable: ${error.message}`)
  } finally {
    loading.value = false
  }
}

function onShiftStarted() {
  starting.value = false
  if (scope.value === 'active') load()
  else scope.value = 'active'
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
      <button class="secondary-button" @click="starting = true">Start new shift</button>
    </div>
    <div v-if="viewingPast" class="scope-notice" role="status">
      <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
      <span><b>Past shift.</b> These totals are final. New scans count toward the current shift.</span>
      <button class="text-button" @click="scope = 'active'">Back to current shift</button>
    </div>

    <div class="volume-row">
      <article class="panel volume-card">
        <p class="eyebrow">Processing volume</p>
        <strong class="hero-number">{{ loading ? '—' : count('total_scans').toLocaleString() }}</strong>
        <p class="muted">Cardava bunches scanned {{ scopePhrase }}</p>
        <p class="volume-foot">
          <span>{{ graded.toLocaleString() }} graded</span>
          <span v-if="count('technical_failure_count')">· {{ plural(count('technical_failure_count'), 'technical failure') }}, not counted in the rates</span>
          <span v-if="count('voided_count')">· {{ count('voided_count').toLocaleString() }} voided, not counted at all</span>
        </p>
      </article>
      <div class="kpi-grid three">
        <article class="kpi-card grade-a"><span>Class A</span><strong>{{ count('class_a_count') }}</strong><small class="kpi-share">{{ ofGraded(count('class_a_count')) }}</small><small>Large hand · width ≥ 2730.07 px</small></article>
        <article class="kpi-card grade-b"><span>Class B</span><strong>{{ count('class_b_count') }}</strong><small class="kpi-share">{{ ofGraded(count('class_b_count')) }}</small><small>Small hand · width &lt; 2730.07 px</small></article>
        <article class="kpi-card reject"><span>Rejected</span><strong>{{ count('rejected_count') }}</strong><small class="kpi-share">{{ ofGraded(count('rejected_count')) }}</small><small>Unhealthy at Stage 1</small></article>
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
            <li><span class="swatch a"></span><div><b>Class A</b><small>Large hand · width ≥ 2730.07 px</small></div><strong>{{ count('class_a_count') }}<em>{{ shareOfAccepted(count('class_a_count')) }}</em></strong></li>
            <li><span class="swatch b"></span><div><b>Class B</b><small>Small hand · width &lt; 2730.07 px</small></div><strong>{{ count('class_b_count') }}<em>{{ shareOfAccepted(count('class_b_count')) }}</em></strong></li>
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

    <StartShiftDialog :open="starting" :current="currentShift(shifts)" @close="starting = false" @started="onShiftStarted" />
  </section>
</template>
