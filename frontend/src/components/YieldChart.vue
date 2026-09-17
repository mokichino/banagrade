<script setup>
import { computed } from 'vue'
import { Doughnut } from 'vue-chartjs'
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from 'chart.js'

ChartJS.register(ArcElement, Tooltip, Legend)
const props = defineProps({ values: { type: Array, required: true }, total: { type: [String, Number], required: true } })
const chartData = computed(() => ({ labels: props.values.map((item) => item.name), datasets: [{ data: props.values.map((item) => item.value), backgroundColor: props.values.map((item) => item.color), borderWidth: 0, hoverOffset: 8 }] }))
const options = { responsive: true, maintainAspectRatio: false, cutout: '72%', animation: { duration: 1200, easing: 'easeOutQuart' }, plugins: { legend: { display: false } } }
</script>

<template>
  <div class="chart-canvas donut-canvas"><Doughnut :data="chartData" :options="options" /><div class="chart-center"><strong>{{ total }}</strong><small>scanned</small></div></div>
</template>
