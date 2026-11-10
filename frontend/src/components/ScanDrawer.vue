<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { WIDTH_THRESHOLD_PX, confidencePercent, disputeSummary, failureReason, finalGradeKey, finalGradeLabel, formatConfidence, formatTimestamp, isHealthy, isVoided, scanLabel, stage2Label } from '../lib/grades.js'
import CloseIcon from './CloseIcon.vue'
import ScanPhoto from './ScanPhoto.vue'

// Scan detail: a centred dialog with the photo beside the result, stacked on a narrow screen.
const props = defineProps({ scan: { type: Object, default: null } })
const emit = defineEmits(['close'])

const pixels = (value, digits) => `${value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })} px`
const voided = computed(() => isVoided(props.scan))
const reason = computed(() => failureReason(props.scan))
// The raw error text, unless the plain-words reason already quotes it.
const errorDetail = computed(() => {
  const detail = props.scan?.error_details
  return detail && !reason.value.includes(detail) ? detail : ''
})

const stages = computed(() => {
  const scan = props.scan
  if (!scan) return []
  const stage2 = stage2Label(scan)
  return [
    {
      name: 'Stage 1 screening',
      value: scan.stage1_status || 'Not run',
      tone: scan.stage1_status ? (isHealthy(scan) ? 'ok' : 'bad') : 'muted',
      percent: confidencePercent(scan.stage1_confidence),
      confidence: formatConfidence(scan.stage1_confidence),
      empty: 'No confidence recorded'
    },
    {
      name: 'Stage 2 grading',
      // A Healthy bunch with no Stage 2 grade was held as Not graded; an Unhealthy one never reached Stage 2.
      value: stage2 === 'N/A' ? (isHealthy(scan) ? 'Not graded' : 'Not run') : stage2,
      tone: stage2 === 'N/A' ? 'muted' : '',
      percent: confidencePercent(scan.stage2_confidence),
      confidence: formatConfidence(scan.stage2_confidence),
      empty: isHealthy(scan) ? 'No measurement recorded' : 'Runs on healthy bunches only'
    }
  ]
})

const width = computed(() => {
  const value = Number(props.scan?.pixel_length)
  if (props.scan?.pixel_length == null || !Number.isFinite(value)) return null
  const gap = Math.abs(value - WIDTH_THRESHOLD_PX)
  return { text: pixels(value, 1), note: `${pixels(gap, 1)} ${value >= WIDTH_THRESHOLD_PX ? 'over' : 'under'} the Class A minimum` }
})
const latency = computed(() => (props.scan?.inference_time_ms != null ? `${Math.round(props.scan.inference_time_ms).toLocaleString()} ms` : 'Not recorded'))

// Focus moves into the dialog when it opens and back to the row that opened it when it closes.
const closeButton = ref(null)
let returnFocus = null
watch(() => props.scan?.scan_id, (id, previous) => {
  if (id && !previous) {
    returnFocus = document.activeElement
    nextTick(() => closeButton.value?.focus())
  } else if (!id && previous) {
    if (returnFocus?.isConnected) returnFocus.focus()
    returnFocus = null
  }
})
</script>

<template>
  <div v-if="scan" class="modal-backdrop" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="scan-dialog" role="dialog" aria-modal="true" aria-labelledby="scan-detail-title">
      <header class="scan-dialog-head">
        <p class="eyebrow">Scan detail</p>
        <div class="scan-title">
          <h2 id="scan-detail-title">{{ scanLabel(scan.scan_id) }}</h2>
          <span v-if="voided" class="voided-badge">Voided</span>
          <span v-if="scan.disputed" class="disputed-badge">Disputed</span>
          <span v-if="scan.shift_closed" class="read-only-badge" title="This scan's shift has ended, so its grade and void status are final">Read-only</span>
        </div>
        <p class="scan-meta"><span class="tabular">{{ formatTimestamp(scan.captured_at) }}</span><span class="mono">{{ scan.scan_id }}</span></p>
        <button ref="closeButton" type="button" class="close-button" aria-label="Close scan detail" @click="emit('close')"><CloseIcon /></button>
      </header>

      <div class="scan-dialog-body">
        <ScanPhoto class="scan-dialog-photo" :scan="scan" />

        <div class="scan-facts">
          <section :class="['grade-summary', finalGradeKey(scan)]" aria-label="Result">
            <span class="fact-label">Final grade</span>
            <strong>{{ finalGradeLabel(scan) }}</strong>
            <p v-if="reason">{{ reason }}</p>
            <p v-if="errorDetail" class="error-detail">{{ errorDetail }}</p>
          </section>

          <div v-if="voided" class="scan-note">
            <b>Voided: not counted in any total, rate or chart</b>
            <span>{{ scan.void_reason }}</span>
            <small class="tabular">{{ formatTimestamp(scan.voided_at) }}</small>
          </div>
          <div v-if="scan.disputed" class="scan-note disputed">
            <b>Grade disputed by an operator</b>
            <span>{{ disputeSummary(scan) }}</span>
          </div>

          <div class="stage-grid">
            <section v-for="stage in stages" :key="stage.name" class="stage-card">
              <span class="fact-label">{{ stage.name }}</span>
              <strong :class="stage.tone">{{ stage.value }}</strong>
              <template v-if="stage.percent != null">
                <span class="meter" role="progressbar" :aria-valuenow="stage.percent" aria-valuemin="0" aria-valuemax="100" :aria-label="`${stage.name} confidence`"><span :style="{ width: `${stage.percent}%` }"></span></span>
                <small class="tabular">{{ stage.confidence }} confidence</small>
              </template>
              <small v-else>{{ stage.empty }}</small>
            </section>
          </div>

          <dl class="fact-list">
            <div><dt>Measured width</dt><dd><span class="tabular">{{ width ? width.text : 'Not measured' }}</span><small v-if="width">{{ width.note }}</small></dd></div>
            <div><dt>Class A minimum</dt><dd class="tabular">{{ pixels(WIDTH_THRESHOLD_PX, 2) }}</dd></div>
            <div><dt>Inference time</dt><dd class="tabular">{{ latency }}</dd></div>
          </dl>
        </div>
      </div>
    </div>
  </div>
</template>
