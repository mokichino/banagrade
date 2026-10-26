<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppHeader from './components/layout/AppHeader.vue'
import AppSidebar from './components/layout/AppSidebar.vue'
import DisputeModal from './components/DisputeModal.vue'
import PowerDialog from './components/PowerDialog.vue'
import ScanDrawer from './components/ScanDrawer.vue'
import { request } from './composables/useApi.js'
import { useLive } from './composables/useLive.js'
import DashboardView from './views/DashboardView.vue'
import HistoryView from './views/HistoryView.vue'
import SystemStatusView from './views/SystemStatusView.vue'

const views = [
  { id: 'dashboard', label: 'Live Dashboard', subtitle: 'Live monitoring of Cardava banana grading for packinghouse supervisors' },
  { id: 'history', label: 'Recent Scans', subtitle: 'Audit log and traceability for every graded bunch' },
  { id: 'status', label: 'System Status', subtitle: 'Camera, edge device, GPIO and AI model health' }
]
const viewFromHash = () => (views.some(view => `#/${view.id}` === window.location.hash) ? window.location.hash.slice(2) : 'dashboard')
const activeView = ref(viewFromHash())
const current = computed(() => views.find(view => view.id === activeView.value))
const error = ref('')
const refreshKey = ref(0)
const selectedScan = ref(null)
const disputeScan = ref(null)
const powerOpen = ref(false)

const demo = ref({ mode: false, data_present: false })
async function loadDemoFlag() {
  try { demo.value = (await request('/api/system/status')).demo || demo.value } catch { /* header label is optional */ }
}

const { connection, led } = useLive(() => { refreshKey.value += 1; if (!demo.value.data_present) loadDemoFlag() })

function syncFromHash() { activeView.value = viewFromHash() }
onMounted(() => { window.addEventListener('hashchange', syncFromHash); loadDemoFlag() })
onBeforeUnmount(() => window.removeEventListener('hashchange', syncFromHash))

function navigate(id) {
  activeView.value = id
  if (window.location.hash !== `#/${id}`) window.location.hash = `/${id}`
  error.value = ''
  window.scrollTo({ top: 0 })
}

function onDisputeSaved() {
  disputeScan.value = null
  refreshKey.value += 1
}
</script>

<template>
  <div class="app-shell">
    <AppSidebar :views="views" :active="activeView" :led="led" @navigate="navigate" @power="powerOpen = true" />
    <main class="main-content">
      <AppHeader :title="current.label" :subtitle="current.subtitle" :led="led" :connection="connection" :demo="demo.data_present || demo.mode" />
      <div v-if="error" class="alert" role="alert"><span>{{ error }}</span><button class="text-button" aria-label="Dismiss" @click="error = ''">Dismiss</button></div>
      <DashboardView v-if="activeView === 'dashboard'" :refresh-key="refreshKey" @navigate="navigate" @select="selectedScan = $event" @dispute="disputeScan = $event" @error="error = $event" />
      <HistoryView v-else-if="activeView === 'history'" :refresh-key="refreshKey" @select="selectedScan = $event" @dispute="disputeScan = $event" @error="error = $event" />
      <SystemStatusView v-else-if="activeView === 'status'" :led="led" @error="error = $event" />
    </main>
    <ScanDrawer :scan="selectedScan" @close="selectedScan = null" />
    <DisputeModal :scan="disputeScan" @close="disputeScan = null" @saved="onDisputeSaved" @error="error = $event" />
    <PowerDialog :open="powerOpen" @close="powerOpen = false" />
  </div>
</template>
