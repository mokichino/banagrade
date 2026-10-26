<script setup>
import { computed, ref } from 'vue'
import { request } from '../../composables/useApi.js'

const props = defineProps({ power: { type: Object, default: null } })

const ACTIONS = {
  reboot: { label: 'Reboot', confirm: 'Reboot the Pi? Grading stops for about a minute, then the dashboard reconnects on its own.', done: 'Rebooting. The dashboard reconnects in about a minute.' },
  shutdown: { label: 'Shut down', confirm: 'Shut down the Pi? It stays off until someone unplugs it and plugs it back in.', done: 'Shutting down. Wait until the Pi’s green activity light stops blinking before unplugging it.' }
}
const pending = ref('')
const busy = ref(false)
const message = ref('')
const error = ref('')
const done = ref(false)

const unavailable = computed(() => {
  if (!props.power) return 'Power status unavailable.'
  if (Object.values(props.power).every(p => p.allowed)) return ''
  return 'The service is not allowed to reboot or shut down the Pi yet. Install deploy/50-banagrade-power.rules (see README).'
})

async function confirm() {
  busy.value = true
  error.value = ''
  try {
    await request('/api/system/power', { method: 'POST', body: JSON.stringify({ action: pending.value }) })
    message.value = ACTIONS[pending.value].done
    done.value = true
  } catch (failure) {
    error.value = failure.message
  } finally {
    busy.value = false
    pending.value = ''
  }
}
</script>

<template>
  <div class="panel">
    <p class="eyebrow">Power</p>
    <h2>Reboot or shut down</h2>
    <p class="muted small">Rebooting also re-runs autofocus, so the rig height reading is fresh.</p>
    <div v-if="!pending" class="power-actions">
      <button v-for="(action, key) in ACTIONS" :key="key" class="secondary-button" :disabled="done || !power?.[key]?.allowed" @click="pending = key; message = ''">{{ action.label }}</button>
    </div>
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
</template>
