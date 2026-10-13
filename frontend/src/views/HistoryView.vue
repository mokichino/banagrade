<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiBase, request } from '../composables/useApi.js'
import { GRADE_FILTERS, matchesGrade, matchesSearch } from '../lib/grades.js'
import ScanTable from '../components/ScanTable.vue'

const props = defineProps({ refreshKey: { type: Number, default: 0 } })
const emit = defineEmits(['dispute', 'select', 'error'])

const scans = ref([])
const loading = ref(true)
const search = ref('')
const gradeFilter = ref('All')
const exporting = ref(false)
const filtered = computed(() => scans.value.filter(scan => matchesSearch(scan, search.value) && matchesGrade(scan, gradeFilter.value)))

async function load() {
  try {
    scans.value = (await request('/api/inspection/scans?limit=5000')).items
  } catch (error) {
    emit('error', `Scan history unavailable: ${error.message}`)
  } finally { loading.value = false }
}

async function downloadPdf() {
  exporting.value = true
  try {
    const { downloadScansPdf } = await import('../lib/pdf.js')
    downloadScansPdf(filtered.value, { filter: gradeFilter.value, search: search.value })
  } catch (error) { emit('error', `PDF export failed: ${error.message}`) } finally { exporting.value = false }
}

onMounted(load)
watch(() => props.refreshKey, load)
</script>

<template>
  <section class="panel">
    <div class="panel-heading history-heading">
      <div><p class="eyebrow">Audit trail</p><h2>Recent scans</h2><p class="muted">Every scan is stored in banagrade.db with its timestamp, model confidences and final grade.</p></div>
    </div>
    <div class="history-controls">
      <input v-model="search" type="search" aria-label="Search by Scan ID or timestamp" placeholder="Search Scan ID or timestamp">
      <select v-model="gradeFilter" aria-label="Filter by grade">
        <option v-for="option in GRADE_FILTERS" :key="option" :value="option">{{ option === 'All' ? 'All grades' : option }}</option>
      </select>
      <button class="primary-button" :disabled="exporting || !filtered.length" @click="downloadPdf">{{ exporting ? 'Preparing…' : 'Download PDF' }}</button>
      <a class="secondary-button link-button" :href="`${apiBase}/api/exports/scans.csv`">CSV</a>
    </div>
    <p class="muted small result-count">{{ loading ? 'Loading…' : `${filtered.length} of ${scans.length} records` }}</p>
    <ScanTable :scans="filtered" @select="$emit('select', $event)" @dispute="$emit('dispute', $event)" />
  </section>
</template>
