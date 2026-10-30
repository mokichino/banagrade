<script setup>
import { computed, ref, watch } from 'vue'
import { request } from '../composables/useApi.js'
import { formatTimestamp, scanLabel } from '../lib/grades.js'

const props = defineProps({ scan: { type: Object, default: null } })
const emit = defineEmits(['close', 'saved', 'changed', 'error'])
const correctedGrade = ref('')
const reason = ref('')
const saving = ref(false)
// The recorded grade in the form's own terms: a null final_grade is 'Technical Failure'.
const recorded = ref(null)
const disputes = ref([])
const confirming = ref(false)
const deleting = ref(false)

const gradeName = grade => (grade === 'Technical Failure' || !grade ? 'Technical failure' : grade)
const unchanged = computed(() => correctedGrade.value === recorded.value)
const sizeCorrection = computed(() => !unchanged.value && ['Class A', 'Class B'].includes(correctedGrade.value))
// Disputes come newest first; the oldest one holds the grade the scanner gave.
const scannerGrade = computed(() => disputes.value.findLast(dispute => dispute.original_grade)?.original_grade)
const reasonExample = computed(() => (sizeCorrection.value ? `${correctedGrade.value} by size: middle finger 12.5 cm, outer curve, tip to stalk joint` : 'Describe why the grade is incorrect'))

async function loadDisputes(scanId) {
  try {
    disputes.value = (await request(`/api/inspection/scans/${scanId}/disputes`)).items
  } catch (error) { disputes.value = []; emit('error', `Unable to load disputes: ${error.message}`) }
}

watch(() => props.scan, scan => {
  correctedGrade.value = ''
  reason.value = ''
  recorded.value = scan ? scan.final_grade || 'Technical Failure' : null
  disputes.value = []
  confirming.value = false
  if (scan) loadDisputes(scan.scan_id)
})

async function submit() {
  saving.value = true
  try {
    await request(`/api/inspection/scans/${props.scan.scan_id}/dispute`, { method: 'POST', body: JSON.stringify({ reason: reason.value || null, corrected_grade: correctedGrade.value }) })
    emit('saved')
  } catch (error) {
    emit('error', `Unable to save dispute: ${error.message}`)
    if (error.status === 409) emit('changed')  // a stale list, e.g. the shift ended since it loaded
  } finally { saving.value = false }
}

async function deleteDisputes() {
  deleting.value = true
  try {
    const result = await request(`/api/inspection/scans/${props.scan.scan_id}/disputes`, { method: 'DELETE' })
    recorded.value = result.final_grade || 'Technical Failure'
    correctedGrade.value = ''
    confirming.value = false
    disputes.value = []
    emit('changed')
  } catch (error) {
    emit('error', `Unable to delete disputes: ${error.message}`)
    if (error.status === 409) emit('changed')
  } finally { deleting.value = false }
}
</script>

<template>
  <div v-if="scan" class="modal-backdrop" @click.self="$emit('close')" @keydown.esc="$emit('close')">
    <form class="modal panel" role="dialog" aria-modal="true" aria-labelledby="dispute-title" @submit.prevent="submit">
      <button type="button" class="close-button" aria-label="Close" @click="$emit('close')">×</button>
      <p class="eyebrow">Operator correction</p>
      <h2 id="dispute-title">Dispute grade</h2>
      <p class="muted">{{ scanLabel(scan.scan_id) }} · Recorded: {{ gradeName(recorded) }}</p>
      <label>Correct grade
        <select v-model="correctedGrade" required><option value="" disabled>Choose the correct grade</option><option>Class A</option><option>Class B</option><option>Rejected</option><option>Technical Failure</option></select>
      </label>
      <p v-if="unchanged" class="form-error">This scan is already recorded as {{ gradeName(recorded) }}. Choose a different grade.</p>
      <p v-else-if="sizeCorrection" class="form-hint">Give the measured finger length: the middle finger of the outer row, along its outer curve, from the tip to where the stalk joins. Class A is 12 cm or more.</p>
      <label>Reason<textarea v-model="reason" required :placeholder="reasonExample"></textarea></label>
      <div class="modal-actions">
        <button type="button" class="secondary-button" @click="$emit('close')">Cancel</button>
        <button class="primary-button" :disabled="saving || !correctedGrade || unchanged">{{ saving ? 'Saving…' : 'Save correction' }}</button>
      </div>

      <section v-if="disputes.length" class="dispute-history" aria-label="Earlier disputes">
        <div class="dispute-history-heading">
          <h3>Earlier disputes ({{ disputes.length }})</h3>
          <button v-if="!confirming" type="button" class="text-button dispute-button" @click="confirming = true">Delete disputes</button>
        </div>
        <div v-if="confirming" class="dispute-confirm">
          <span v-if="scannerGrade">Delete {{ disputes.length === 1 ? 'this dispute' : `all ${disputes.length} disputes` }}? The grade goes back to {{ gradeName(scannerGrade) }}, the scanner's own grade.</span>
          <span v-else>Delete {{ disputes.length === 1 ? 'this dispute' : `all ${disputes.length} disputes` }}? The grade stays {{ gradeName(recorded) }}: these disputes are too old to know the scanner's grade.</span>
          <button type="button" class="text-button dispute-button" :disabled="deleting" @click="deleteDisputes">{{ deleting ? 'Deleting…' : 'Delete' }}</button>
          <button type="button" class="text-button" @click="confirming = false">Keep</button>
        </div>
        <ul>
          <li v-for="dispute in disputes" :key="dispute.id">
            <div class="dispute-body">
              <strong>{{ gradeName(dispute.original_grade) }} → {{ dispute.corrected_grade ? gradeName(dispute.corrected_grade) : 'no grade change' }}</strong>
              <small class="tabular">{{ formatTimestamp(dispute.created_at) }}</small>
              <p v-if="dispute.reason">{{ dispute.reason }}</p>
            </div>
          </li>
        </ul>
      </section>
    </form>
  </div>
</template>
