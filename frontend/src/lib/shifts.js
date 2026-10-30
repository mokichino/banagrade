// How shifts are named and listed. There is one shift per day, opened and closed by the service, so a shift goes by
// the name the operator typed, otherwise by its date.

const MINUTE = 60_000
const DAY_TIME = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }
const DATE = { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }

export function plural(count, word) {
  return `${Number(count || 0).toLocaleString()} ${word}${count === 1 ? '' : 's'}`
}

export function shiftStart(shift) {
  return new Date(shift.started_at).toLocaleString(undefined, DAY_TIME)
}

/** The day a shift covers, e.g. "Tue, Oct 27, 2026". */
export function shiftDate(shift) {
  return new Date(shift.started_at).toLocaleDateString(undefined, DATE)
}

export function shiftDuration(shift, now = Date.now()) {
  const end = shift.ended_at ? Date.parse(shift.ended_at) : now
  const minutes = Math.max(0, Math.round((end - Date.parse(shift.started_at)) / MINUTE))
  const hours = Math.floor(minutes / 60)
  if (hours >= 24) return `${Math.floor(hours / 24)} d ${hours % 24} h`
  return hours ? `${hours} h ${minutes % 60} min` : `${minutes} min`
}

export function shiftTitle(shift) {
  return shift.name || shiftDate(shift)
}

/** A past shift as the pickers list it: name if any, its date, and how many scans it holds. */
export function shiftOptionLabel(shift) {
  const voided = shift.voided_count ? `${shift.voided_count.toLocaleString()} voided` : ''
  return [shift.name, shiftDate(shift), plural(shift.scan_count ?? 0, 'scan'), voided].filter(Boolean).join(' · ')
}

export function currentShift(shifts) {
  return shifts.find(shift => shift.status === 'open') || null
}

/** Closed shifts worth choosing, newest first. Empty ones (from before shifts were daily) only clutter the list. */
export function pastShifts(shifts) {
  return shifts.filter(shift => shift.status !== 'open' && (shift.scan_count > 0 || shift.voided_count > 0))
}

/** The shift a picker value stands for: null for 'all', the open shift for 'active', else that past shift. */
export function scopeShift(scope, shifts) {
  if (scope === 'all') return null
  if (scope === 'active') return currentShift(shifts)
  return shifts.find(shift => shift.id === scope) || null
}

export function scopeTitle(scope, shifts) {
  if (scope === 'all') return 'All shifts'
  if (scope === 'active') return 'Current shift'
  const shift = scopeShift(scope, shifts)
  return shift ? shiftTitle(shift) : 'Past shift'
}

/** The scope in full, for export headers. */
export function scopeDescription(scope, shifts) {
  const shift = scopeShift(scope, shifts)
  if (scope === 'all') return 'All shifts'
  if (scope === 'active') return shift ? `Current shift · ${shiftOptionLabel(shift)}` : 'Current shift'
  return shift ? shiftOptionLabel(shift) : 'Past shift'
}

/** The ?session= query for a scope; '' means every shift. */
export function scopeQuery(scope) {
  return scope === 'all' ? '' : `session=${encodeURIComponent(scope)}`
}
