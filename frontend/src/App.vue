<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ScanTable from './components/ScanTable.vue'
import AnalyticsView from './components/AnalyticsView.vue'
import SusEvaluation from './components/SusEvaluation.vue'

const apiBase = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
const activeView = ref('Overview')
const loading = ref(true)
const error = ref('')
const health = ref(null)
const summary = ref({})
const scans = ref([])
const sessions = ref([])
const configuration = ref({ class_a_min_cm: 12, class_b_min_cm: 8 })
const liveEvent = ref(null)
const sessionNotes = ref('')
const socketState = ref('Connecting')
const selectedScan = ref(null)
const now = ref(new Date())
let socket
let clock

const views = ['Overview', 'Recent Scans', 'System Status', 'Live Inspection', 'Analytics', 'Sessions', 'Calibration & Settings', 'Hardware Diagnostics', 'SUS Evaluation', 'Reports']
const kpis = computed(() => [
  ['Completed scans', summary.value.total_completed_scans ?? 0, 'neutral'],
  ['Class A', summary.value.class_a_count ?? 0, 'grade-a'],
  ['Class B', summary.value.class_b_count ?? 0, 'grade-b'],
  ['Commercial rejects', summary.value.rejected_count ?? 0, 'reject']
])
const activeSession = computed(() => sessions.value.find(session => session.status === 'open'))
const currentDate = computed(() => now.value.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }))
const currentTime = computed(() => now.value.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }))

