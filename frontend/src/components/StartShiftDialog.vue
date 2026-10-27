<script setup>
import { nextTick, ref, watch } from 'vue'
import { request } from '../composables/useApi.js'
import { plural, shiftStart } from '../lib/shifts.js'

const props = defineProps({ open: { type: Boolean, default: false }, current: { type: Object, default: null } })
const emit = defineEmits(['close', 'started'])
const name = ref('')
const busy = ref(false)
const error = ref('')
const input = ref(null)

watch(() => props.open, async open => {
  if (!open) return
  name.value = ''
  error.value = ''
  await nextTick()
  input.value?.focus()
})

async function start() {
  busy.value = true
  error.value = ''
  try {
    emit('started', await request('/api/sessions', { method: 'POST', body: JSON.stringify({ name: name.value.trim() || null }) }))
  } catch (failure) { error.value = `Unable to start a shift: ${failure.message}` } finally { busy.value = false }
}

function close() {
  if (!busy.value) emit('close')
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" @click.self="close" @keydown.esc="close">
    <form class="modal panel" role="dialog" aria-modal="true" aria-labelledby="shift-title" @submit.prevent="start">
      <button type="button" class="close-button" aria-label="Close" @click="close">×</button>
      <p class="eyebrow">Shift</p>
      <h2 id="shift-title">Start a new shift</h2>
      <p v-if="current?.scan_count" class="muted">The current shift (started {{ shiftStart(current) }}, {{ plural(current.scan_count, 'scan') }}) ends now and moves to Past shifts with its totals. Scans from now on count toward the new shift.</p>
      <p v-else-if="current" class="muted">The current shift has no scans, so it is not kept under Past shifts. Scans from now on count toward the new shift.</p>
      <p v-else class="muted">No shift is open. Scans from now on count toward the new shift.</p>
      <label><span>Name <span class="optional">(optional)</span></span>
        <input ref="input" v-model="name" maxlength="80" placeholder="e.g. Toril batch" autocomplete="off">
      </label>
      <p class="form-hint">Without a name, the shift is listed by when it ran.</p>
      <div class="modal-actions">
        <button type="button" class="secondary-button" :disabled="busy" @click="close">Cancel</button>
        <button class="primary-button" :disabled="busy">{{ busy ? 'Starting…' : 'Start shift' }}</button>
      </div>
      <p v-if="error" class="bad small" role="alert">{{ error }}</p>
    </form>
  </div>
</template>
