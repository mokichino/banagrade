<script setup>
import { ref, watch } from 'vue'
import { request } from '../composables/useApi.js'
import { plural, shiftDuration, shiftStart } from '../lib/shifts.js'

const props = defineProps({ open: { type: Boolean, default: false }, current: { type: Object, default: null } })
const emit = defineEmits(['close', 'ended'])
const busy = ref(false)
const error = ref('')

watch(() => props.open, open => { if (open) error.value = '' })

async function end() {
  busy.value = true
  error.value = ''
  try {
    await request(`/api/sessions/${encodeURIComponent(props.current.id)}/close`, { method: 'POST' })
    emit('ended', props.current)
  } catch (failure) { error.value = `Unable to end the shift: ${failure.message}` } finally { busy.value = false }
}

function close() {
  if (!busy.value) emit('close')
}
</script>

<template>
  <div v-if="open && current" class="modal-backdrop" @click.self="close" @keydown.esc="close">
    <form class="modal panel" role="dialog" aria-modal="true" aria-labelledby="end-shift-title" @submit.prevent="end">
      <button type="button" class="close-button" aria-label="Close" @click="close">×</button>
      <p class="eyebrow">Shift</p>
      <h2 id="end-shift-title">End this shift?</h2>
      <p v-if="current.scan_count" class="muted">The shift that started {{ shiftStart(current) }} ends now, after {{ shiftDuration(current) }} and {{ plural(current.scan_count, 'scan') }}. It moves to Past shifts with its totals and CPU temperature, which stops being recorded.</p>
      <p v-else class="muted">The shift that started {{ shiftStart(current) }} has no scans, so it is not kept under Past shifts.</p>
      <p class="form-hint">The next bunch scanned, or Start new shift, opens a new one.</p>
      <div class="modal-actions">
        <button type="button" class="secondary-button" :disabled="busy" @click="close">Cancel</button>
        <button class="primary-button" :disabled="busy">{{ busy ? 'Ending…' : 'End shift' }}</button>
      </div>
      <p v-if="error" class="bad small" role="alert">{{ error }}</p>
    </form>
  </div>
</template>
