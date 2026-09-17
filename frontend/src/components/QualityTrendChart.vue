<script setup>
import { computed } from 'vue'
import { Line } from 'vue-chartjs'
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler } from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler)

const props = defineProps({ series: { type: Array, required: true } })

const chartData = computed(() => ({
  labels: props.series.map((item) => item.time),
  datasets: [{
    label: 'Quality index',
    data: props.series.map((item) => item.rate),
    borderColor: '#3b82f6',
    backgroundColor: 'rgba(59, 130, 246, .12)',
    fill: true,
    tension: .42,
    pointRadius: 4,
    pointHoverRadius: 7,
    pointBackgroundColor: '#ffffff',
    pointBorderColor: '#3b82f6',
    pointBorderWidth: 2,
  }],
}))

const options = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { intersect: false, mode: 'index' },
  animation: { duration: 1400, easing: 'easeOutQuart' },
  scales: {
    y: { beginAtZero: true, max: 20, grid: { color: '#eef0f3' }, ticks: { callback: (value) => `${value}%` } },
    x: { grid: { display: false } },
  },
  plugins: {
    legend: { display: false },
    tooltip: { callbacks: { label: (context) => ` Rejection rate: ${context.parsed.y}%` } },
  },
}
</script>

<template>
  <div class="trend-chart chart-canvas" aria-label="Weekly quality trend chart">
    <Line :data="chartData" :options="options" />
  </div>
</template>
