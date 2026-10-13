<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { DEMO_SEQUENCE, LAMPS, LED_LEGEND, LED_STATES, lampPattern, ledInfo } from '../../lib/led.js'

const props = defineProps({
  led: { type: String, default: 'offline' },
  ledStatus: { type: Object, default: null },
  embedded: { type: Boolean, default: false }
})

const mode = ref('live')
const demoIndex = ref(0)
const pinned = ref(null)
let timer

const shownState = computed(() => {
  if (mode.value === 'demo') return DEMO_SEQUENCE[demoIndex.value]
  if (mode.value === 'pick') return pinned.value
  return props.led
})
const info = computed(() => ledInfo(shownState.value))
const pattern = computed(() => lampPattern(shownState.value))

const hardware = computed(() => {
  const s = props.ledStatus
  if (!s) return { text: 'Unknown', tone: 'muted' }
  if (s.mode === 'physical') return { text: 'Physical LEDs connected', tone: 'ok' }
  if (s.mode === 'unavailable') return { text: s.error || 'GPIO enabled but unavailable', tone: 'bad' }
  return { text: 'Software only — physical LEDs not connected', tone: 'muted' }
})

function stopDemo() { window.clearInterval(timer); timer = undefined }
function setMode(next) {
  stopDemo()
  mode.value = next
  if (next === 'demo') {
    demoIndex.value = 0
    timer = window.setInterval(() => { demoIndex.value = (demoIndex.value + 1) % DEMO_SEQUENCE.length }, 1800)
  }
}
function pick(state) { stopDemo(); mode.value = 'pick'; pinned.value = state }
onBeforeUnmount(stopDemo)
</script>

<template>
  <div :class="embedded ? 'led-embedded' : 'panel led-panel'">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">LED indicators</p>
        <h2 v-if="!embedded">Sorting floor signal board</h2>
        <p class="muted">The four GPIO LEDs as the sorting worker sees them.</p>
      </div>
      <div class="segmented" role="group" aria-label="LED panel mode">
        <button :class="{ active: mode === 'live' }" @click="setMode('live')">Live</button>
        <button :class="{ active: mode === 'demo' }" @click="setMode('demo')">Demo cycle</button>
      </div>
    </div>

    <div class="led-board" :aria-label="`LED board showing ${info.label}`" role="img">
      <div v-for="lamp in LAMPS" :key="lamp.key" class="lamp">
        <span :key="`${shownState}-${lamp.key}`" :class="['lamp-bulb', lamp.key, pattern[lamp.key]]"></span>
        <b>{{ lamp.label }}</b>
        <small>{{ lamp.meaning }}</small>
        <small class="lamp-pin" v-if="ledStatus?.pins">GPIO {{ ledStatus.pins[lamp.key] }}</small>
      </div>
    </div>

    <div class="led-readout">
      <div>
        <span class="muted small">{{ mode === 'live' ? 'Current state' : mode === 'demo' ? 'Demo — not the real system' : 'Preview — not the real system' }}</span>
        <strong>{{ info.label }}</strong>
        <span class="muted small">{{ info.color }} · {{ info.detail }}</span>
      </div>
      <span :class="['led-hw', hardware.tone]">{{ hardware.text }}</span>
    </div>

    <div class="led-state-picker" role="group" aria-label="Preview an LED state">
      <span class="muted small">Preview a state:</span>
      <button v-for="key in LED_LEGEND" :key="key" :class="['chip-button', { active: mode === 'pick' && pinned === key }]" @click="pick(key)">
        <span :class="['led-dot', 'static', LED_STATES[key].tone]"></span>{{ LED_STATES[key].label }}
      </button>
    </div>
  </div>
</template>
