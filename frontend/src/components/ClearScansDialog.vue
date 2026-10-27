<script setup>
import { computed, ref, watch } from 'vue'
import { request } from '../composables/useApi.js'

const props = defineProps({ open: { type: Boolean, default: false }, scanCount: { type: Number, default: 0 } })
const emit = defineEmits(['close', 'cleared'])
const typed = ref('')
const busy = ref(false)
const result = ref(null)
const error = ref('')
const ready = computed(() => typed.value.trim().toUpperCase() === 'CLEAR')

watch(() => props.open, open => {
  if (!open) return
  typed.value = ''
  result.value = null
  error.value = ''
})

async function clear() {
  busy.value = true
  error.value = ''
  try {
    result.value = await request('/api/inspection/scans/clear', { method: 'POST', body: JSON.stringify({ confirm: 'CLEAR' }) })
    emit('cleared', result.value)
  } catch (failure) { error.value = `Unable to clear scans: ${failure.message}` } finally { busy.value = false }
}

function close() {
  if (!busy.value) emit('close')
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" @click.self="close" @keydown.esc="close">
    <form class="modal panel" role="dialog" aria-modal="true" aria-labelledby="clear-title" @submit.prevent="ready && !result && clear()">
      <button type="button" class="close-button" aria-label="Close" @click="close">×</button>
      <p class="eyebrow">Test data</p>
      <h2 id="clear-title">Clear all scans</h2>
      <template v-if="!result">
        <p class="muted">This deletes all {{ scanCount }} scans with their disputes and saved photos, closes the current shift and opens a new one. A backup of the database is saved first. Retraining copies of disputed photos are kept.</p>
        <label>Type CLEAR to confirm<input v-model="typed" autocomplete="off" spellcheck="false" placeholder="CLEAR"></label>
        <div class="modal-actions">
          <button type="button" class="secondary-button" :disabled="busy" @click="close">Cancel</button>
          <button class="primary-button danger" :disabled="busy || !ready">{{ busy ? 'Clearing…' : `Delete ${scanCount} scans` }}</button>
        </div>
      </template>
      <template v-else>
        <p class="ok">Cleared {{ result.scans }} scans, {{ result.disputes }} disputes and {{ result.frames }} photos. A new shift has started.</p>
        <p class="muted small">Backup: <span class="mono">{{ result.backup }}</span></p>
        <div class="modal-actions"><button type="button" class="primary-button" @click="close">Done</button></div>
      </template>
      <p v-if="error" class="bad small">{{ error }}</p>
    </form>
  </div>
</template>
