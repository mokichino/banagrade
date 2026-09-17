<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import YieldChart from './components/YieldChart.vue'
import RejectionChart from './components/RejectionChart.vue'
import QualityTrendChart from './components/QualityTrendChart.vue'
import { useRaspberryPi } from './composables/useRaspberryPi'

const currentPage = ref('overview')
const menuOpen = ref(false)
const search = ref('')
const healthFilter = ref('all')
const gradeFilter = ref('all')
const startDate = ref('')
const endDate = ref('')
const reportMonth = ref('2026-09')
const currentTime = ref(new Date())
const shiftActive = ref(true)
const workers = ref(12)
const savingShift = ref(false)
const exportState = ref('')
const ticketScan = ref(null)
const ticketNote = ref('')
const ticketSaving = ref(false)
const ticketState = ref('')
const { enabled: piEnabled, connected: piConnected } = useRaspberryPi()

const navItems = [
  { id: 'overview', label: 'Overview' },
  { id: 'scans', label: 'Scan History' },
  { id: 'trends', label: 'Quality Trends' },
  { id: 'equipment', label: 'Equipment' },
  { id: 'reports', label: 'Reports' },
]

const fallbackData = {
  summary: {
    sessionVolume: 1284,
    classA: 539,
    classB: 488,
    rejected: 257,
    yieldRate: 82,
    thesisObjective: 'Improve grading consistency, traceability, and supervisor decision support in banana packing operations.',
  },
  scans: [
    { id: 'VIEU-001284', timestamp: '09:42:18', stage1: 'Healthy', stage2: 'Large hand', confidence: 97, grade: 'Class A', qualityIndex: 91, line: 'Line 2' },
    { id: 'VIEU-001283', timestamp: '09:41:56', stage1: 'Healthy', stage2: 'Small hand', confidence: 94, grade: 'Class B', qualityIndex: 83, line: 'Line 1' },
    { id: 'VIEU-001282', timestamp: '09:41:20', stage1: 'Unhealthy', stage2: 'Rejected', confidence: 98, grade: 'Rejected', qualityIndex: 42, line: 'Line 3' },
    { id: 'VIEU-001281', timestamp: '09:40:51', stage1: 'Healthy', stage2: 'Large hand', confidence: 91, grade: 'Class A', qualityIndex: 89, line: 'Line 2' },
    { id: 'VIEU-001280', timestamp: '09:40:22', stage1: 'Healthy', stage2: 'Small hand', confidence: 96, grade: 'Class B', qualityIndex: 81, line: 'Line 1' },
    { id: 'VIEU-001279', timestamp: '09:39:43', stage1: 'Unhealthy', stage2: 'Rejected', confidence: 93, grade: 'Rejected', qualityIndex: 38, line: 'Line 3' },
  ],
  trend: [
    { time: '09:00', rate: 8 },
    { time: '10:00', rate: 11 },
    { time: '11:00', rate: 9 },
    { time: '12:00', rate: 14 },
    { time: '13:00', rate: 10 },
  ],
  equipment: [
    { name: 'Camera Feed', state: 'Stable', detail: 'No calibration drift detected', specs: '12 MP industrial camera · 30 FPS', firmware: 'v2.4.1', lastService: 'Sep 12, 2026', health: 98 },
    { name: 'AI Pipeline', state: 'Operational', detail: 'Model confidence average 94%', specs: 'Quality classifier · GPU inference', firmware: 'Model 1.8.0', lastService: 'Sep 15, 2026', health: 96 },
    { name: 'Raspberry Pi 5', state: 'Staging disabled', detail: 'Bridge ready; hardware transport is off', specs: '8 GB RAM · GPIO / camera bridge', firmware: 'Bridge staged', lastService: 'Not commissioned', health: 100 },
    { name: 'Packing Line', state: 'Ready', detail: 'Next bunch queued', specs: 'Line 2 · Automated diverter', firmware: 'PLC 4.2.0', lastService: 'Sep 10, 2026', health: 94 },
  ],
  systemStatus: {
    mode: 'ready',
    label: 'System Ready',
    detail: 'Waiting for banana',
  },
}

const dashboardData = ref({ ...fallbackData })

