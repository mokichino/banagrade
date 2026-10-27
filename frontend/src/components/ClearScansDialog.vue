<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { request } from '../composables/useApi.js'
import { plural } from '../lib/shifts.js'

const props = defineProps({ open: { type: Boolean, default: false }, scanCount: { type: Number, default: 0 } })
const emit = defineEmits(['close', 'cleared'])
const typed = ref('')
const busy = ref(false)
const result = ref(null)
const error = ref('')
const input = ref(null)
const ready = computed(() => typed.value.trim().toUpperCase() === 'CLEAR')

watch(() => props.open, async open => {
  if (!open) return
  typed.value = ''
  result.value = null
  error.value = ''
  await nextTick()
  input.value?.focus()
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
        <p class="muted">This deletes all {{ plural(scanCount, 'scan') }} from every shift, with their disputes, saved photos and the past shifts, then starts a new shift. A verified backup of the database is saved first. Retraining copies of disputed photos are kept.</p>
        <label>Type CLEAR to confirm<input ref="input" v-model="typed" autocomplete="off" spellcheck="false" placeholder="CLEAR"></label>
        <div class="modal-actions">
          <button type="button" class="secondary-button" :disabled="busy" @click="close">Cancel</button>
          <button class="primary-button danger" :disabled="busy || !ready">{{ busy ? 'Clearing…' : `Delete ${plural(scanCount, 'scan')}` }}</button>
        </div>
      </template>
      <template v-else>
        <p class="ok">Cleared {{ plural(result.scans, 'scan') }}, {{ plural(result.disputes, 'dispute') }}, {{ plural(result.frames, 'photo') }} and {{ plural(result.shifts ?? 0, 'shift') }}. A new shift has started.</p>
        <p class="muted small">Backup: <span class="mono">{{ result.backup }}</span></p>
        <div class="modal-actions"><button type="button" class="primary-button" @click="close">Done</button></div>
      </template>
      <p v-if="error" class="bad small" role="alert">{{ error }}</p>
    </form>
  </div>
</template>
