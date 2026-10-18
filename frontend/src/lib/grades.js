// Shared grade semantics. Colours mirror the physical GPIO LEDs (thesis 3.6.5, 4.8.2):
// Yellow = Class A, Blue = Class B, Red = Rejected.

export const WIDTH_THRESHOLD_PX = 2730.07

export const GRADES = {
  'Class A': { key: 'a', label: 'Class A', description: 'Large hand (≥ 12 cm)' },
  'Class B': { key: 'b', label: 'Class B', description: 'Small hand (8–12 cm)' },
  Rejected: { key: 'r', label: 'Rejected', description: 'Unhealthy at Stage 1' }
}

export const GRADE_FILTERS = ['All', 'Class A', 'Class B', 'Rejected']

export function scanLabel(scanId) {
  if (!scanId) return '—'
  return `#SCN-${String(scanId).replace(/-/g, '').slice(0, 6).toUpperCase()}`
}

export function isTechnicalFailure(scan) {
  return !scan?.final_grade
}

export function finalGradeLabel(scan) {
  return isTechnicalFailure(scan) ? 'Technical failure' : scan.final_grade
}

export function finalGradeKey(scan) {
  return GRADES[scan?.final_grade]?.key || 't'
}

export function stage1Label(scan) {
  return scan?.stage1_status || 'N/A'
}

export function isHealthy(scan) {
  return String(scan?.stage1_status || '').toLowerCase() === 'healthy'
}

/** Stage 2 only runs for Healthy bunches; anything else is N/A (thesis 3.5.4 Rule 1). */
export function stage2Label(scan) {
  if (!isHealthy(scan)) return 'N/A'
  return scan.final_grade === 'Class A' || scan.final_grade === 'Class B' ? scan.final_grade : 'N/A'
}

export function confidencePercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null
  return Math.max(0, Math.min(100, Math.round(Number(value) * 1000) / 10))
}

export function formatConfidence(value) {
  const percent = confidencePercent(value)
  return percent === null ? 'N/A' : `${percent.toFixed(1)}%`
}

export function formatTimestamp(iso) {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

export function matchesSearch(scan, query) {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return [scan.scan_id, scanLabel(scan.scan_id), scan.captured_at, formatTimestamp(scan.captured_at)]
    .some(value => String(value || '').toLowerCase().includes(q))
}

export function matchesGrade(scan, filter) {
  return filter === 'All' || scan.final_grade === filter
}

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—'
  const s = Math.floor(seconds)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d) return `${d}d ${h}h ${m}m`
  if (h) return `${h}h ${m}m`
  return `${m}m ${s % 60}s`
}