const statusConfig = {
  ready: { label: 'System Ready', text: 'Waiting for banana', dot: 'ready-dot', pill: 'ready-pill' },
  class_a: { label: 'Class A Detected', text: 'Large hand · ≥ 12 cm', dot: 'a-dot', pill: 'a-pill' },
  class_b: { label: 'Class B Detected', text: 'Small hand · 8–12 cm', dot: 'b-dot', pill: 'b-pill' },
  booting: { label: 'System Booting', text: 'Calibrating camera and sensors', dot: 'boot-dot', pill: 'boot-pill' },
  error: { label: 'Hardware Error', text: 'Check camera / Raspberry Pi', dot: 'error-dot', pill: 'error-pill' },
}

const formattedDate = computed(() =>
  currentTime.value.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
)

const formattedClock = computed(() => {
  const hours = String(currentTime.value.getHours()).padStart(2, '0')
  const minutes = String(currentTime.value.getMinutes()).padStart(2, '0')
  const seconds = String(currentTime.value.getSeconds()).padStart(2, '0')
  return `${hours}:${minutes}:${seconds}`
})

const metrics = computed(() => [
  { title: 'Session Volume', subtitle: 'Current shift', value: dashboardData.value.summary.sessionVolume.toLocaleString(), note: 'Cardava bananas scanned', accent: 'gold' },
  { title: 'Class A', subtitle: 'Large hand', value: dashboardData.value.summary.classA.toLocaleString(), note: '≥ 12 cm', accent: 'gold' },
  { title: 'Class B', subtitle: 'Small hand', value: dashboardData.value.summary.classB.toLocaleString(), note: '8–12 cm', accent: 'blue' },
  { title: 'Rejected', subtitle: 'Unhealthy / undersized', value: dashboardData.value.summary.rejected.toLocaleString(), note: '< 8 cm or unhealthy', accent: 'red' },
])

const yieldData = computed(() => [
  { name: 'Class A', value: 42, color: '#F4C542' },
  { name: 'Class B', value: 38, color: '#3B82F6' },
  { name: 'Rejected', value: 20, color: '#EF4444' },
])

const recentScans = computed(() => dashboardData.value.scans.slice(0, 5))

const filteredScans = computed(() => {
  return dashboardData.value.scans.filter((scan) => {
    const query = search.value.trim().toLowerCase()
    const matchesSearch = !query || scan.id.toLowerCase().includes(query) || scan.grade.toLowerCase().includes(query)
    const matchesHealth = healthFilter.value === 'all' || scan.stage1 === healthFilter.value
    const matchesGrade = gradeFilter.value === 'all' || scan.grade === gradeFilter.value
    const scanDate = scan.capturedAt?.slice(0, 10)
    const matchesStart = !startDate.value || !scanDate || scanDate >= startDate.value
    const matchesEnd = !endDate.value || !scanDate || scanDate <= endDate.value
    return matchesSearch && matchesHealth && matchesGrade && matchesStart && matchesEnd
  })
})

const currentRejection = computed(() => {
  const trend = dashboardData.value.trend
  const last = trend[trend.length - 1].rate
  const first = trend[0].rate
  const delta = last - first
  return { current: last, delta }
})

const shiftLabel = computed(() => shiftActive.value ? 'Active' : 'Inactive')

const weekRange = computed(() => {
  const today = new Date(currentTime.value)
  const day = today.getDay()
  const mondayOffset = day === 0 ? -6 : 1 - day
  const start = new Date(today)
  start.setDate(today.getDate() + mondayOffset)
  const end = new Date(start)
  end.setDate(start.getDate() + 6)
  const format = (value, includeYear = false) => value.toLocaleDateString('en-US', { month: 'short', day: 'numeric', ...(includeYear ? { year: 'numeric' } : {}) })
  return `${format(start)} – ${format(end, start.getFullYear() !== end.getFullYear())}`
})

const trendStats = computed(() => {
  const scans = dashboardData.value.scans
  const total = scans.length || 1
  const averageConfidence = scans.reduce((sum, scan) => sum + scan.confidence, 0) / total
  const share = (grade) => Math.round(scans.filter((scan) => scan.grade === grade).length / total * 100)
  return {
    confidence: `${averageConfidence.toFixed(1)}%`,
    classA: `${share('Class A')}%`,
    classB: `${share('Class B')}%`,
    rejected: `${share('Rejected')}%`,
  }
})

