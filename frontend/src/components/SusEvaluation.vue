<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ apiBase: { type: String, required: true } })
const questions = [
  'I think that I would like to use this system frequently.',
  'I found the system unnecessarily complex.',
  'I thought the system was easy to use.',
  'I think that I would need the support of a technical person to use this system.',
  'I found the various functions in this system were well integrated.',
  'I thought there was too much inconsistency in this system.',
  'I would imagine that most people would learn to use this system very quickly.',
  'I found the system very cumbersome to use.',
  'I felt very confident using the system.',
  'I needed to learn a lot of things before I could get going with this system.'
]
const responses = ref(Array(10).fill(null))
const submitted = ref(false)
const submitting = ref(false)
const error = ref('')
const complete = computed(() => responses.value.every(response => response !== null))

async function submit() {
  if (!complete.value) return
  submitting.value = true
  error.value = ''
  try {
    const response = await fetch(`${props.apiBase}/api/sus/responses`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ responses: responses.value }) })
    if (!response.ok) throw new Error((await response.json()).detail || 'Submission failed')
    submitted.value = true
  } catch (submitError) { error.value = submitError.message } finally { submitting.value = false }
}
</script>

<template>
  <section class="panel survey"><p class="eyebrow">OPERATOR RESEARCH</p><h2>System Usability Scale</h2><p class="muted">Please answer every statement based on your experience with Banagrade.</p>
    <div v-if="submitted" class="notice">Your anonymous survey response was submitted successfully.</div>
    <form v-else @submit.prevent="submit">
      <fieldset v-for="(question, index) in questions" :key="question" class="survey-question"><legend>{{ index + 1 }}. {{ question }}</legend><div class="likert"><label v-for="value in 5" :key="value"><input v-model="responses[index]" type="radio" :name="`sus-${index}`" :value="value"><span>{{ ['Strongly disagree', 'Disagree', 'Neither', 'Agree', 'Strongly agree'][value - 1] }}</span></label></div></fieldset>
      <p v-if="error" class="alert">{{ error }}</p><button class="primary-button" :disabled="!complete || submitting">{{ submitting ? 'Submitting...' : 'Submit evaluation' }}</button>
    </form>
  </section>
</template>