<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { request as api } from '../composables/useApi.js'
import { finalGradeLabel, formatTimestamp, isVoided, scanLabel } from '../lib/grades.js'
import { plural } from '../lib/shifts.js'

// Voiding is how a scan is taken out of the numbers: it stays in the audit trail, marked, and can be counted again.
// `request` is { scans, restore }: restore false voids the listed scans that count, true counts the voided ones again.
const props = defineProps({ request: { type: Object, default: null } })
const emit = defineEmits(['close', 'saved'])
const REASONS = ['Duplicate scan of the same bunch', 'Test object, not a bunch', 'Test run', 'Scanned by mistake']
const reason = ref('')
const busy = ref(false)
const error = ref('')
const first = ref(null)

const restoring = computed(() => Boolean(props.request?.restore))
const scans = computed(() => (props.request?.scans || []).filter(scan => isVoided(scan) === restoring.value))
const single = computed(() => (scans.value.length === 1 ? scans.value[0] : null))
const what = computed(() => (single.value ? scanLabel(single.value.scan_id) : plural(scans.value.length, 'scan')))
const ready = computed(() => scans.value.length > 0 && (restoring.value || reason.value.trim().length >= 3))

watch(() => props.request, async request => {
  reason.value = ''
  error.value = ''
  if (!request) return
  await nextTick()
  first.value?.focus()
})

async function save() {
  busy.value = true
  error.value = ''
  const scanIds = scans.value.map(scan => scan.scan_id)
  try {
    await api(`/api/inspection/scans/${restoring.value ? 'unvoid' : 'void'}`, {
      method: 'POST',
      body: JSON.stringify(restoring.value ? { scan_ids: scanIds } : { scan_ids: scanIds, reason: reason.value.trim() })
    })
    emit('saved')
  } catch (failure) {
    error.value = `${restoring.value ? 'Unable to count again' : 'Unable to void'}: ${failure.message}`
  } finally { busy.value = false }
}

function close() {
  if (!busy.value) emit('close')
}
</script>

<template>
  <div v-if="request" class="modal-backdrop" @click.self="close" @keydown.esc="close">
    <form class="modal panel" role="dialog" aria-modal="true" aria-labelledby="void-title" @submit.prevent="ready && save()">
      <button type="button" class="close-button" aria-label="Close" @click="close">×</button>
      <p class="eyebrow">Audit trail</p>
      <template v-if="!restoring">
        <h2 id="void-title">Void {{ what }}</h2>
        <p class="muted">{{ single ? 'It stays' : 'They stay' }} in Recent Scans, marked Voided, and {{ single ? 'stops' : 'stop' }} counting in totals, rates and charts. Nothing is deleted; you can count {{ single ? 'it' : 'them' }} again at any time.</p>
        <p v-if="single" class="void-subject">{{ finalGradeLabel(single) }} · {{ formatTimestamp(single.captured_at) }}</p>
        <label>Reason
          <textarea ref="first" v-model="reason" required maxlength="500" placeholder="Why should this not count?"></textarea>
        </label>
        <div class="reason-chips" role="group" aria-label="Common reasons">
          <button v-for="option in REASONS" :key="option" type="button" :class="['chip-button', { active: reason === option }]" @click="reason = option">{{ option }}</button>
        </div>
        <div class="modal-actions">
          <button type="button" class="secondary-button" :disabled="busy" @click="close">Cancel</button>
          <button class="primary-button" :disabled="busy || !ready">{{ busy ? 'Voiding…' : `Void ${single ? 'scan' : plural(scans.length, 'scan')}` }}</button>
        </div>
      </template>
      <template v-else>
        <h2 id="void-title">Count {{ what }} again</h2>
        <p class="muted">{{ single ? 'It goes' : 'They go' }} back into totals, rates and charts. The void stays in the system log.</p>
        <p v-if="single" class="void-subject">Voided {{ formatTimestamp(single.voided_at) }}: {{ single.void_reason }}</p>
        <div class="modal-actions">
          <button type="button" class="secondary-button" :disabled="busy" @click="close">Cancel</button>
          <button ref="first" class="primary-button" :disabled="busy || !ready">{{ busy ? 'Saving…' : 'Count again' }}</button>
        </div>
      </template>
      <p v-if="error" class="bad small" role="alert">{{ error }}</p>
    </form>
  </div>
</template>
