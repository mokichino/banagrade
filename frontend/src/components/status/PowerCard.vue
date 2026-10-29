<script setup>
import { computed } from 'vue'
import { POWER_ACTIONS as ACTIONS, POWER_RULE_MISSING, usePowerAction } from '../../composables/usePower.js'

const props = defineProps({ power: { type: Object, default: null } })
const { pending, busy, message, error, done, choose, confirm } = usePowerAction()

const unavailable = computed(() => {
  if (!props.power) return 'Power status unavailable.'
  return Object.values(props.power).every(p => p.allowed) ? '' : POWER_RULE_MISSING
})
</script>

<template>
  <div class="panel">
    <p class="eyebrow">Power</p>
    <h2>Reboot or shut down</h2>
    <p class="muted small">Rebooting also re-runs autofocus, so the rig height reading is fresh.</p>
    <div v-if="!pending" class="power-actions">
      <button v-for="(action, key) in ACTIONS" :key="key" class="secondary-button" :disabled="done || !power?.[key]?.allowed" @click="choose(key)">{{ action.label }}</button>
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
