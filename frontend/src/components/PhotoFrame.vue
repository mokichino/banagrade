<script setup>
import { ref } from 'vue'

// One scan photo with the Stage 2 box drawn over it. `box` and `frame` (the full frame's width and height) are both
// in full-frame pixels, so the overlay lines up on any copy of the photo, a quarter-size preview or the original.
defineProps({
  src: { type: String, required: true },
  alt: { type: String, required: true },
  box: { type: Array, default: null },
  frame: { type: Object, default: null },
  showBox: { type: Boolean, default: true }
})
const emit = defineEmits(['load', 'error'])
const ratio = ref(null)

function loaded(event) {
  const { naturalWidth: width, naturalHeight: height } = event.target
  if (width && height) ratio.value = `${width} / ${height}`
  emit('load', width && height ? { width, height } : null)
}
</script>

<template>
  <div class="photo-frame" :style="ratio ? { aspectRatio: ratio } : null">
    <img :src="src" :alt="alt" decoding="async" @load="loaded" @error="emit('error')" />
    <svg v-if="showBox && box && frame" class="photo-box" :viewBox="`0 0 ${frame.width} ${frame.height}`" preserveAspectRatio="none" aria-hidden="true">
      <rect class="photo-box-halo" :x="box[0]" :y="box[1]" :width="box[2] - box[0]" :height="box[3] - box[1]" />
      <rect class="photo-box-line" :x="box[0]" :y="box[1]" :width="box[2] - box[0]" :height="box[3] - box[1]" />
    </svg>
  </div>
</template>
