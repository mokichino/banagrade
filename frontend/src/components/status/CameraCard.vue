<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiBase, request } from '../../composables/useApi.js'

const props = defineProps({ pipeline: { type: Object, default: null } })
const camera = computed(() => props.pipeline?.camera || {})
const streamError = ref(false)
const streamKey = ref(0)
const streamSrc = computed(() => `${apiBase}/api/camera/preview.mjpg?k=${streamKey.value}`)
const snapshotBusy = ref(false)
const snapshotError = ref('')
async function openSnapshot() {
  snapshotBusy.value = true
  snapshotError.value = ''
  try {
    const response = await fetch(`${apiBase}/api/camera/snapshot.jpg`)
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `Request failed: ${response.status}`)
    const url = URL.createObjectURL(await response.blob())
    window.open(url, '_blank', 'noopener')
    window.setTimeout(() => URL.revokeObjectURL(url), 60000)
  } catch (error) {
    snapshotError.value = error.message
  } finally {
    snapshotBusy.value = false
  }
}
// Placement guide in 4608x2592 frame coordinates, from the app's Stage 2 boxes on the 336 dataset photos:
// median bunch box 2648 x 1789 px centred at (2222, 1386). The edge strip is where a bunch gets refused or cut off.
const GUIDE = { width: 4608, height: 2592, box: { x: 898, y: 492, width: 2648, height: 1789 }, centre: { x: 2222, y: 1386 }, edge: { x: 115, y: 65 } }
const guideKey = 'banagrade.cameraGuide'
const showGuide = ref(readGuide())
function readGuide() {
  try { return window.localStorage.getItem(guideKey) !== 'off' } catch { return true }
}
watch(showGuide, value => { try { window.localStorage.setItem(guideKey, value ? 'on' : 'off') } catch { /* preference is optional */ } })

// Camera alignment from a short bond sheet on the velvet (backend/app/alignment.py). Opposite edges of equal
// length mean the camera looks straight down; the outline is drawn over the preview until cleared.
const alignment = ref(null)
const alignBusy = ref(false)
const alignError = ref('')
async function checkAlignment() {
  alignBusy.value = true
  alignError.value = ''
  try {
    alignment.value = await request('/api/camera/alignment', { method: 'POST' })
  } catch (error) {
    alignment.value = null
    alignError.value = error.message
  } finally {
    alignBusy.value = false
  }
}
function tiltRow(ratio, degrees, [positive, negative]) {
  if (Math.abs(ratio - 1) <= 0.02) return { text: `Level · ${ratio.toFixed(2)}`, tone: 'ok' }
  const [leans, fix] = degrees > 0 ? positive : negative
  return { text: `${Math.abs(degrees)}° towards the ${leans} · tip the lens towards the ${fix}`, tone: 'bad' }
}
const alignRows = computed(() => {
  const a = alignment.value
  if (!a) return []
  return [
    { label: 'Front–back tilt', ...tiltRow(a.front_back_ratio, a.front_back_tilt_deg, [['top of the view', 'bottom'], ['bottom of the view', 'top']]) },
    { label: 'Side tilt', ...tiltRow(a.side_ratio, a.side_tilt_deg, [['left of the view', 'right'], ['right of the view', 'left']]) },
    { label: 'Height at the sheet', text: `≈ ${Math.round(a.height_cm)} cm (camera specs, ±2 cm)`, tone: a.height_ok ? 'ok' : 'bad' }
  ]
})
const sheetPoints = computed(() => alignment.value?.corners.map(point => point.join(',')).join(' '))