const reportScans = computed(() => {
  const prefix = reportMonth.value
  return dashboardData.value.scans.filter((scan) => scan.capturedAt?.startsWith(prefix))
})

const reportSummary = computed(() => {
  const scans = reportScans.value
  const total = scans.length
  const count = (grade) => scans.filter((scan) => scan.grade === grade).length
  const rejected = count('Rejected')
  const confidence = total ? scans.reduce((sum, scan) => sum + scan.confidence, 0) / total : 0
  return {
    sessionVolume: total,
    classA: count('Class A'),
    classB: count('Class B'),
    rejected,
    yieldRate: total ? Math.round((total - rejected) / total * 100) : 0,
    averageConfidence: confidence.toFixed(1),
  }
})

const reportYieldData = computed(() => {
  const total = reportSummary.value.sessionVolume || 1
  return [
    { name: 'Class A', value: Math.round(reportSummary.value.classA / total * 100), color: '#F4C542' },
    { name: 'Class B', value: Math.round(reportSummary.value.classB / total * 100), color: '#3B82F6' },
    { name: 'Rejected', value: Math.round(reportSummary.value.rejected / total * 100), color: '#EF4444' },
  ]
})

const reportPeriodLabel = computed(() => {
  const value = new Date(`${reportMonth.value}-01T00:00:00`)
  return value.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
})

const gradeClass = (grade) => ({
  'Class A': 'grade-badge grade-a',
  'Class B': 'grade-badge grade-b',
  Rejected: 'grade-badge grade-red',
  'N/A': 'grade-badge grade-neutral',
}[grade] || 'grade-badge grade-neutral')

const stageClass = (value) => value === 'Healthy' ? 'stage-pill stage-healthy' : 'stage-pill stage-unhealthy'

const statusDescriptor = computed(() => statusConfig[dashboardData.value.systemStatus.mode] || statusConfig.ready)

const thesisSummary = computed(() => dashboardData.value.summary.thesisObjective)
const averageHealth = computed(() => {
  const equipment = dashboardData.value.equipment
  return equipment.length ? Math.round(equipment.reduce((sum, item) => sum + (item.health || 0), 0) / equipment.length) : 0
})

function downloadFile(content, filename, type) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function escapeCsv(value) {
  return `"${String(value ?? '').replaceAll('"', '""')}"`
}

function exportScans() {
  const headers = ['Scan ID', 'Captured At', 'Stage 1', 'Stage 2', 'Confidence', 'Final Grade', 'Quality Index', 'Line']
  const rows = filteredScans.value.map((scan) => [scan.id, scan.capturedAt || scan.timestamp, scan.stage1, scan.stage2, `${scan.confidence}%`, scan.grade, scan.qualityIndex, scan.line])
  downloadFile([headers, ...rows].map((row) => row.map(escapeCsv).join(',')).join('\n'), `bananagrade-scans-${new Date().toISOString().slice(0, 10)}.csv`, 'text/csv;charset=utf-8')
  exportState.value = `${rows.length} scans exported`
  window.setTimeout(() => { exportState.value = '' }, 3000)
}

function exportReport() {
  const reportRows = [
    ['BananaGrade packing report', ''],
    ['Generated at', new Date().toLocaleString()],
    ['Reporting period', reportPeriodLabel.value],
    ['Shift status', shiftLabel.value],
    ['Workers on floor', workers.value],
    [],
    ['Summary metric', 'Value'],
    ['Session volume', reportSummary.value.sessionVolume],
    ['Class A', reportSummary.value.classA],
    ['Class B', reportSummary.value.classB],
    ['Rejected', reportSummary.value.rejected],
    ['Yield rate', `${reportSummary.value.yieldRate}%`],
    ['Average confidence', `${reportSummary.value.averageConfidence}%`],
    [],
    ['Equipment', 'State', 'Health', 'Specifications', 'Firmware', 'Last service'],
    ...dashboardData.value.equipment.map((item) => [item.name, item.state, `${item.health}%`, item.specs, item.firmware, item.lastService]),
    [],
    ['Scan ID', 'Captured At', 'Stage 1', 'Stage 2', 'Confidence', 'Final Grade', 'Quality Index', 'Line', 'Disputed'],
    ...reportScans.value.map((scan) => [scan.id, scan.capturedAt || scan.timestamp, scan.stage1, scan.stage2, `${scan.confidence}%`, scan.grade, scan.qualityIndex, scan.line, scan.ticketed ? 'Yes' : 'No']),
  ]
  downloadFile(reportRows.map((row) => row.map(escapeCsv).join(',')).join('\n'), `bananagrade-report-${new Date().toISOString().slice(0, 10)}.csv`, 'text/csv;charset=utf-8')
  exportState.value = 'CSV report exported'
  window.setTimeout(() => { exportState.value = '' }, 3000)
}

