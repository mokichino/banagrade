<script setup>
defineProps({ scans: { type: Array, required: true } })
defineEmits(['select'])
</script>

<template>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Scan</th><th>Time</th><th>Health</th><th>Length</th><th>Grade</th><th></th></tr></thead>
      <tbody>
        <tr v-for="scan in scans" :key="scan.scan_id">
          <td class="mono">{{ scan.scan_id.slice(0, 8) }}</td>
          <td>{{ scan.captured_at }}</td>
          <td>{{ scan.stage1_status || 'Unavailable' }}</td>
          <td>{{ scan.calculated_length_cm ? `${scan.calculated_length_cm} cm` : '—' }}</td>
          <td><span :class="['grade-chip', scan.final_grade === 'Class A' ? 'a' : scan.final_grade === 'Class B' ? 'b' : scan.final_grade === 'Rejected' ? 'r' : 't']">{{ scan.final_grade || 'Technical' }}</span></td>
          <td><button class="text-button" @click="$emit('select', scan)">Details</button></td>
        </tr>
        <tr v-if="!scans.length"><td colspan="6" class="empty">No completed scans.</td></tr>
      </tbody>
    </table>
  </div>
</template>