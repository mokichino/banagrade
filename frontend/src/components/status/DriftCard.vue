<script setup>
import { computed } from 'vue'
import { apiBase } from '../../composables/useApi.js'
import { driftSummary, formatDriftValue } from '../../lib/drift.js'

const props = defineProps({ drift: { type: Object, default: null } })
const summary = computed(() => driftSummary(props.drift))
const TONE = { ok: 'ok', warn: 'bad', insufficient_data: 'muted' }
</script>

<template>
  <div class="panel drift-card">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">Model drift</p>
        <h2>Production vs. held-out test set</h2>
        <p :class="['drift-summary', summary.tone]">{{ summary.text }}</p>
      </div>
      <a class="secondary-button link-button" :href="`${apiBase}/api/exports/disputes.zip`">Export disputed frames</a>
    </div>
    <p v-if="!drift" class="chart-empty">Drift indicators unavailable.</p>
    <div v-else class="telemetry-grid drift-grid">
      <div v-for="item in drift.indicators" :key="item.key">
        <span>{{ item.label }}</span>
        <strong :class="TONE[item.status]">{{ formatDriftValue(item.value, item.unit) }}</strong>
        <small>
          Test set {{ formatDriftValue(item.baseline, item.unit) }} · warn {{ item.direction }} {{ formatDriftValue(item.limit, item.unit) }}
          · {{ item.samples }} scan{{ item.samples === 1 ? '' : 's' }}
        </small>
      </div>
    </div>
  </div>
</template>