function printReport() {
  const previousPage = currentPage.value
  currentPage.value = 'reports'
  window.setTimeout(() => {
    window.print()
    currentPage.value = previousPage
  }, 100)
}

function printScans() {
  const previousPage = currentPage.value
  currentPage.value = 'scans'
  window.setTimeout(() => {
    window.print()
    currentPage.value = previousPage
  }, 100)
}

function openTicket(scan) {
  ticketScan.value = scan
  ticketNote.value = scan.ticketNote || ''
  ticketState.value = ''
}

function closeTicket() {
  if (!ticketSaving.value) ticketScan.value = null
}

async function submitTicket() {
  if (!ticketScan.value) return
  ticketSaving.value = true
  try {
    const response = await fetch(`/api/scans/${ticketScan.value.id}/ticket`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: ticketNote.value.trim() }),
    })
    if (!response.ok) throw new Error('Ticket could not be saved')
    const data = await response.json()
    const updateTicket = (scan) => scan.id === ticketScan.value.id ? { ...scan, ticketed: true, ticketNote: data.ticket.note, ticketedAt: data.ticket.createdAt } : scan
    dashboardData.value.scans = dashboardData.value.scans.map(updateTicket)
    ticketState.value = 'Contest note saved'
    window.setTimeout(closeTicket, 900)
  } catch (error) {
    ticketState.value = 'Unable to save note'
  } finally {
    ticketSaving.value = false
  }
}

async function loadDashboard() {
  try {
    const response = await fetch('/api/dashboard')
    if (!response.ok) {
      throw new Error('Dashboard request failed')
    }
    const data = await response.json()
    dashboardData.value = data
    shiftActive.value = data.shift?.isActive ?? true
    workers.value = data.shift?.workers ?? 12
  } catch (error) {
    console.warn('Using fallback dashboard data:', error)
    dashboardData.value = { ...fallbackData }
  }
}

async function updateShift() {
  savingShift.value = true
  try {
    const response = await fetch('/api/v1/shift/update', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ isActive: shiftActive.value, workers: Number(workers.value) || 0 }),
    })
    const data = await response.json()
    shiftActive.value = data.shift.isActive
    workers.value = data.shift.workers
  } finally {
    savingShift.value = false
  }
}

async function loadFilteredScans() {
  const params = new URLSearchParams()
  if (startDate.value) params.set('start_date', startDate.value)
  if (endDate.value) params.set('end_date', endDate.value)
  const response = await fetch(`/api/scans?${params}`)
  if (response.ok) dashboardData.value.scans = (await response.json()).scans
}

onMounted(() => {
  loadDashboard()

  const timer = setInterval(() => {
    currentTime.value = new Date()
  }, 1000)

  return () => clearInterval(timer)
})

watch([startDate, endDate], loadFilteredScans)

function setPage(page) {
  currentPage.value = page
  menuOpen.value = false
}
</script>

