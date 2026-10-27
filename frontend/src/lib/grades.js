// Shared grade semantics. Colours mirror the physical GPIO LEDs (thesis 3.6.5, 4.8.2):
// Yellow = Class A, Blue = Class B, Red = Rejected.

export const WIDTH_THRESHOLD_PX = 2730.07

export const GRADES = {
  'Class A': { key: 'a', label: 'Class A', description: 'Large hand (width ≥ 2730.07 px)' },
  'Class B': { key: 'b', label: 'Class B', description: 'Small hand (width < 2730.07 px)' },
  Rejected: { key: 'r', label: 'Rejected', description: 'Unhealthy at Stage 1' }
}

export const GRADE_FILTERS = ['All', 'Class A', 'Class B', 'Rejected', 'Technical failure', 'Disputed']

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

const REASONS = { SURFACE_UNHEALTHY: 'Unhealthy at Stage 1' }

/** Why a scan was not graded, in plain words; '' for a graded scan. Thresholds come from the stored error text. */
export function failureReason(scan) {
  if (!scan) return ''
  if (!isTechnicalFailure(scan)) return REASONS[scan.rejection_reason] || ''
  const limit = String(scan.error_details || '').match(/below (\d+(?:\.\d+)?)/)
  const needs = limit ? ` (needs ${Math.round(Number(limit[1]) * 100)}%)` : ''
  const percent = value => `${Math.round(Number(value) * 100)}%`
  switch (scan.rejection_reason) {
    case 'LOW_CONFIDENCE':
      return `Unsure: ${scan.stage1_status || 'Stage 1'} ${percent(scan.stage1_confidence)}${needs} · check by hand`
    case 'DETECTION_FAILED':
      return scan.stage2_confidence != null ? `Not measured: outline ${percent(scan.stage2_confidence)}${needs} · check by hand` : 'Not measured: no outline found · check by hand'
    case 'NOT_A_BUNCH':
      return 'Not a bunch: no banana colour'
    case 'PIPELINE_ERROR':
      return `Scan error: ${scan.error_details || 'see System Status'}`
    default:
      return scan.error_details || ''
  }
}

/** Hover text for the Disputed badge: what the model said and the latest reason. */
export function disputeSummary(scan) {
  if (!scan?.disputed) return ''
  const model = scan.model_grade ? `Model graded ${scan.model_grade === 'Technical Failure' ? 'Technical failure' : scan.model_grade}` : 'Disputed'
  return scan.dispute_reason ? `${model} · ${scan.dispute_reason}` : model
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

/** A shift as the pickers list it: its name, when it started and how many scans it holds. */
export function shiftLabel(shift) {
  const started = new Date(shift.started_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
  const count = shift.scan_count ?? 0
  return `${shift.notes || 'Unnamed shift'} · ${started} · ${count} scan${count === 1 ? '' : 's'}`
}

export function matchesSearch(scan, query) {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return [scan.scan_id, scanLabel(scan.scan_id), scan.captured_at, formatTimestamp(scan.captured_at)]
    .some(value => String(value || '').toLowerCase().includes(q))
}

export function matchesGrade(scan, filter) {
  if (filter === 'Technical failure') return isTechnicalFailure(scan)
  if (filter === 'Disputed') return Boolean(scan.disputed)
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
