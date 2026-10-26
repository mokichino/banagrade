<script setup>
import LedIndicator from '../LedIndicator.vue'

defineProps({
  views: { type: Array, required: true },
  active: { type: String, required: true },
  led: { type: String, default: 'offline' }
})
defineEmits(['navigate'])
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
  </aside>
</template>
