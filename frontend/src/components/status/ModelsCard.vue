<script setup>
import { computed } from 'vue'

const props = defineProps({ models: { type: Object, default: null } })
const STATE_LABEL = { loaded: 'Loaded', missing: 'Missing', error: 'Error' }
const entries = computed(() => props.models?.models || [])
const presence = computed(() => (props.models?.presence_source === 'dedicated' ? 'Dedicated YOLO11n-presence model' : 'Stage 2 banana_bunch detector'))
</script>

<template>
  <div class="panel models-card">
    <p class="eyebrow">AI models</p>
    <h2>Inference stack</h2>
    <p v-if="models?.error" class="alert compact">{{ models.error }}</p>
    <div class="model-list">
      <div v-for="model in entries" :key="model.key" class="model-item">
        <div class="model-head">
          <span class="model-file" tabindex="0" :aria-describedby="`path-${model.key}`">
            {{ model.label }}
            <span :id="`path-${model.key}`" role="tooltip" class="path-tooltip">{{ model.path }}</span>
          </span>
          <span :class="['status-badge', model.state]">{{ STATE_LABEL[model.state] }}</span>
        </div>
        <dl class="kv-grid">
          <dt>Stage</dt><dd>{{ model.key === 'stage1' ? 'Stage 1' : 'Stage 2' }}</dd>
          <dt>Architecture</dt><dd>{{ model.architecture }}</dd>
          <dt>Task</dt><dd>{{ model.task }}</dd>
          <dt>Input</dt><dd>{{ model.key === 'stage1' ? 'HSV-masked RGB, 224 × 224' : 'Raw RGB, 640 × 640 letterbox' }}</dd>
        </dl>
      </div>
    </div>
    <dl class="kv-grid decision-grid">
      <dt>Empirical threshold</dt><dd><b>{{ models?.empirical_threshold_px ?? 2730.07 }} px</b></dd>
      <dt>Measurement</dt><dd>Horizontal bbox {{ models?.length_axis || 'width' }} in the 4608 × 2592 frame</dd>
      <dt>Decision</dt><dd>≥ threshold → Class A · below → Class B · Unhealthy → Rejected</dd>
      <dt>Capture trigger</dt><dd>{{ presence }}</dd>
    </dl>
  </div>
</template>
