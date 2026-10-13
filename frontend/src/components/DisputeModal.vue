<script setup>
import { ref, watch } from 'vue'
import { request } from '../composables/useApi.js'
import { finalGradeLabel, scanLabel } from '../lib/grades.js'

const props = defineProps({ scan: { type: Object, default: null } })
const emit = defineEmits(['close', 'saved', 'error'])
const correctedGrade = ref('')
const reason = ref('')
const saving = ref(false)

watch(() => props.scan, scan => { correctedGrade.value = scan?.final_grade || 'Rejected'; reason.value = '' })

async function submit() {
  saving.value = true
  try {
    await request(`/api/inspection/scans/${props.scan.scan_id}/dispute`, { method: 'POST', body: JSON.stringify({ reason: reason.value || null, corrected_grade: correctedGrade.value }) })
    emit('saved')
  } catch (error) { emit('error', `Unable to save dispute: ${error.message}`) } finally { saving.value = false }
}
</script>

<template>
  <div v-if="scan" class="modal-backdrop" @click.self="$emit('close')" @keydown.esc="$emit('close')">
    <form class="modal panel" role="dialog" aria-modal="true" aria-labelledby="dispute-title" @submit.prevent="submit">
      <button type="button" class="close-button" aria-label="Close" @click="$emit('close')">×</button>
      <p class="eyebrow">Operator correction</p>
      <h2 id="dispute-title">Dispute grade</h2>
      <p class="muted">{{ scanLabel(scan.scan_id) }} · Recorded: {{ finalGradeLabel(scan) }}</p>
      <label>Correct grade
        <select v-model="correctedGrade"><option>Class A</option><option>Class B</option><option>Rejected</option><option>Technical Failure</option></select>
      </label>
      <label>Reason<textarea v-model="reason" required placeholder="Describe why the grade is incorrect"></textarea></label>
      <div class="modal-actions">
        <button type="button" class="secondary-button" @click="$emit('close')">Cancel</button>
        <button class="primary-button" :disabled="saving">{{ saving ? 'Saving…' : 'Save correction' }}</button>
      </div>
    </form>
  </div>
</template>
