<script setup>
import { computed, ref, watch } from 'vue'
import { request } from '../composables/useApi.js'
import { POWER_ACTIONS as ACTIONS, POWER_RULE_MISSING, usePowerAction } from '../composables/usePower.js'

const props = defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['close'])
const { pending, busy, message, error, done, choose, confirm } = usePowerAction()
const power = ref(null)
const loadError = ref('')

watch(() => props.open, async open => {
  if (!open) return
  pending.value = ''
  loadError.value = ''
  try {
    power.value = (await request('/api/system/status')).power
  } catch (failure) {
    power.value = null
    loadError.value = `Power status unavailable: ${failure.message}`
  }
})

const unavailable = computed(() => {
  if (loadError.value) return loadError.value
  if (!power.value) return 'Checking…'
  return Object.values(power.value).every(p => p.allowed) ? '' : POWER_RULE_MISSING
})

function close() {
  if (!busy.value) emit('close')
}
</script>

<template>
  <div v-if="open" class="modal-backdrop" @click.self="close" @keydown.esc="close">
    <div class="modal panel" role="dialog" aria-modal="true" aria-labelledby="power-title">
      <button type="button" class="close-button" aria-label="Close" @click="close">×</button>
      <p class="eyebrow">Power</p>
      <h2 id="power-title">Reboot or shut down the Pi</h2>
      <template v-if="!pending">
        <p class="muted small">Rebooting also re-runs autofocus, so the rig height reading is fresh.</p>
        <div class="power-actions">
          <button v-for="(action, key) in ACTIONS" :key="key" class="secondary-button" :disabled="done || !power?.[key]?.allowed" @click="choose(key)">{{ action.label }}</button>
        </div>
      </template>
      <div v-else class="power-confirm">
        <p>{{ ACTIONS[pending].confirm }}</p>
        <div class="power-actions">
          <button class="primary-button danger" :disabled="busy" @click="confirm">{{ busy ? 'Sending…' : `Yes, ${ACTIONS[pending].label.toLowerCase()}` }}</button>
          <button class="secondary-button" :disabled="busy" @click="pending = ''">Cancel</button>
        </div>
      </div>
      <p v-if="message" class="ok small">{{ message }}</p>
      <p v-if="error" class="bad small">{{ error }}</p>
      <p v-else-if="unavailable && !done" class="muted small">{{ unavailable }}</p>
    </div>
  </div>
</template>
