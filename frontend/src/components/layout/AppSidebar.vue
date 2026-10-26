<script setup>
import LedIndicator from '../LedIndicator.vue'

defineProps({
  views: { type: Array, required: true },
  active: { type: String, required: true },
  led: { type: String, default: 'offline' }
})
defineEmits(['navigate', 'power'])
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <img class="brand-mark" src="/logo.svg" alt="" width="32" height="32" />
      <div><strong>Banagrade</strong><span>AI SORTING SYSTEM</span></div>
    </div>
    <nav aria-label="Primary navigation">
      <button v-for="view in views" :key="view.id" :class="['nav-button', { active: active === view.id }]" :aria-current="active === view.id ? 'page' : undefined" @click="$emit('navigate', view.id)">
        {{ view.label }}
      </button>
    </nav>
    <div class="sidebar-status">
      <p class="eyebrow">Sorting floor LED</p>
      <LedIndicator :state="led" />
    </div>
    <button class="nav-button power-shortcut" title="Reboot or shut down the Pi" aria-label="Reboot or shut down the Pi" @click="$emit('power')">
      <svg class="power-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v8" /><path d="M6.4 6.6a8 8 0 1 0 11.2 0" /></svg>
      <span>Power</span>
    </button>
  </aside>
</template>
