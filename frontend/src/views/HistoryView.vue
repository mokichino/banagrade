<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { request } from '../composables/useApi.js'
import { GRADE_FILTERS, isVoided, matchesGrade, matchesSearch } from '../lib/grades.js'
import { downloadScansCsv } from '../lib/csv.js'
import { plural, scopeDescription, scopeQuery, scopeTitle } from '../lib/shifts.js'
import FileIcon from '../components/FileIcon.vue'
import ScanTable from '../components/ScanTable.vue'
import ShiftSelect from '../components/ShiftSelect.vue'

const LIMIT = 5000
const PAGE_SIZE = 50

const props = defineProps({ refreshKey: { type: Number, default: 0 } })
const emit = defineEmits(['dispute', 'select', 'void', 'error'])
// Shared with the Dashboard through App, so "View all scans" opens the shift that was on screen.
const scope = defineModel('scope', { type: String, default: 'active' })

const scans = ref([])
const shifts = ref([])
const loading = ref(true)
const search = ref('')
const gradeFilter = ref('All')
const page = ref(1)
const exporting = ref(false)

const filtering = computed(() => Boolean(search.value.trim()) || gradeFilter.value !== 'All')
const filtered = computed(() => scans.value.filter(scan => matchesSearch(scan, search.value) && matchesGrade(scan, gradeFilter.value)))
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const pageRows = computed(() => filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))
const truncated = computed(() => scans.value.length >= LIMIT)
const listedVoided = computed(() => filtered.value.filter(isVoided))
const listedCounting = computed(() => filtered.value.filter(scan => !isVoided(scan)))
// Voiding a batch (a test run, say) is offered once the list is narrowed to a shift or a filter, never for all history at once.
const batchVoid = computed(() => listedCounting.value.length > 1 && (scope.value !== 'all' || filtering.value))

const countText = computed(() => {
  if (loading.value) return 'Loading…'
  const total = filtered.value.length
  const shown = total > PAGE_SIZE ? `Showing ${((page.value - 1) * PAGE_SIZE + 1).toLocaleString()}–${Math.min(page.value * PAGE_SIZE, total).toLocaleString()} · ` : ''
  const voided = gradeFilter.value === 'All' && listedVoided.value.length ? ` · ${listedVoided.value.length.toLocaleString()} voided` : ''
  return shown + (filtering.value ? `${total.toLocaleString()} of ${plural(scans.value.length, 'scan')} match` : plural(total, 'scan')) + voided
})
const emptyText = computed(() => {
  if (loading.value) return 'Loading scans…'
  if (filtering.value && scans.value.length) return 'No scans match the search and grade filter.'
  if (scope.value === 'active') return 'No scans in the current shift yet. Choose All shifts to see earlier scans.'
  return scope.value === 'all' ? 'No scans recorded yet.' : 'This shift has no scans.'
})

async function load() {
  try {
    const query = scopeQuery(scope.value)
    const [scanData, shiftData] = await Promise.all([
      request(`/api/inspection/scans?limit=${LIMIT}${query ? `&${query}` : ''}`),
      request('/api/sessions')
    ])
    scans.value = scanData.items
    shifts.value = shiftData.items
  } catch (error) {
    emit('error', `Scan history unavailable: ${error.message}`)
  } finally { loading.value = false }
}

function clearFilters() {
  search.value = ''
  gradeFilter.value = 'All'
}

async function exportPdf() {
  exporting.value = true
  try {
    const { downloadScansPdf } = await import('../lib/pdf.js')
    downloadScansPdf(filtered.value, { filter: gradeFilter.value, search: search.value, shift: scopeDescription(scope.value, shifts.value) })
  } catch (error) { emit('error', `PDF export failed: ${error.message}`) } finally { exporting.value = false }
}

onMounted(load)
watch(() => props.refreshKey, load)
watch(scope, load)
watch([search, gradeFilter, scope], () => { page.value = 1 })
watch(pages, count => { page.value = Math.min(page.value, count) })
</script>

<template>
  <section class="panel">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">Audit trail</p>
        <h2>{{ scopeTitle(scope, shifts) }}</h2>
        <p class="muted">Every scan with its time, model confidence and final grade. Select a Scan ID for details, or the flag to correct a grade.</p>
      </div>
    </div>
    <div class="history-controls">
      <input v-model="search" type="search" aria-label="Search by Scan ID or time" placeholder="Search Scan ID or time">
      <ShiftSelect v-model="scope" :shifts="shifts" />
      <select v-model="gradeFilter" aria-label="Filter by grade">
        <option v-for="option in GRADE_FILTERS" :key="option" :value="option">{{ option === 'All' ? 'All grades' : option }}</option>
      </select>
      <div class="export-actions" role="group" aria-label="Export the scans listed">
        <button class="secondary-button export-button" :disabled="exporting || !filtered.length" :aria-busy="exporting" :aria-label="exporting ? 'Preparing PDF' : 'Export PDF'" :title="exporting ? 'Preparing PDF…' : 'Export PDF: the scans listed, with the search and grade filter applied'" @click="exportPdf"><FileIcon type="pdf" /></button>
        <button class="secondary-button export-button" :disabled="!filtered.length" aria-label="Export CSV" title="Export CSV: the scans listed, with every stored field" @click="downloadScansCsv(filtered)"><FileIcon type="csv" /></button>
      </div>
    </div>
    <div class="result-bar">
      <p class="muted small result-count" aria-live="polite">{{ countText }}</p>
      <button v-if="filtering" class="text-button" @click="clearFilters">Clear filters</button>
      <button v-if="gradeFilter === 'Voided' && listedVoided.length > 1" class="text-button batch-action" @click="$emit('void', { scans: listedVoided, restore: true })">Count all {{ listedVoided.length.toLocaleString() }} again…</button>
      <button v-else-if="batchVoid" class="text-button batch-action" @click="$emit('void', { scans: listedCounting, restore: false })">Void all {{ listedCounting.length.toLocaleString() }} listed…</button>
    </div>
    <ScanTable :scans="pageRows" :empty-text="emptyText" @select="$emit('select', $event)" @dispute="$emit('dispute', $event)" @void="$emit('void', $event)" />
    <p v-if="truncated" class="muted small table-note">Only the newest {{ LIMIT.toLocaleString() }} scans are loaded. Choose one shift to see older ones.</p>
    <nav v-if="pages > 1" class="pager" aria-label="Scan pages">
      <button class="secondary-button" :disabled="page === 1" @click="page -= 1">Previous</button>
      <span class="muted small tabular">Page {{ page }} of {{ pages }}</span>
      <button class="secondary-button" :disabled="page === pages" @click="page += 1">Next</button>
    </nav>
  </section>
</template>
