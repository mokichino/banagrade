<script setup>
import { confidencePercent, disputeSummary, failureReason, finalGradeKey, finalGradeLabel, formatConfidence, formatTimestamp, isHealthy, scanLabel, stage1Label, stage2Label } from '../lib/grades.js'

defineProps({ scans: { type: Array, required: true }, emptyText: { type: String, default: 'No scan records match.' } })
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
          <td>
            <div class="grade-cell">
              <span :class="['grade-chip', finalGradeKey(scan)]">{{ finalGradeLabel(scan) }}</span>
              <span v-if="scan.disputed" class="disputed-badge" :title="disputeSummary(scan)">
                <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><path d="M4 22v-7" fill="none" /></svg>
                Disputed
              </span>
            </div>
            <small v-if="finalGradeKey(scan) === 't' && failureReason(scan)" class="failure-reason">{{ failureReason(scan) }}</small>
          </td>
          <td>
            <button class="icon-button dispute-button" :title="scan.disputed ? 'Disputes for this scan' : 'Dispute grade'" :aria-label="`Dispute ${scanLabel(scan.scan_id)}`" @click="$emit('dispute', scan)">
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><path d="M4 22v-7" /></svg>
            </button>
          </td>
        </tr>
        <tr v-if="!scans.length"><td colspan="7" class="empty">{{ emptyText }}</td></tr>
      </tbody>
    </table>
  </div>
</template>