async function request(path, options) {
  const response = await fetch(`${apiBase}${path}`, { headers: { 'Content-Type': 'application/json' }, ...options })
  if (!response.ok) throw new Error((await response.json()).detail || `Request failed: ${response.status}`)
  return response.status === 204 ? null : response.json()
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [healthData, summaryData, scansData, sessionsData, configData] = await Promise.all([
      request('/api/health'), request('/api/analytics/summary'), request('/api/inspection/scans?limit=20'), request('/api/sessions'), request('/api/config')
    ])
    health.value = healthData
    summary.value = summaryData
    scans.value = scansData.items
    sessions.value = sessionsData.items
    configuration.value = configData
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

function connectLive() {
  const wsUrl = apiBase.replace(/^http/, 'ws') + '/ws/live'
  socket = new WebSocket(wsUrl)
  socket.onopen = () => { socketState.value = 'Connected' }
  socket.onmessage = event => { liveEvent.value = JSON.parse(event.data); refresh() }
  socket.onerror = () => { socketState.value = 'Unavailable' }
  socket.onclose = () => { socketState.value = 'Disconnected' }
}

async function startSession() {
  await request('/api/sessions', { method: 'POST', body: JSON.stringify({ notes: sessionNotes.value || null }) })
  sessionNotes.value = ''
  await refresh()
}

async function saveThresholds() {
  if (configuration.value.class_a_min_cm <= configuration.value.class_b_min_cm) {
    error.value = 'Class A minimum must be greater than Class B minimum.'
    return
  }
  await request('/api/config/thresholds', { method: 'PUT', body: JSON.stringify({ class_a_min_cm: Number(configuration.value.class_a_min_cm), class_b_min_cm: Number(configuration.value.class_b_min_cm) }) })
  await refresh()
}

onMounted(() => { refresh(); connectLive(); clock = window.setInterval(() => { now.value = new Date() }, 1000) })
onBeforeUnmount(() => { socket?.close(); window.clearInterval(clock) })
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark">B</div><div><strong>Banagrade</strong><span>Edge operations</span></div></div>
      <nav aria-label="Primary navigation">
        <button v-for="view in views" :key="view" :class="['nav-button', { active: activeView === view }]" @click="activeView = view">{{ view }}</button>
      </nav>
      <div class="sidebar-status"><span class="status-dot" :class="health?.status === 'ok' ? 'online' : 'offline'"></span><span>{{ health?.status === 'ok' ? 'Backend online' : 'Backend unavailable' }}</span></div>
    </aside>

    <main class="main-content">
      <header class="topbar"><div><h1>{{ activeView }}</h1><p class="page-subtitle">{{ activeView === 'Overview' ? 'Live monitoring of Cardava banana quality grading' : activeView === 'Recent Scans' ? 'Traceability and AI grading history' : activeView === 'System Status' ? 'Hardware and pipeline diagnostics' : 'Banagrade edge operations console' }}</p></div><div class="header-context"><div><span>CURRENT SHIFT</span><strong>{{ activeSession ? 'Shift active' : 'No active session' }}</strong></div><div class="header-divider"></div><div class="connection"><span class="status-dot" :class="socketState === 'Connected' ? 'online' : 'offline'"></span>{{ socketState === 'Connected' ? 'System ready' : socketState }}</div><div class="header-divider"></div><div class="header-time"><span>{{ currentDate }}</span><strong>{{ currentTime }}</strong></div></div></header>
      <div v-if="error" class="alert" role="alert">{{ error }}</div>
      <section v-if="loading" class="loading">Loading operational data...</section>

      <template v-else>
        <section v-if="activeView === 'Overview'" class="content-grid">
          <div class="hero-panel"><div><p class="eyebrow">SYSTEM READINESS</p><h2>{{ health?.models?.available ? 'Models ready' : 'Awaiting pipeline' }}</h2><p>{{ health?.models?.error || 'The backend is online. Connect the camera pipeline to begin automatic inspection.' }}</p></div><div class="readiness-ring">{{ health?.models?.available ? 'READY' : 'STAGED' }}</div></div>
          <div class="kpi-grid"><article v-for="kpi in kpis" :key="kpi[0]" :class="['kpi-card', kpi[2]]"><span>{{ kpi[0] }}</span><strong>{{ kpi[1] }}</strong><small v-if="kpi[0] === 'Class A'">&ge; 12 cm length</small><small v-else-if="kpi[0] === 'Class B'">8&ndash;12 cm length</small><small v-else-if="kpi[0] === 'Commercial rejects'">&lt; 8 cm or unhealthy</small><small v-else>Cardava bananas scanned</small></article></div>
          <AnalyticsView :api-base="apiBase" />
          <div class="panel"><div class="panel-heading"><div><p class="eyebrow">RECENT ACTIVITY</p><h2>Latest scans</h2></div><button class="text-button" @click="activeView = 'Scan History'">View history</button></div><ScanTable :scans="scans.slice(0, 8)" @select="selectedScan = $event" /></div>
        </section>

        <section v-else-if="activeView === 'Recent Scans' || activeView === 'Scan History'" class="panel"><div class="panel-heading"><div><p class="eyebrow">AUDIT TRAIL</p><h2>Recent scans</h2></div><button class="icon-button" title="Refresh scans" @click="refresh">↻</button></div><ScanTable :scans="scans" @select="selectedScan = $event" /></section>

        <section v-else-if="activeView === 'Live Inspection'" class="content-grid two-column"><div class="hero-panel inspection"><p class="eyebrow">LIVE PIPELINE</p><h2>{{ liveEvent?.event_type || 'Waiting for scan events' }}</h2><p>{{ liveEvent?.timestamp || 'No live event received yet.' }}</p><div class="pipeline-steps"><span>Capture</span><span>Stage 1</span><span>Stage 2</span><span>Decision</span></div></div><div class="panel"><p class="eyebrow">LAST RESULT</p><h2>{{ selectedScan?.final_grade || 'No completed scan' }}</h2><p class="muted">{{ selectedScan?.calculated_length_cm ? `${selectedScan.calculated_length_cm} cm` : 'Awaiting measurement' }}</p></div></section>

        <section v-else-if="activeView === 'Sessions'" class="content-grid two-column"><div class="panel"><p class="eyebrow">SESSION CONTROL</p><h2>Start grading session</h2><textarea v-model="sessionNotes" placeholder="Optional session note"></textarea><button class="primary-button" @click="startSession">Start session</button></div><div class="panel"><p class="eyebrow">HISTORY</p><h2>Previous sessions</h2><div v-for="session in sessions" :key="session.id" class="list-row"><strong>{{ session.id.slice(0, 8) }}</strong><span>{{ session.status }}</span></div></div></section>

        <AnalyticsView v-else-if="activeView === 'Analytics'" :api-base="apiBase" />
        <section v-else-if="activeView === 'Calibration & Settings'" class="panel settings"><p class="eyebrow">CONFIGURATION</p><h2>Grade thresholds</h2><label>Class A minimum (cm)<input v-model.number="configuration.class_a_min_cm" type="number" min="0.01" step="0.1"></label><label>Class B minimum (cm)<input v-model.number="configuration.class_b_min_cm" type="number" min="0.01" step="0.1"></label><button class="primary-button" @click="saveThresholds">Save thresholds</button><div class="notice">Calibration activation requires a connected camera and validated physical reference measurement.</div></section>
        <section v-else-if="activeView === 'Hardware Diagnostics'" class="panel"><p class="eyebrow">HARDWARE</p><h2>Diagnostics unavailable</h2><p class="muted">GPIO controls and camera telemetry remain disabled until the Raspberry Pi hardware adapter is connected. The browser cannot control GPIO directly.</p><div class="notice">No physical LED state is being simulated.</div></section>
        <section v-else-if="activeView === 'System Status' || activeView === 'System Health'" class="content-grid two-column"><div class="panel"><p class="eyebrow">SERVICE STATUS</p><h2>{{ health?.status === 'ok' ? 'System ready' : 'Backend unavailable' }}</h2><p class="muted">WebSocket: {{ socketState }}</p></div><div class="panel"><p class="eyebrow">MODEL STATUS</p><h2>{{ health?.models?.available ? 'Models loaded' : 'Models staged' }}</h2><p class="muted">{{ health?.models?.error || 'No model error reported.' }}</p></div><div class="panel diagnostics-panel"><p class="eyebrow">HARDWARE DIAGNOSTICS</p><div class="diagnostic-row"><span><i class="status-dot offline"></i> Raspberry Pi 5</span><b>Unavailable</b></div><div class="diagnostic-row"><span><i class="status-dot offline"></i> Camera Module</span><b>Unavailable</b></div><div class="diagnostic-row"><span><i class="status-dot offline"></i> GPIO / LEDs</span><b>Unavailable</b></div></div></section>
        <section v-else-if="activeView === 'Reports'" class="panel"><p class="eyebrow">REPORTING</p><h2>Export operational data</h2><p class="muted">Download the current scan audit as CSV using the backend export endpoint.</p><a class="primary-button link-button" :href="`${apiBase}/api/exports/scans.csv`" download="banagrade-scans.csv">Download scan CSV</a></section>

        <SusEvaluation v-else-if="activeView === 'SUS Evaluation'" :api-base="apiBase" />
      </template>
    </main>
    <div v-if="selectedScan" class="drawer" @click.self="selectedScan = null"><div class="drawer-panel"><button class="close-button" @click="selectedScan = null">×</button><p class="eyebrow">SCAN DETAIL</p><h2>{{ selectedScan.scan_id }}</h2><dl><dt>Grade</dt><dd>{{ selectedScan.final_grade || 'Technical failure' }}</dd><dt>Health</dt><dd>{{ selectedScan.stage1_status || 'Unavailable' }}</dd><dt>Length</dt><dd>{{ selectedScan.calculated_length_cm ? `${selectedScan.calculated_length_cm} cm` : 'Unavailable' }}</dd><dt>Reason</dt><dd>{{ selectedScan.rejection_reason || 'None' }}</dd></dl></div></div>
  </div>
</template>