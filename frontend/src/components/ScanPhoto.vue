<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { apiBase } from '../composables/useApi.js'
import { scanLabel } from '../lib/grades.js'
import PhotoFrame from './PhotoFrame.vue'

// The preview is the saved frame at a quarter size (backend/app/photos.py PREVIEW_SCALE).
const PREVIEW_SCALE = 4
// The frame is written just after the result is shown, so a scan opened at once may not have its photo yet.
const RETRIES = 2
const RETRY_MS = 1500

const props = defineProps({ scan: { type: Object, required: true } })

function parseList(value) {
  if (Array.isArray(value)) return value
  if (typeof value !== 'string' || !value) return null
  try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed : [parsed] } catch { return [value] }
}

const hasPhoto = computed(() => (parseList(props.scan.image_refs) || []).length > 0)
const box = computed(() => {
  const coords = parseList(props.scan.bbox_coords)?.map(Number)
  return coords?.length === 4 && coords.every(Number.isFinite) && coords[2] > coords[0] && coords[3] > coords[1] ? coords : null
})
const label = computed(() => scanLabel(props.scan.scan_id))
const alt = computed(() => `Photo of scan ${label.value}${box.value ? ', with the bunch Stage 2 measured outlined' : ''}`)
const photoUrl = computed(() => `${apiBase}/api/inspection/scans/${encodeURIComponent(props.scan.scan_id)}/photo`)

const status = ref('loading') // loading | loaded | failed
const attempt = ref(0)
const previewSrc = computed(() => (attempt.value ? `${photoUrl.value}?attempt=${attempt.value}` : photoUrl.value))
const fullSrc = computed(() => `${photoUrl.value}?size=full`)
const frame = ref(null) // full-frame size, from the preview's size
const ratio = computed(() => (frame.value ? frame.value.width / frame.value.height : 16 / 9))
const showBox = ref(true)
let retryTimer = null

function onLoad(size) {
  status.value = 'loaded'
  if (size) frame.value = { width: size.width * PREVIEW_SCALE, height: size.height * PREVIEW_SCALE }
}
function onError() {
  if (attempt.value >= RETRIES) { status.value = 'failed'; return }
  retryTimer = window.setTimeout(() => { attempt.value += 1 }, RETRY_MS)
}

// Full-screen viewer: shows the cached preview at once and swaps in the full frame when it arrives.
const viewerOpen = ref(false)
const fullLoaded = ref(false)
const fullFailed = ref(false)
const opener = ref(null)
const viewerClose = ref(null)
let fullImage = null
let restore = null

function openViewer() {
  viewerOpen.value = true
  if (!fullLoaded.value) {
    fullFailed.value = false
    fullImage = new Image()
    fullImage.onload = () => { fullLoaded.value = true }
    fullImage.onerror = () => { fullFailed.value = true }
    fullImage.src = fullSrc.value
  }
  // The dashboard behind becomes inert, so focus and screen readers stay in the viewer; the page stops scrolling.
  const app = document.getElementById('app')
  const overflow = document.body.style.overflow
  if (app) app.inert = true
  document.body.style.overflow = 'hidden'
  restore = () => { if (app) app.inert = false; document.body.style.overflow = overflow }
  nextTick(() => viewerClose.value?.focus())
}
function closeViewer({ refocus = true } = {}) {
  if (!viewerOpen.value) return
  viewerOpen.value = false
  restore?.()
  restore = null
  if (refocus) nextTick(() => opener.value?.focus())
}
function trapFocus(event) {
  const items = [...event.currentTarget.querySelectorAll('a[href], button:not([disabled])')]
  if (!items.length) return
  const first = items[0]
  const last = items[items.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}

function reset() {
  window.clearTimeout(retryTimer)
  closeViewer({ refocus: false })
  status.value = 'loading'
  attempt.value = 0
  frame.value = null
  fullLoaded.value = false
  fullFailed.value = false
  if (fullImage) { fullImage.onload = fullImage.onerror = null; fullImage = null }
}
watch(() => props.scan.scan_id, reset)
onBeforeUnmount(reset)
</script>

<template>
  <figure class="scan-photo">
    <div v-if="!hasPhoto" class="photo-empty" role="note">
      <b>No photo was saved for this scan.</b>
      <span>Simulated demo scans and scans where the camera failed have no photo.</span>
    </div>
    <div v-else-if="status === 'failed'" class="photo-empty" role="note">
      <b>Photo no longer available.</b>
      <span>The station keeps the latest 1,000 photos to save space; photos of disputed scans are kept for retraining.</span>
    </div>
    <template v-else>
      <button ref="opener" type="button" class="photo-open" :disabled="status !== 'loaded'" :aria-label="`View photo of scan ${label} full screen`" @click="openViewer">
        <PhotoFrame :src="previewSrc" :alt="alt" :box="box" :frame="frame" :show-box="showBox" @load="onLoad" @error="onError" />
        <span v-if="status === 'loading'" class="photo-status" role="status">Loading photo…</span>
        <span v-else class="photo-zoom" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" /></svg>
        </span>
      </button>
      <figcaption v-if="status === 'loaded'" class="photo-caption">
        <span>{{ box && showBox ? 'Yellow outline: the bunch Stage 2 measured. ' : '' }}Tap or click the photo to enlarge.</span>
        <button v-if="box" type="button" class="secondary-button photo-toggle" :aria-pressed="showBox" @click="showBox = !showBox">{{ showBox ? 'Hide outline' : 'Show outline' }}</button>
      </figcaption>
    </template>

    <Teleport to="body">
      <div v-if="viewerOpen" class="photo-viewer" role="dialog" aria-modal="true" :aria-label="`Photo of scan ${label}`" @keydown.esc.stop.prevent="closeViewer()" @keydown.tab="trapFocus">
        <!-- Close sits top-right as everywhere else; the other actions sit in a bottom bar within thumb reach on a
             phone held upright, and join the top bar when it is held sideways (style.css). -->
        <p class="viewer-title">{{ label }}<span v-if="!fullLoaded && !fullFailed" role="status"> · loading full resolution…</span><span v-else-if="fullFailed" role="status"> · showing the preview; full resolution unavailable</span></p>
        <button ref="viewerClose" type="button" class="viewer-button viewer-close" aria-label="Close photo" @click="closeViewer()">×</button>
        <div class="viewer-stage" @click.self="closeViewer()">
          <PhotoFrame class="viewer-frame" :style="{ '--ratio': ratio }" :src="fullLoaded ? fullSrc : previewSrc" :alt="alt" :box="box" :frame="frame" :show-box="showBox" />
        </div>
        <div class="viewer-actions">
          <button v-if="box" type="button" class="viewer-button" :aria-pressed="showBox" @click="showBox = !showBox">{{ showBox ? 'Hide outline' : 'Show outline' }}</button>
          <a class="viewer-button" :href="fullSrc" target="_blank" rel="noopener">Open original</a>
        </div>
      </div>
    </Teleport>
  </figure>
</template>
