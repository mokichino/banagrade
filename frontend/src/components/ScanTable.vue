<script setup>
import { confidencePercent, finalGradeKey, finalGradeLabel, formatConfidence, formatTimestamp, isHealthy, scanLabel, stage1Label, stage2Label } from '../lib/grades.js'

defineProps({ scans: { type: Array, required: true } })
defineEmits(['select', 'dispute'])
</script>

<template>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th scope="col">Scan ID</th><th scope="col">Timestamp</th><th scope="col">Stage 1 screening</th><th scope="col">Stage 2 grading</th><th scope="col">Confidence</th><th scope="col">Final grade</th><th scope="col">Action</th></tr>
      </thead>
      <tbody>
        <tr v-for="scan in scans" :key="scan.scan_id">
          <td><button class="link-cell mono" :title="scan.scan_id" @click="$emit('select', scan)">{{ scanLabel(scan.scan_id) }}</button></td>
          <td class="tabular">{{ formatTimestamp(scan.captured_at) }}</td>
          <td>
            <span v-if="scan.stage1_status" :class="['health-pill', isHealthy(scan) ? 'healthy' : 'unhealthy']">{{ stage1Label(scan) }}</span>
            <span v-else class="muted">N/A</span>
          </td>
          <td><span :class="['stage2-label', stage2Label(scan) === 'N/A' ? 'muted' : '']">{{ stage2Label(scan) }}</span></td>
          <td>
            <div class="confidence-cell" :title="`Stage 1 ${formatConfidence(scan.stage1_confidence)} · Stage 2 detection ${formatConfidence(scan.stage2_confidence)}`">
              <div class="confidence-track" role="progressbar" :aria-valuenow="confidencePercent(scan.stage1_confidence) ?? 0" aria-valuemin="0" aria-valuemax="100" aria-label="Stage 1 confidence"><span :style="{ width: `${confidencePercent(scan.stage1_confidence) ?? 0}%` }"></span></div>
              <small class="tabular">{{ formatConfidence(scan.stage1_confidence) }}</small>
            </div>
          </td>
          <td><span :class="['grade-chip', finalGradeKey(scan)]">{{ finalGradeLabel(scan) }}</span></td>
          <td><button class="text-button dispute-button" @click="$emit('dispute', scan)">Dispute</button></td>
        </tr>
        <tr v-if="!scans.length"><td colspan="7" class="empty">No scan records match.</td></tr>
      </tbody>
    </table>
  </div>
</template>
