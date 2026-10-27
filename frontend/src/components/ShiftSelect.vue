<script setup>
import { computed } from 'vue'
import { shiftLabel } from '../lib/grades.js'

// v-model is 'active', 'all' or a past shift's id.
const props = defineProps({ modelValue: { type: String, required: true }, shifts: { type: Array, default: () => [] } })
defineEmits(['update:modelValue'])
const past = computed(() => props.shifts.filter(shift => shift.status !== 'open'))
</script>

<template>
  <select :value="modelValue" aria-label="Shift" @change="$emit('update:modelValue', $event.target.value)">
    <option value="active">Current shift</option>
    <option value="all">All shifts</option>
    <optgroup v-if="past.length" label="Past shifts">
      <option v-for="shift in past" :key="shift.id" :value="shift.id">{{ shiftLabel(shift) }}</option>
    </optgroup>
  </select>
</template>