<template>
  <div class="dashboard-shell">
    <aside class="sidebar">
      <div class="brand-box">
        <div class="brand-mark">B</div>
        <div>
          <div class="brand-name">BananaGrade</div>
          <div class="brand-subtitle">AI SORTING SYSTEM</div>
        </div>
        <button class="mobile-menu-button" type="button" :aria-expanded="menuOpen" aria-controls="primary-navigation" aria-label="Toggle navigation menu" @click="menuOpen = !menuOpen">
          <span class="menu-icon" aria-hidden="true">☰</span>
        </button>
      </div>

      <nav id="primary-navigation" class="sidebar-nav" :class="{ open: menuOpen }" aria-label="Primary navigation">
        <button
          v-for="item in navItems"
          :key="item.id"
          :class="['nav-item', { active: currentPage === item.id }]"
          @click="setPage(item.id)"
        >
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <div class="sidebar-status">
        <div :class="['status-pill', statusDescriptor.pill]">
          <span :class="['status-dot', statusDescriptor.dot]"></span>
          <div>
            <div class="status-label">{{ statusDescriptor.label }}</div>
            <div class="status-text">{{ statusDescriptor.text }}</div>
          </div>
        </div>
      </div>
    </aside>

    <div class="main-panel">
      <header class="topbar">
        <div>
          <div class="page-title">
            {{ currentPage === 'overview' ? 'Operations Overview' : currentPage === 'scans' ? 'Scan History' : currentPage === 'trends' ? 'Quality Trends' : currentPage === 'equipment' ? 'Equipment Status' : 'Packing Reports' }}
          </div>
          <div class="page-subtitle">
            AI-powered Cardava banana quality grading and sorting for packinghouse supervision.
          </div>
        </div>

        <div class="header-meta">
          <div class="meta-block">
            <div class="meta-label">Current shift</div>
            <button
              class="shift-toggle"
              :class="{ active: shiftActive }"
              type="button"
              role="switch"
              :aria-checked="shiftActive"
              :aria-label="`Shift ${shiftLabel.toLowerCase()}`"
              @click="shiftActive = !shiftActive; updateShift()"
            >
              <span class="toggle-track"><span class="toggle-thumb"></span></span>
              <span>{{ shiftLabel }}</span>
            </button>
          </div>
          <div class="meta-divider"></div>
          <div class="meta-block system-state-block">
            <div class="meta-label">Current system state</div>
            <div class="system-state-header"><span :class="['status-dot', statusDescriptor.dot]"></span>{{ statusDescriptor.label }}</div>
          </div>
          <div class="meta-divider"></div>
          <div class="meta-block clock-block">
            <div class="meta-label">{{ formattedDate }}</div>
            <div class="meta-value time-value">{{ formattedClock }}</div>
          </div>
          <span v-if="savingShift" class="save-state">Saving</span>
        </div>
      </header>

      <main class="content" v-if="currentPage === 'overview'">
        <section class="metrics-grid">
          <article class="metric-card metric-featured">
            <div class="metric-header">
              <div>
                <div class="metric-title">Session processing volume</div>
                <div class="metric-subtitle">Current shift</div>
              </div>
              <span class="live-badge"><span class="live-dot"></span>Live</span>
            </div>
            <div class="metric-value-row">
              <div class="accent-bar gold"></div>
              <div class="metric-value">{{ metrics[0].value }}</div>
            </div>
            <div class="metric-note">Cardava bananas scanned</div>
          </article>

          <article v-for="(item, index) in metrics.slice(1)" :key="index" class="metric-card">
            <div class="metric-header compact">
              <div>
                <div class="metric-title">{{ item.title }}</div>
                <div class="metric-subtitle">{{ item.subtitle }}</div>
              </div>
            </div>
            <div class="metric-value-row">
              <div :class="['accent-bar', item.accent]"></div>
              <div class="metric-value small">{{ item.value }}</div>
            </div>
            <div class="metric-note">{{ item.note }}</div>
          </article>
        </section>

        <section class="analytics-grid">
          <article class="panel chart-panel">
            <div class="panel-header">
              <div>
                <div class="panel-kicker">Yield distribution</div>
                <div class="panel-subtitle">Current session classification</div>
              </div>
            </div>
            <div class="yield-layout">
              <YieldChart :values="yieldData" :total="metrics[0].value" />

              <div class="legend-list">
                <div v-for="item in yieldData" :key="item.name" class="legend-item">
                  <div class="legend-meta">
                    <span class="legend-swatch" :style="{ background: item.color }"></span>
                    <span>{{ item.name }}</span>
                  </div>
                  <strong>{{ item.value }}%</strong>
                </div>
              </div>
            </div>
          </article>

          <article class="panel analytics-panel">
            <div class="panel-header split">
              <div>
                <div class="panel-kicker">Rejection analytics</div>
                <div class="panel-subtitle">Rejection rate during the current session</div>
              </div>
              <div class="rejection-summary">
                <div class="rejection-value">{{ currentRejection.current }}%</div>
                <div class="rejection-meta">Current rejection rate</div>
                <div :class="['rejection-trend', currentRejection.delta <= 0 ? 'positive' : 'negative']">
                  {{ currentRejection.delta <= 0 ? '↓' : '↑' }} {{ Math.abs(currentRejection.delta).toFixed(1) }}% vs previous session
                </div>
              </div>
            </div>

            <RejectionChart :series="dashboardData.trend" />
          </article>
        </section>

        <section class="bottom-grid">
          <article class="panel activity-panel">
            <div class="panel-header split">
              <div class="panel-kicker">Recent activity</div>
              <button class="link-button" @click="setPage('scans')">View all scans</button>
            </div>

            <table class="scan-table">
              <thead>
                <tr>
                  <th>Scan ID</th>
                  <th>Time</th>
                  <th>Stage 1</th>
                  <th>Final grade</th>
                  <th>Confidence</th>
                  <th>Flag</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="scan in recentScans" :key="scan.id">
                  <td>{{ scan.id }}</td>
                  <td>{{ scan.timestamp }}</td>
                  <td><span :class="stageClass(scan.stage1)">{{ scan.stage1 }}</span></td>
                  <td><span :class="gradeClass(scan.grade)">{{ scan.grade }}</span></td>
                  <td>
                    <div class="confidence-wrap">
                      <div class="confidence-bar">
                        <span :style="{ width: scan.confidence + '%' }"></span>
                      </div>
                      <span>{{ scan.confidence }}%</span>
                    </div>
                  </td>
                  <td><button class="ticket-button flag-button" :class="{ ticketed: scan.ticketed }" type="button" :aria-label="scan.ticketed ? `View dispute for ${scan.id}` : `Flag ${scan.id} as disputed`" @click="openTicket(scan)"><span aria-hidden="true">⚑</span></button></td>
                </tr>
              </tbody>
            </table>
          </article>

          <article class="panel status-panel">
            <div class="panel-kicker">Live system status</div>
            <div class="panel-subtitle">Hardware state monitoring</div>

            <div class="status-stack">
              <div v-for="item in dashboardData.equipment" :key="item.name" class="status-box" :class="item.state === 'Stable' ? 'ready' : item.state === 'Operational' ? 'a-box' : item.state === 'Connected' ? 'b-box' : 'ready'">
                <span class="status-indicator" :class="item.state === 'Stable' ? 'ready-dot' : item.state === 'Operational' ? 'a-dot' : item.state === 'Connected' ? 'b-dot' : 'ready-dot'"></span>
                <div>
                  <strong>{{ item.name }}</strong>
                  <small>{{ item.state }} · {{ item.detail }}</small>
                </div>
              </div>
            </div>
          </article>
        </section>
      </main>

      <main class="content" v-else-if="currentPage === 'scans'">
        <section class="panel table-panel">
          <div class="toolbar">
            <input v-model="search" type="search" placeholder="Search by scan ID or grade" class="search-input" />
            <label class="date-field">From <input v-model="startDate" type="date" /></label>
            <label class="date-field">To <input v-model="endDate" type="date" /></label>
            <select v-model="healthFilter" class="filter-select">
              <option value="all">All health status</option>
              <option value="Healthy">Healthy</option>
              <option value="Unhealthy">Unhealthy</option>
            </select>
            <select v-model="gradeFilter" class="filter-select">
              <option value="all">All grades</option>
              <option value="Class A">Class A</option>
              <option value="Class B">Class B</option>
              <option value="Rejected">Rejected</option>
            </select>
            <button class="export-button" type="button" @click="exportScans"><span class="button-icon" aria-hidden="true">↓</span> Export CSV</button>
            <button class="link-button" type="button" @click="printScans"><span class="button-icon" aria-hidden="true">▣</span> Export PDF</button>
            <span v-if="exportState" class="export-feedback" role="status">{{ exportState }}</span>
          </div>

          <div class="table-scroll" role="region" aria-label="Scan history table" tabindex="0">
          <table class="scan-table full-table">
            <thead>
              <tr>
                <th>Scan ID</th>
                <th>Timestamp</th>
                <th>Stage 1</th>
                <th>Stage 2</th>
                <th>Confidence</th>
                <th>Final grade</th>
                <th>Flag</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="scan in filteredScans" :key="scan.id">
                <td>{{ scan.id }}</td>
                <td>{{ scan.timestamp }}</td>
                <td><span :class="stageClass(scan.stage1)">{{ scan.stage1 }}</span></td>
                <td>{{ scan.stage2 }}</td>
                <td>
                  <div class="confidence-wrap">
                    <div class="confidence-bar">
                      <span :style="{ width: scan.confidence + '%' }"></span>
                    </div>
                    <span>{{ scan.confidence }}%</span>
                  </div>
                </td>
                <td><span :class="gradeClass(scan.grade)">{{ scan.grade }}</span></td>
                <td><button class="ticket-button flag-button" :class="{ ticketed: scan.ticketed }" type="button" :aria-label="scan.ticketed ? `View dispute for ${scan.id}` : `Flag ${scan.id} as disputed`" @click="openTicket(scan)"><span aria-hidden="true">⚑</span></button></td>
              </tr>
              <tr v-if="filteredScans.length === 0">
                <td colspan="7" class="empty-table">No scans match the selected filters.</td>
              </tr>
            </tbody>
          </table>
          </div>
        </section>
      </main>

      <main class="content" v-else-if="currentPage === 'trends'">
        <section class="panel trend-panel">
          <div class="panel-header split">
            <div>
              <div class="panel-kicker">Quality trends</div>
                <div class="panel-subtitle">Weekly quality signal · {{ weekRange }}</div>
            </div>
            <div class="trend-actions">
              <div class="trend-pill">{{ dashboardData.summary.yieldRate }}% yield rate</div>
              <button class="link-button" type="button" @click="printReport"><span class="button-icon" aria-hidden="true">▣</span> Export PDF</button>
            </div>
          </div>

          <div class="trend-grid">
            <div class="mini-card">
              <div class="mini-label">Avg. confidence</div>
              <div class="mini-value">{{ trendStats.confidence }}</div>
            </div>
            <div class="mini-card">
              <div class="mini-label">Class A share</div>
              <div class="mini-value">{{ trendStats.classA }}</div>
            </div>
            <div class="mini-card">
              <div class="mini-label">Class B share</div>
              <div class="mini-value">{{ trendStats.classB }}</div>
            </div>
            <div class="mini-card">
              <div class="mini-label">Rejected share</div>
              <div class="mini-value">{{ trendStats.rejected }}</div>
            </div>
          </div>

          <div class="trend-chart-heading">
            <span>Rejection rate by processing hour</span>
            <span class="trend-updated">Updated live</span>
          </div>
          <QualityTrendChart :series="dashboardData.trend" />
        </section>
      </main>

      <main class="content" v-else-if="currentPage === 'equipment'">
        <section class="panel status-detail-panel">
          <div class="panel-header split equipment-header">
            <div>
              <div class="panel-kicker">Equipment register</div>
              <div class="panel-subtitle">Live readiness, specifications, and service history</div>
            </div>
            <div class="equipment-health"><strong>{{ averageHealth }}%</strong><span>fleet health</span></div>
          </div>
          <div class="system-state-row">
            <div class="state-card active">
              <span class="status-indicator ready-dot large"></span>
              <div>
                <strong>System ready</strong>
                <small>Waiting for banana</small>
              </div>
            </div>
            <div class="state-card">
              <span class="status-indicator a-dot large"></span>
              <div>
                <strong>Class A detected</strong>
                <small>Large hand · ≥ 12 cm</small>
              </div>
            </div>
            <div class="state-card">
              <span class="status-indicator b-dot large"></span>
              <div>
                <strong>Class B detected</strong>
                <small>Small hand · 8–12 cm</small>
              </div>
            </div>
          </div>

          <div class="equipment-grid">
              <div v-for="item in dashboardData.equipment" :key="item.name" class="info-box equipment-card">
                <div class="info-label">{{ item.name }}</div>
                <div class="equipment-state"><span class="status-indicator ready-dot"></span><div class="info-value">{{ item.state }}</div></div>
                <small>{{ item.detail }}</small>
                <div class="equipment-specs">{{ item.specs }}</div>
                <div class="equipment-meta"><span>{{ item.firmware }}</span><span>Serviced {{ item.lastService }}</span></div>
                <div class="health-bar"><span :style="{ width: item.health + '%' }"></span></div>
              </div>
          </div>
        </section>
      </main>

      <main class="content" v-else>
        <section class="panel report-panel">
          <div class="panel-header split">
            <div>
              <div class="panel-kicker">Packing reports</div>
              <div class="panel-subtitle">Monthly harvest report · {{ reportPeriodLabel }}</div>
            </div>
            <label class="report-period">Report month <input v-model="reportMonth" id="report-month" name="reportMonth" type="month" /></label>
            <div class="report-actions">
              <button class="export-button" type="button" @click="exportReport"><span class="button-icon" aria-hidden="true">↓</span> Export CSV</button>
              <button class="link-button" type="button" @click="printReport"><span class="button-icon" aria-hidden="true">▣</span> Export PDF</button>
            </div>
            <span v-if="exportState" class="export-feedback" role="status">{{ exportState }}</span>
          </div>

          <div class="report-overview-grid">
            <div class="report-chart-card">
              <div class="report-title">Monthly yield distribution</div>
              <YieldChart :values="reportYieldData" :total="reportSummary.sessionVolume" />
            </div>
            <div class="report-chart-card">
              <div class="report-title">Rejection trend</div>
              <RejectionChart :series="dashboardData.trend" />
            </div>
          </div>

          <div class="report-grid">
            <div class="report-card">
              <div class="report-title">Production snapshot</div>
              <p>{{ reportSummary.sessionVolume }} scans recorded in {{ reportPeriodLabel }} with a yield rate of {{ reportSummary.yieldRate }}%.</p>
            </div>
            <div class="report-card">
              <div class="report-title">Quality signal</div>
              <p>Class A: {{ reportSummary.classA }} · Class B: {{ reportSummary.classB }} · Rejected: {{ reportSummary.rejected }} · Average confidence: {{ reportSummary.averageConfidence }}%.</p>
            </div>
            <div class="report-card">
              <div class="report-title">Thesis alignment</div>
              <p>{{ thesisSummary }}</p>
            </div>
          </div>

          <div class="report-table-wrap">
            <div class="report-title">Monthly scan register</div>
            <table class="scan-table report-scan-table">
              <thead><tr><th>Scan ID</th><th>Time</th><th>Stage 1</th><th>Grade</th><th>Confidence</th><th>Flag</th></tr></thead>
              <tbody>
                <tr v-for="scan in reportScans" :key="`report-${scan.id}`">
                  <td>{{ scan.id }}</td><td>{{ scan.timestamp }}</td><td>{{ scan.stage1 }}</td><td>{{ scan.grade }}</td><td>{{ scan.confidence }}%</td><td>{{ scan.ticketed ? 'Disputed' : '—' }}</td>
                </tr>
                <tr v-if="!reportScans.length"><td colspan="6" class="empty-table">No scans recorded for this month.</td></tr>
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>

    <div v-if="ticketScan" class="modal-backdrop" @click.self="closeTicket">
      <section class="ticket-modal" role="dialog" aria-modal="true" aria-labelledby="ticket-title">
        <div class="ticket-modal-header">
          <div>
            <h2 id="ticket-title">Flag as Disputed</h2>
            <div class="ticket-scan-id">{{ ticketScan.id }}</div>
          </div>
          <button class="modal-close" type="button" aria-label="Close ticket dialog" @click="closeTicket">×</button>
        </div>
        <div class="ticket-summary">
          <div><span>AI Grade</span><strong>{{ ticketScan.grade }}</strong></div>
          <div><span>Confidence</span><strong>{{ ticketScan.confidence }}%</strong></div>
          <div><span>Timestamp</span><strong>{{ ticketScan.timestamp }}</strong></div>
        </div>
        <label class="ticket-label" for="ticket-note">Reason for dispute <span>(optional)</span></label>
        <textarea id="ticket-note" v-model="ticketNote" name="ticketNote" rows="4" maxlength="500" placeholder="e.g. Misidentified — bunch visually healthy, ≥ 12 cm"></textarea>
        <div class="ticket-footer">
          <span v-if="ticketState" :class="ticketState === 'Contest note saved' ? 'ticket-success' : 'ticket-error'" role="status">{{ ticketState }}</span>
          <div class="modal-actions">
            <button class="link-button" type="button" @click="closeTicket">Cancel</button>
            <button class="dispute-confirm-button" type="button" :disabled="ticketSaving" @click="submitTicket">{{ ticketSaving ? 'Saving...' : 'Confirm Flag' }}</button>
          </div>
        </div>
        <p class="ticket-disclaimer">The original AI decision is preserved. This flag is an annotation only.</p>
      </section>
    </div>
  </div>
</template>
