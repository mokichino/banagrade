<script setup>
// A document with its file type on a coloured band, the way file managers show PDF and CSV files.
const props = defineProps({ type: { type: String, required: true } })
const BANDS = { pdf: '#C2412D', csv: '#1D7A46' }
</script>

<template>
  <svg class="file-icon" viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
    <path d="M6 1.5h8.5L20 7v13.5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-17a2 2 0 0 1 2-2z" fill="#fff" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" />
    <path d="M14.5 1.5V7H20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" />
    <rect x="1" y="11" width="18" height="8.5" rx="1.6" :fill="BANDS[props.type]" />
    <text x="10" y="17.4" text-anchor="middle" fill="#fff" font-size="6.4" font-weight="700" letter-spacing=".2">{{ props.type.toUpperCase() }}</text>
  </svg>
</template>
