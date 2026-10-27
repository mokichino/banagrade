<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiBase, request } from '../composables/useApi.js'
import { GRADE_FILTERS, matchesGrade, matchesSearch, shiftLabel } from '../lib/grades.js'
import ScanTable from '../components/ScanTable.vue'
import ClearScansDialog from '../components/ClearScansDialog.vue'
import ShiftSelect from '../components/ShiftSelect.vue'

const props = defineProps({ refreshKey: { type: Number, default: 0 } })
const emit = defineEmits(['dispute', 'select', 'error'])

const scans = ref([])
const loading = ref(true)
const search = ref('')
const gradeFilter = ref('All')
const exporting = ref(false)
const clearing = ref(false)
const shift = ref('all')
const shifts = ref([])
const shiftQuery = computed(() => (shift.value === 'all' ? '' : `session=${encodeURIComponent(shift.value)}`))
const shiftName = computed(() => {
  if (shift.value === 'all') return 'All shifts'
  const found = shifts.value.find(item => (shift.value === 'active' ? item.status === 'open' : item.id === shift.value))
  return found ? shiftLabel(found) : 'Current shift'
})
// Clearing deletes every shift's scans, not just the ones shown.
const allScans = computed(() => (shift.value === 'all' ? scans.value.length : shifts.value.reduce((total, item) => total + (item.scan_count || 0), 0)))
const filtered = computed(() => scans.value.filter(scan => matchesSearch(scan, search.value) && matchesGrade(scan, gradeFilter.value)))

async function load() {
  try {
    const [scanData, shiftData] = await Promise.all([
      request(`/api/inspection/scans?limit=5000${shiftQuery.value ? '&' + shiftQuery.value : ''}`),
      request('/api/sessions')
    ])
    scans.value = scanData.items
    shifts.value = shiftData.items
  } catch (error) {
    emit('error', `Scan history unavailable: ${error.message}`)
  } finally { loading.value = false }
}

async function downloadPdf() {
  exporting.value = true
  try {
    const { downloadScansPdf } = await import('../lib/pdf.js')
    downloadScansPdf(filtered.value, { filter: gradeFilter.value, search: search.value, shift: shiftName.value })
  } catch (error) { emit('error', `PDF export failed: ${error.message}`) } finally { exporting.value = false }
}

onMounted(load)
watch(() => props.refreshKey, load)
watch(shift, load)
</script>

<template>
  <section class="panel">
    <div class="panel-heading history-heading">
      <div><p class="eyebrow">Audit trail</p><h2>Recent scans</h2><p class="muted">Every scan is stored in banagrade.db with its timestamp, model confidences and final grade.</p></div>
      <button class="secondary-button danger-outline" :disabled="!allScans" @click="clearing = true">Clear all scans</button>
    </div>
    <div class="history-controls">
      <input v-model="search" type="search" aria-label="Search by Scan ID or timestamp" placeholder="Search Scan ID or timestamp">
      <ShiftSelect v-model="shift" :shifts="shifts" />
      <select v-model="gradeFilter" aria-label="Filter by grade">
        <option v-for="option in GRADE_FILTERS" :key="option" :value="option">{{ option === 'All' ? 'All grades' : option }}</option>
      </select>
      <button class="primary-button" :disabled="exporting || !filtered.length" @click="downloadPdf">{{ exporting ? 'Preparing…' : 'Download PDF' }}</button>
      <a class="secondary-button link-button" :href="`${apiBase}/api/exports/scans.csv${shiftQuery ? '?' + shiftQuery : ''}`">CSV</a>
    </div>
    <p class="muted small result-count">{{ loading ? 'Loading…' : `${filtered.length} of ${scans.length} records` }}</p>
    <ScanTable :scans="filtered" @select="$emit('select', $event)" @dispute="$emit('dispute', $event)" />
    <ClearScansDialog :open="clearing" :scan-count="allScans" @close="clearing = false" @cleared="load" />
  </section>
</template>
