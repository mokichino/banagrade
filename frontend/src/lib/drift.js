// Drift indicators from /api/system/drift. A warning asks for a review of disputed frames; it never changes a grade.

export function formatDriftValue(value, unit) {
  if (value === null || value === undefined) return '—'
  return unit === 'rate' ? `${(value * 100).toFixed(1)}%` : value.toFixed(3)
}

export function driftSummary(report) {
  if (!report) return { tone: 'muted', text: 'Waiting for drift data.' }
  if (report.status === 'drift_suspected') {
    const flagged = report.indicators.filter(item => item.status === 'warn').map(item => item.label.toLowerCase())
    return { tone: 'bad', text: `Review disputed frames: ${flagged.join(', ')}.` }
  }
  if (report.status === 'ok') return { tone: 'ok', text: `In line with the test set over the last ${report.scans_considered} scans.` }
  return { tone: 'muted', text: `Needs at least ${report.min_samples} scans per indicator before it can judge drift.` }
}