const previewEl = ref(null)
const expanded = ref(false)
async function toggleExpanded() {
  if (expanded.value) {
    expanded.value = false
    if (document.fullscreenElement) await document.exitFullscreen().catch(() => {})
    return
  }
  expanded.value = true
  // Real fullscreen where the browser allows it; iPhones only allow it for video, so the page overlay is the fallback.
  if (previewEl.value?.requestFullscreen) await previewEl.value.requestFullscreen().catch(() => {})
}
function onFullscreenChange() { if (!document.fullscreenElement && expanded.value) expanded.value = false }
function onKey(event) { if (event.key === 'Escape' && expanded.value && !document.fullscreenElement) expanded.value = false }
onMounted(() => { document.addEventListener('fullscreenchange', onFullscreenChange); document.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { document.removeEventListener('fullscreenchange', onFullscreenChange); document.removeEventListener('keydown', onKey) })

watch(() => camera.value.available, available => { if (available) { streamError.value = false; streamKey.value += 1 } })

const illumination = computed(() => {
  const value = camera.value.illumination
  if (!value) return { text: 'Not measured', tone: 'muted' }
  if (value.status === 'ok') return { text: `OK · brightness ${value.mean_brightness}`, tone: 'ok' }
  return { text: value.status === 'dark' ? 'Too dark — check ring light' : 'Lens obstructed', tone: 'bad' }
})
const expectedCm = computed(() => camera.value.expected_distance_cm || 45)
const focus = computed(() => {
  const dpt = camera.value.lens_position_dioptres
  if (camera.value.focus === 'fixed') return { text: `Fixed · ${dpt} dpt (set at ${expectedCm.value} cm)`, tone: 'ok' }
  if (camera.value.focus === 'autofocus') return { text: `Autofocus · ${dpt} dpt`, tone: 'ok' }
  if (camera.value.focus === 'unset') return { text: 'Not set', tone: 'bad' }
  return { text: 'Unavailable', tone: 'muted' }
})
</script>

<template>
  <div class="panel camera-card">
    <div class="panel-heading">
      <div><p class="eyebrow">Camera utility</p><h2>Live top-down preview</h2><p class="muted">Raspberry Pi Camera Module 3 · {{ expectedCm }} cm above the black velvet surface</p></div>
      <span :class="['status-badge', camera.available ? 'loaded' : 'missing']">{{ camera.available ? 'Streaming' : 'Offline' }}</span>
    </div>
    <div ref="previewEl" :class="['camera-preview', { expanded }]">
      <div v-if="camera.available && !streamError" class="camera-frame">
        <img :src="streamSrc" alt="Live top-down camera preview of the inspection zone" @error="streamError = true">
        <svg v-if="showGuide || alignment" class="placement-guide" :viewBox="`0 0 ${GUIDE.width} ${GUIDE.height}`" preserveAspectRatio="none" aria-hidden="true">
          <g v-if="showGuide">
            <path class="guide-edge" fill-rule="evenodd" :d="`M0 0H${GUIDE.width}V${GUIDE.height}H0Z M${GUIDE.edge.x} ${GUIDE.edge.y}V${GUIDE.height - GUIDE.edge.y}H${GUIDE.width - GUIDE.edge.x}V${GUIDE.edge.y}Z`" />
            <rect class="guide-box" v-bind="GUIDE.box" rx="40" />
            <path class="guide-cross" :d="`M${GUIDE.centre.x - 120} ${GUIDE.centre.y}h240M${GUIDE.centre.x} ${GUIDE.centre.y - 120}v240`" />
          </g>
          <polygon v-if="alignment" :class="['guide-sheet', alignment.level ? 'level' : 'tilted']" :points="sheetPoints" />
        </svg>
      </div>
      <div v-else class="camera-offline"><strong>Camera unavailable</strong><span>{{ pipeline?.last_error || 'The edge device has not opened the camera.' }}</span></div>
      <span class="preview-tag">Full camera view · box = what the capture trigger sees<template v-if="showGuide"> · dashed = typical bunch, centre it on the cross · keep out of the red edge</template></span>
      <button v-if="expanded" class="preview-exit secondary-button" @click="toggleExpanded">Exit full screen</button>
    </div>
    <div class="camera-actions">
      <button class="secondary-button" :disabled="!camera.available" @click="toggleExpanded">Full screen</button>
      <label class="guide-toggle small"><input v-model="showGuide" type="checkbox"> Placement guide</label>
      <button class="secondary-button" :disabled="!camera.available || snapshotBusy" @click="openSnapshot">{{ snapshotBusy ? 'Capturing…' : 'Full-resolution snapshot' }}</button>
      <button class="secondary-button" :disabled="!camera.available || alignBusy" @click="checkAlignment">{{ alignBusy ? 'Measuring…' : 'Check camera alignment' }}</button>
      <span v-if="snapshotError" class="muted small">{{ snapshotError }}</span>
    </div>
    <div v-if="alignment || alignError" class="alignment-result">
      <p v-if="alignError" class="bad small">{{ alignError }}</p>
      <template v-else>
        <dl class="camera-meta">
          <div v-for="row in alignRows" :key="row.label"><dt>{{ row.label }}</dt><dd :class="row.tone">{{ row.text }}</dd></div>
        </dl>
        <p class="muted small">{{ alignment.level ? 'The camera looks straight down.' : 'Adjust, then check again: aim for "Level" on both tilts. Check the table is level too.' }} <button class="text-button" @click="alignment = null">Clear</button></p>
      </template>
    </div>
    <p v-else class="muted small alignment-hint">Camera alignment: lay a short bond sheet flat in the middle of the table, then press Check camera alignment.</p>
    <slot name="below-preview" />
    <dl class="camera-meta">
      <div><dt>Capture resolution</dt><dd>{{ camera.resolution || 'Unavailable' }}</dd></div>
      <div><dt>Lens focus</dt><dd :class="focus.tone">{{ focus.text }}</dd></div>
      <div><dt>LED ring light</dt><dd :class="illumination.tone">{{ illumination.text }}</dd></div>
    </dl>
  </div>
</template>
