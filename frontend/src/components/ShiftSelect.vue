<script setup>
import { computed, watch } from 'vue'
import { pastShifts, shiftOptionLabel } from '../lib/shifts.js'

// v-model is 'active', 'all' or a past shift's id. Past shifts without scans are not offered.
const props = defineProps({ modelValue: { type: String, required: true }, shifts: { type: Array, default: () => [] } })
const emit = defineEmits(['update:modelValue'])
const past = computed(() => pastShifts(props.shifts))

// A chosen shift can vanish (Clear all scans) or be emptied; show the current shift then instead of a blank page.
watch(past, list => {
  const known = ['active', 'all'].includes(props.modelValue) || list.some(shift => shift.id === props.modelValue)
  if (props.shifts.length && !known) emit('update:modelValue', 'active')
}, { immediate: true })
</script>

<template>
  <select :value="modelValue" aria-label="Shift" @change="$emit('update:modelValue', $event.target.value)">
    <option value="active">Current shift</option>
    <option value="all">All shifts</option>
    <optgroup v-if="past.length" label="Past shifts">
      <option v-for="shift in past" :key="shift.id" :value="shift.id">{{ shiftOptionLabel(shift) }}</option>
    </optgroup>
  </select>
</template>
