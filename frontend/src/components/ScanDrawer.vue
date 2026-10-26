<script setup>
import { computed } from 'vue'
import { failureReason, finalGradeLabel, formatConfidence, formatTimestamp, scanLabel, stage2Label } from '../lib/grades.js'

const props = defineProps({ scan: { type: Object, default: null } })
defineEmits(['close'])
const width = computed(() => (props.scan?.pixel_length != null ? `${Number(props.scan.pixel_length).toFixed(1)} px` : 'N/A'))
const latency = computed(() => (props.scan?.inference_time_ms != null ? `${Math.round(props.scan.inference_time_ms)} ms` : 'N/A'))
</script>

<template>
  <div v-if="scan" class="drawer" @click.self="$emit('close')">
    <div class="drawer-panel" role="dialog" aria-modal="true" aria-label="Scan detail">
      <button class="close-button" aria-label="Close" @click="$emit('close')">×</button>
      <p class="eyebrow">Scan detail</p>
      <h2>{{ scanLabel(scan.scan_id) }}</h2>
      <p class="muted mono small">{{ scan.scan_id }}</p>
      <dl>
        <dt>Captured</dt><dd>{{ formatTimestamp(scan.captured_at) }}</dd>
        <dt>Final grade</dt><dd>{{ finalGradeLabel(scan) }}</dd>
        <dt>Stage 1</dt><dd>{{ scan.stage1_status || 'N/A' }} · {{ formatConfidence(scan.stage1_confidence) }}</dd>
        <dt>Stage 2</dt><dd>{{ stage2Label(scan) }} · {{ formatConfidence(scan.stage2_confidence) }}</dd>
        <dt>Bbox width</dt><dd>{{ width }}</dd>
        <dt>Threshold</dt><dd>≥ 2730.07 px → Class A</dd>
        <dt>Latency</dt><dd>{{ latency }}</dd>
        <dt>Reason</dt><dd>{{ failureReason(scan) || scan.rejection_reason || '—' }}</dd>
        <template v-if="scan.error_details"><dt>Error</dt><dd>{{ scan.error_details }}</dd></template>
      </dl>
    </div>
  </div>
</template>
