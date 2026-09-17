<script setup>
import { computed } from 'vue'
import { Line } from 'vue-chartjs'
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler } from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler)
const props = defineProps({ series: { type: Array, required: true } })
const chartData = computed(() => ({ labels: props.series.map((item) => item.time), datasets: [{ data: props.series.map((item) => item.rate), borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,.12)', fill: true, tension: .4, pointRadius: 4, pointBackgroundColor: '#ffffff', pointBorderWidth: 2 }] }))
const options = { responsive: true, maintainAspectRatio: false, animation: { duration: 1200, easing: 'easeOutQuart' }, scales: { y: { beginAtZero: true, grid: { color: '#eef0f3' }, ticks: { callback: (value) => `${value}%` } }, x: { grid: { display: false } } }, plugins: { legend: { display: false } } }
</script>

<template><div class="line-chart chart-canvas"><Line :data="chartData" :options="options" /></div></template>
