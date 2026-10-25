<script setup>
import { computed, ref, watch } from 'vue'
import { apiBase } from '../../composables/useApi.js'

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
watch(() => camera.value.available, available => { if (available) { streamError.value = false; streamKey.value += 1 } })

const illumination = computed(() => {
  const value = camera.value.illumination
  if (!value) return { text: 'Not measured', tone: 'muted' }
  if (value.status === 'ok') return { text: `OK · brightness ${value.mean_brightness}`, tone: 'ok' }
  return { text: value.status === 'dark' ? 'Too dark — check ring light' : 'Lens obstructed', tone: 'bad' }
})
const autofocus = computed(() => {
  if (camera.value.autofocus === 'locked') return { text: `Locked · ${camera.value.lens_position_dioptres} dpt`, tone: 'ok' }
  if (camera.value.autofocus === 'unlocked') return { text: 'Not locked', tone: 'bad' }
  return { text: 'Unavailable', tone: 'muted' }
})
</script>

<template>
  <div class="panel camera-card">
    <div class="panel-heading">
      <div><p class="eyebrow">Camera utility</p><h2>Live top-down preview</h2><p class="muted">Raspberry Pi Camera Module 3 · fixed {{ camera.distance_cm || 45 }} cm above the black velvet surface</p></div>
      <span :class="['status-badge', camera.available ? 'loaded' : 'missing']">{{ camera.available ? 'Streaming' : 'Offline' }}</span>
    </div>
    <div class="camera-preview">
      <img v-if="camera.available && !streamError" :src="streamSrc" alt="Live top-down camera preview of the inspection zone" @error="streamError = true">
      <div v-else class="camera-offline"><strong>Camera unavailable</strong><span>{{ pipeline?.last_error || 'The edge device has not opened the camera.' }}</span></div>
      <span class="preview-tag">Preview 1280×720 · box = what the capture trigger sees · grading uses {{ camera.resolution || 'full resolution' }}</span>
    </div>
    <div class="camera-actions">
      <button class="secondary-button" :disabled="!camera.available || snapshotBusy" @click="openSnapshot">{{ snapshotBusy ? 'Capturing…' : 'Full-resolution snapshot' }}</button>
      <span v-if="snapshotError" class="muted small">{{ snapshotError }}</span>
    </div>
    <slot name="below-preview" />
    <dl class="camera-meta">
      <div><dt>Capture resolution</dt><dd>{{ camera.resolution || 'Unavailable' }}</dd></div>
      <div><dt>Autofocus</dt><dd :class="autofocus.tone">{{ autofocus.text }}</dd></div>
      <div><dt>LED ring light</dt><dd :class="illumination.tone">{{ illumination.text }}</dd></div>
    </dl>
  </div>
</template>
