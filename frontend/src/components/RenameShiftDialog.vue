<script setup>
import { nextTick, ref, watch } from 'vue'
import { request } from '../composables/useApi.js'
import { shiftDate } from '../lib/shifts.js'

// Shifts start and end on their own, one per day; naming today's (a batch, say) is all the dashboard does to one.
const props = defineProps({ open: { type: Boolean, default: false }, current: { type: Object, default: null } })
const emit = defineEmits(['close', 'renamed'])
const name = ref('')
const busy = ref(false)
const error = ref('')
const input = ref(null)

watch(() => props.open, async open => {
  if (!open) return
  name.value = props.current?.name || ''
  error.value = ''
  await nextTick()
  input.value?.focus()
})

async function save() {
  busy.value = true
  error.value = ''
  try {
    emit('renamed', await request(`/api/sessions/${encodeURIComponent(props.current.id)}`, { method: 'PATCH', body: JSON.stringify({ name: name.value.trim() || null }) }))
  } catch (failure) { error.value = `Unable to rename the shift: ${failure.message}` } finally { busy.value = false }
}

function close() {
  if (!busy.value) emit('close')
}
</script>

<template>
  <div v-if="open && current" class="modal-backdrop" @click.self="close" @keydown.esc="close">
    <form class="modal panel" role="dialog" aria-modal="true" aria-labelledby="shift-title" @submit.prevent="save">
      <button type="button" class="close-button" aria-label="Close" @click="close">×</button>
      <p class="eyebrow">Today's shift</p>
      <h2 id="shift-title">Name this shift</h2>
      <p class="muted">A new shift starts on its own each day, and ends with the day's last scan. The name only labels {{ shiftDate(current) }}.</p>
      <label><span>Name <span class="optional">(optional)</span></span>
        <input ref="input" v-model="name" maxlength="80" placeholder="e.g. Toril batch" autocomplete="off">
      </label>
      <p class="form-hint">Without a name, the shift is listed by its date.</p>
      <div class="modal-actions">
        <button type="button" class="secondary-button" :disabled="busy" @click="close">Cancel</button>
        <button class="primary-button" :disabled="busy">{{ busy ? 'Saving…' : 'Save name' }}</button>
      </div>
      <p v-if="error" class="bad small" role="alert">{{ error }}</p>
    </form>
  </div>
</template>
