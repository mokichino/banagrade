<script setup>
import { ref, watch } from 'vue'
import { request } from '../composables/useApi.js'
import { finalGradeLabel, formatTimestamp, scanLabel } from '../lib/grades.js'

const props = defineProps({ scan: { type: Object, default: null } })
const emit = defineEmits(['close', 'saved', 'changed', 'error'])
const correctedGrade = ref('')
const reason = ref('')
const saving = ref(false)
const recorded = ref(null)
const disputes = ref([])
const confirmingId = ref(null)
const deletingId = ref(null)

const gradeName = grade => (grade === 'Technical Failure' || !grade ? 'Technical failure' : grade)

async function loadDisputes(scanId) {
  try {
    disputes.value = (await request(`/api/inspection/scans/${scanId}/disputes`)).items
  } catch (error) { disputes.value = []; emit('error', `Unable to load disputes: ${error.message}`) }
}

watch(() => props.scan, scan => {
  correctedGrade.value = scan?.final_grade || 'Rejected'
  reason.value = ''
  recorded.value = scan ? finalGradeLabel(scan) : null
  disputes.value = []
  confirmingId.value = null
  if (scan) loadDisputes(scan.scan_id)
})

async function submit() {
  saving.value = true
  try {
    await request(`/api/inspection/scans/${props.scan.scan_id}/dispute`, { method: 'POST', body: JSON.stringify({ reason: reason.value || null, corrected_grade: correctedGrade.value }) })
    emit('saved')
  } catch (error) { emit('error', `Unable to save dispute: ${error.message}`) } finally { saving.value = false }
}

async function deleteDispute(dispute) {
  deletingId.value = dispute.id
  try {
    const result = await request(`/api/inspection/scans/${props.scan.scan_id}/disputes/${dispute.id}`, { method: 'DELETE' })
    recorded.value = gradeName(result.final_grade)
    correctedGrade.value = result.final_grade || 'Rejected'
    confirmingId.value = null
    await loadDisputes(props.scan.scan_id)
    emit('changed')
  } catch (error) { emit('error', `Unable to delete dispute: ${error.message}`) } finally { deletingId.value = null }
}
</script>

<template>
  <div v-if="scan" class="modal-backdrop" @click.self="$emit('close')" @keydown.esc="$emit('close')">
    <form class="modal panel" role="dialog" aria-modal="true" aria-labelledby="dispute-title" @submit.prevent="submit">
      <button type="button" class="close-button" aria-label="Close" @click="$emit('close')">×</button>
      <p class="eyebrow">Operator correction</p>
      <h2 id="dispute-title">Dispute grade</h2>
      <p class="muted">{{ scanLabel(scan.scan_id) }} · Recorded: {{ recorded }}</p>
      <label>Correct grade
        <select v-model="correctedGrade"><option>Class A</option><option>Class B</option><option>Rejected</option><option>Technical Failure</option></select>
      </label>
      <label>Reason<textarea v-model="reason" required placeholder="Describe why the grade is incorrect"></textarea></label>
      <div class="modal-actions">
        <button type="button" class="secondary-button" @click="$emit('close')">Cancel</button>
        <button class="primary-button" :disabled="saving">{{ saving ? 'Saving…' : 'Save correction' }}</button>
      </div>

      <section v-if="disputes.length" class="dispute-history" aria-label="Earlier disputes">
        <h3>Earlier disputes ({{ disputes.length }})</h3>
        <ul>
          <li v-for="dispute in disputes" :key="dispute.id">
            <div class="dispute-body">
              <strong>{{ gradeName(dispute.original_grade) }} → {{ dispute.corrected_grade ? gradeName(dispute.corrected_grade) : 'no grade change' }}</strong>
              <small class="tabular">{{ formatTimestamp(dispute.created_at) }}</small>
              <p v-if="dispute.reason">{{ dispute.reason }}</p>
              <div v-if="confirmingId === dispute.id" class="dispute-confirm">
                <span>Delete this dispute? The grade goes back to the one before it.</span>
                <button type="button" class="text-button dispute-button" :disabled="deletingId === dispute.id" @click="deleteDispute(dispute)">{{ deletingId === dispute.id ? 'Deleting…' : 'Delete' }}</button>
                <button type="button" class="text-button" @click="confirmingId = null">Keep</button>
              </div>
            </div>
            <button v-if="confirmingId !== dispute.id" type="button" class="icon-button delete-button" title="Delete dispute" aria-label="Delete dispute" @click="confirmingId = dispute.id">
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v6" /><path d="M14 11v6" /></svg>
            </button>
          </li>
        </ul>
      </section>
    </form>
  </div>
</template>
