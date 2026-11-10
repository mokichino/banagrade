<script setup>
import { computed } from 'vue'
import { LED_LEGEND, LED_STATES, ledInfo } from '../lib/led.js'

// `legend` adds a hover/focus key of every floor LED state. Only the header's copy has one.
const props = defineProps({
  state: { type: String, default: 'offline' },
  compact: { type: Boolean, default: false },
  legend: { type: Boolean, default: false }
})
const info = computed(() => ledInfo(props.state))
</script>

<template>
  <div :class="['led-indicator', { compact, 'has-legend': legend }]" role="status" aria-live="polite" :tabindex="legend ? 0 : undefined" :aria-label="`Floor LED: ${info.color}, ${info.label}`">
    <span :key="state" :class="['led-dot', info.tone]" aria-hidden="true"></span>
    <span class="led-text"><strong>{{ info.label }}</strong><small v-if="!compact">{{ info.detail }}</small></span>
    <div v-if="legend" class="led-legend" role="tooltip">
      <p class="eyebrow">Floor LED key</p>
      <div v-for="key in LED_LEGEND" :key="key" class="led-legend-row">
        <span :class="['led-dot', 'static', LED_STATES[key].tone]"></span>
        <b>{{ LED_STATES[key].label }}</b>
        <span>{{ LED_STATES[key].color }}</span>
      </div>
    </div>
  </div>
</template>
