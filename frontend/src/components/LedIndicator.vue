<script setup>
import { computed } from 'vue'
import { LED_LEGEND, LED_STATES, ledInfo } from '../lib/led.js'

const props = defineProps({
  state: { type: String, default: 'offline' },
  compact: { type: Boolean, default: false }
})
const info = computed(() => ledInfo(props.state))
</script>

<template>
  <div :class="['led-indicator', { compact }]" role="status" aria-live="polite" tabindex="0" :aria-label="`Floor LED: ${info.color}, ${info.label}`">
    <span :key="state" :class="['led-dot', info.tone]" aria-hidden="true"></span>
    <span class="led-text"><strong>{{ info.label }}</strong><small v-if="!compact">{{ info.color }} · {{ info.detail }}</small></span>
    <div class="led-legend" role="tooltip">
      <p class="eyebrow">Floor LED mirror</p>
      <div v-for="key in LED_LEGEND" :key="key" class="led-legend-row">
        <span :class="['led-dot', 'static', LED_STATES[key].tone]"></span>
        <span><b>{{ LED_STATES[key].color }}</b> — {{ LED_STATES[key].label }}</span>
      </div>
    </div>
  </div>
</template>
