<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import LedIndicator from '../LedIndicator.vue'

defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  led: { type: String, default: 'offline' },
  connection: { type: String, default: 'Connecting' },
  demo: { type: Boolean, default: false }
})

const now = ref(new Date())
let clock
onMounted(() => { clock = window.setInterval(() => { now.value = new Date() }, 1000) })
onBeforeUnmount(() => window.clearInterval(clock))
const date = computed(() => now.value.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }))
const time = computed(() => now.value.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }))
</script>

<template>
  <header class="topbar">
    <div class="topbar-title"><h1>{{ title }}</h1><p class="page-subtitle">{{ subtitle }}</p></div>
    <div class="header-context">
      <span v-if="demo" class="demo-chip" title="This database contains mock scans generated for presentation. They are not real grading results.">Demo data</span>
      <LedIndicator :state="led" compact />
      <div class="header-divider"></div>
      <div class="connection"><span :class="['status-dot', connection === 'Connected' ? 'online' : 'offline']"></span>{{ connection }}</div>
      <div class="header-divider"></div>
      <div class="header-time"><span>{{ date }}</span><strong>{{ time }}</strong></div>
    </div>
  </header>
</template>
