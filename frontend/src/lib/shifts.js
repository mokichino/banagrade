// How shifts are named and listed. A shift goes by the name the operator typed, otherwise by when it ran:
// automatic shifts all share the same note ("Shift opened automatically at startup"), which says nothing to tell them apart.

const MINUTE = 60_000
const DAY_TIME = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }
const TIME = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }

export function plural(count, word) {
  return `${Number(count || 0).toLocaleString()} ${word}${count === 1 ? '' : 's'}`
}

export function shiftStart(shift) {
  return new Date(shift.started_at).toLocaleString(undefined, DAY_TIME)
}

/** "Oct 27, 02:48 – 13:30", "Oct 26, 18:00 – Oct 27, 05:30", or "Oct 27, 13:46 – now" for the open shift. */
export function shiftRange(shift) {
  if (!shift.ended_at) return `${shiftStart(shift)} – now`
  const start = new Date(shift.started_at)
  const end = new Date(shift.ended_at)
  return `${shiftStart(shift)} – ${end.toLocaleString(undefined, start.toDateString() === end.toDateString() ? TIME : DAY_TIME)}`
}

export function shiftDuration(shift, now = Date.now()) {
  const end = shift.ended_at ? Date.parse(shift.ended_at) : now
  const minutes = Math.max(0, Math.round((end - Date.parse(shift.started_at)) / MINUTE))
  const hours = Math.floor(minutes / 60)
  if (hours >= 24) return `${Math.floor(hours / 24)} d ${hours % 24} h`
  return hours ? `${hours} h ${minutes % 60} min` : `${minutes} min`
}

export function shiftTitle(shift) {
  return shift.name || shiftRange(shift)
}

/** A past shift as the pickers list it: name if any, when it ran, and how many scans it holds. */
export function shiftOptionLabel(shift) {
  const voided = shift.voided_count ? `${shift.voided_count.toLocaleString()} voided` : ''
  return [shift.name, shiftRange(shift), plural(shift.scan_count ?? 0, 'scan'), voided].filter(Boolean).join(' · ')
}

export function currentShift(shifts) {
  return shifts.find(shift => shift.status === 'open') || null
}

/** Closed shifts worth choosing, newest first. Empty ones (restarts, test clean-ups) only clutter the list. */
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
