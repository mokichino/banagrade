<script setup>
import { computed, ref } from 'vue'
import { plural } from '../../lib/shifts.js'
import ClearScansDialog from '../ClearScansDialog.vue'

// Clearing lives here, away from the scan table, so a bulk delete is never one click from everyday filtering and exports.
const props = defineProps({ shifts: { type: Array, default: null } })
defineEmits(['cleared'])
const clearing = ref(false)
const scanCount = computed(() => (props.shifts || []).reduce((total, shift) => total + (shift.scan_count || 0), 0))
const shiftCount = computed(() => (props.shifts || []).filter(shift => shift.scan_count).length)
</script>

<template>
  <div class="panel records-card">
    <p class="eyebrow">Test data</p>
    <h2>Scan records</h2>
    <p class="muted records-summary">
      <template v-if="shifts">Stored on the Pi: {{ plural(scanCount, 'scan') }} in {{ plural(shiftCount, 'shift') }}.</template>
      <template v-else>Scan records unavailable.</template>
      The database is also backed up every night.
    </p>
    <div class="danger-zone">
      <div><b>Clear all scans</b><small>Deletes every scan, dispute, saved photo and past shift, for example after a test run. A verified backup is saved first.</small></div>
      <button class="secondary-button danger-outline" :disabled="!scanCount" @click="clearing = true">Clear all scans</button>
    </div>
    <ClearScansDialog :open="clearing" :scan-count="scanCount" @close="clearing = false" @cleared="$emit('cleared', $event)" />
  </div>
</template>
